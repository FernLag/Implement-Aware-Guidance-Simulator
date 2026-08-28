"""Flask application for the guidance simulator.

Route handlers stay thin. Validation lives in `schemas`, limits and headers in
`security`, and the physics in `aggsim`, which this package never modifies.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask, abort, jsonify, redirect, render_template, request, session, url_for,
)
from pydantic import ValidationError

from .config import Settings, load_settings
from .schemas import ContactRequest, SimulationRequest
from .security import (
    RateLimiter, apply_security_headers, build_csp, too_many_requests,
)
from .simulation import SimulationError, catalog_payload, run_simulation

log = logging.getLogger("aggsim.web")

PAGES = {
    "index": ("Run a guidance pass", "Simulate how a tractor and its implement track a straight AB line, and see where the two disagree."),
    "catalog": ("Equipment catalog", "Eighteen tractors and twenty one implements, every parameter either traceable to a published source or flagged as an assumption."),
    "method": ("How the model works", "The kinematic bicycle model, pure pursuit and Stanley control, side slope drift, and the implement edge metric, with the closed forms each was checked against."),
    "contact": ("Contact", "Ask a question about the model, the equipment catalog, or the results."),
    "thank_you": ("Message received", "Your message has been stored on the server for the operator to read, along with your name and email address so they can reply."),
    "privacy": ("Privacy", "What this site stores, what it does not, and the one cookie it needs to work."),
    "terms": ("Terms of use", "The terms covering use of this simulator and the limits of what its results mean."),
}


def _csrf_token() -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def _csrf_ok(submitted: str | None) -> bool:
    expected = session.get("csrf")
    if not expected or not submitted:
        return False
    return hmac.compare_digest(expected, submitted)


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.secret_key,
        MAX_CONTENT_LENGTH=settings.max_content_length,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.site_origin.startswith("https://"),
        JSON_SORT_KEYS=False,
        TRAP_HTTP_EXCEPTIONS=False,
    )
    app.settings = settings
    limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_burst)
    app.limiter = limiter

    if settings.secret_key_is_ephemeral:
        log.warning(
            "AGGSIM_SECRET_KEY is not set. Using a random key for this process; "
            "sessions will not survive a restart. Set it before deploying."
        )

    # ---- cross cutting ---------------------------------------------------

    @app.before_request
    def _rate_limit():
        # Static assets are cheap and frequent; limiting them would break
        # ordinary page loads long before it stopped anyone.
        if request.endpoint == "static":
            return None
        scope = "api" if request.path.startswith("/api/") else "page"
        cost = 4.0 if request.path == "/api/simulate" else 1.0
        retry = limiter.check(scope, cost)
        if retry is not None:
            if request.path.startswith("/api/"):
                return too_many_requests(retry)
            return render_template("429.html", retry_after=int(retry), **_ctx("index")), 429
        return None

    analytics_origin = None
    if settings.analytics_enabled and settings.analytics_script_url:
        parts = settings.analytics_script_url.split("/")
        if len(parts) >= 3 and parts[0].endswith(":"):
            analytics_origin = f"{parts[0]}//{parts[2]}"
    csp = build_csp(analytics_origin)

    @app.after_request
    def _headers(response):
        return apply_security_headers(
            response, https=settings.site_origin.startswith("https://"), csp=csp
        )

    def _ctx(page: str, **extra) -> dict:
        title, description = PAGES.get(page, PAGES["index"])
        base = {
            "page": page,
            "meta_title": f"{title} | Implement-Aware Guidance Simulator",
            "meta_description": description,
            "settings": settings,
            "canonical": settings.site_origin + request.path,
            "og_image": settings.site_origin + url_for("static", filename="img/og-image.png"),
            "csrf_token": _csrf_token(),
            "year": datetime.now(timezone.utc).year,
        }
        base.update(extra)
        return base

    app.jinja_env.globals["ctx_pages"] = PAGES

    # ---- pages -----------------------------------------------------------

    @app.get("/")
    def index():
        return render_template("index.html", **_ctx("index"))

    @app.get("/catalog")
    def catalog():
        return render_template("catalog.html", data=catalog_payload(), **_ctx("catalog"))

    @app.get("/method")
    def method():
        return render_template("method.html", **_ctx("method"))

    @app.get("/contact")
    def contact():
        return render_template("contact.html", errors={}, values={}, **_ctx("contact"))

    @app.post("/contact")
    def contact_submit():
        form = request.form
        if not _csrf_ok(form.get("csrf_token")):
            return render_template(
                "contact.html",
                errors={"_form": "Your session expired. Please submit the form again."},
                values={k: form.get(k, "") for k in ("name", "email", "message")},
                **_ctx("contact"),
            ), 400

        try:
            payload = ContactRequest(
                name=form.get("name", ""), email=form.get("email", ""),
                message=form.get("message", ""), website=form.get("website", ""),
            )
        except ValidationError as exc:
            errors = {}
            for err in exc.errors():
                field = err["loc"][0] if err["loc"] else "_form"
                errors.setdefault(str(field), err["msg"].replace("Value error, ", ""))
            return render_template(
                "contact.html", errors=errors,
                values={k: form.get(k, "") for k in ("name", "email", "message")},
                **_ctx("contact"),
            ), 400

        if payload.website:
            # Honeypot filled. Accept silently so the bot learns nothing.
            return redirect(url_for("thank_you"))

        if not settings.accepts_messages:
            # Said before the work, not after: the form is disabled in the
            # template too, so this is the belt to that pair of braces.
            return render_template(
                "contact.html",
                errors={"_form": "This deployment has nowhere to store messages, "
                                 "so the form cannot accept them. Nothing was sent."},
                values={k: form.get(k, "") for k in ("name", "email", "message")},
                **_ctx("contact"),
            ), 503

        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "name": payload.name, "email": payload.email, "message": payload.message,
        }
        try:
            path = Path(app.config.get("MESSAGE_STORE") or settings.message_store)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            log.exception("could not store contact message")
            return render_template(
                "contact.html",
                errors={"_form": "The message could not be stored. Please try again later."},
                values={k: form.get(k, "") for k in ("name", "email", "message")},
                **_ctx("contact"),
            ), 500

        return redirect(url_for("thank_you"))

    @app.get("/thank-you")
    def thank_you():
        return render_template("thank_you.html", **_ctx("thank_you"))

    @app.get("/privacy")
    def privacy():
        return render_template("privacy.html", **_ctx("privacy"))

    @app.get("/terms")
    def terms():
        return render_template("terms.html", **_ctx("terms"))

    # ---- api -------------------------------------------------------------

    @app.get("/api/catalog")
    def api_catalog():
        return jsonify(catalog_payload())

    @app.post("/api/simulate")
    def api_simulate():
        if not request.is_json:
            return jsonify({"error": "bad_request",
                            "message": "Send application/json."}), 415
        raw = request.get_json(silent=True)
        if not isinstance(raw, dict):
            return jsonify({"error": "bad_request",
                            "message": "Body must be a JSON object."}), 400
        try:
            req = SimulationRequest(**raw)
        except ValidationError as exc:
            return jsonify({
                "error": "validation_failed",
                "fields": [
                    {"field": ".".join(str(p) for p in e["loc"]),
                     "message": e["msg"].replace("Value error, ", "")}
                    for e in exc.errors()
                ],
            }), 422
        try:
            return jsonify(run_simulation(req, settings.max_simulation_steps))
        except SimulationError as exc:
            return jsonify({"error": "cannot_simulate", "message": str(exc)}), 422

    # ---- crawl surface ---------------------------------------------------

    @app.get("/robots.txt")
    def robots():
        body = "\n".join([
            "User-agent: *",
            "Allow: /",
            "Disallow: /api/",
            "Disallow: /thank-you",
            "",
            f"Sitemap: {settings.site_origin}/sitemap.xml",
            "",
        ])
        return app.response_class(body, mimetype="text/plain")

    @app.get("/sitemap.xml")
    def sitemap():
        paths = [("/", "1.0"), ("/catalog", "0.8"), ("/method", "0.8"),
                 ("/contact", "0.5"), ("/privacy", "0.3"), ("/terms", "0.3")]
        today = datetime.now(timezone.utc).date().isoformat()
        urls = "".join(
            f"<url><loc>{settings.site_origin}{p}</loc>"
            f"<lastmod>{today}</lastmod><priority>{pr}</priority></url>"
            for p, pr in paths
        )
        body = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"{urls}</urlset>")
        return app.response_class(body, mimetype="application/xml")

    # ---- errors ----------------------------------------------------------

    @app.errorhandler(404)
    def not_found(_):
        return render_template("404.html", **_ctx("index")), 404

    @app.errorhandler(413)
    def too_large(_):
        if request.path.startswith("/api/"):
            return jsonify({"error": "payload_too_large",
                            "message": "Request body is too large."}), 413
        return render_template("404.html", **_ctx("index")), 413

    @app.errorhandler(500)
    def server_error(exc):
        log.exception("unhandled error: %s", exc)
        return render_template("500.html", **_ctx("index")), 500

    return app


app = create_app()
