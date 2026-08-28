"""Flask application for the guidance simulator.

Route handlers stay thin. Validation lives in `schemas`, limits and headers in
`security`, and the physics in `aggsim`, which this package never modifies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request, url_for
from pydantic import ValidationError

from .config import Settings, load_settings
from .schemas import SimulationRequest
from .security import (
    RateLimiter, apply_security_headers, build_csp, too_many_requests,
)
from .simulation import SimulationError, catalog_payload, run_simulation

log = logging.getLogger("aggsim.web")

PAGES = {
    "index": ("Run a guidance pass", "Simulate how a tractor and its implement track a straight AB line, and see where the two disagree."),
    "catalog": ("Equipment catalog", "Eighteen tractors and twenty one implements, every parameter either traceable to a published source or flagged as an assumption."),
    "method": ("How the model works", "The kinematic bicycle model, pure pursuit and Stanley control, side slope drift, and the implement edge metric, with the closed forms each was checked against."),
    "privacy": ("Privacy", "What this site stores, what it does not, and why it sets no cookies at all."),
    "terms": ("Terms of use", "The terms covering use of this simulator and the limits of what its results mean."),
}


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.secret_key,
        MAX_CONTENT_LENGTH=settings.max_content_length,
        JSON_SORT_KEYS=False,
        TRAP_HTTP_EXCEPTIONS=False,
    )
    app.settings = settings
    limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_burst)
    app.limiter = limiter

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
            "",
            f"Sitemap: {settings.site_origin}/sitemap.xml",
            "",
        ])
        return app.response_class(body, mimetype="text/plain")

    @app.get("/sitemap.xml")
    def sitemap():
        paths = [("/", "1.0"), ("/catalog", "0.8"), ("/method", "0.8"),
                 ("/privacy", "0.3"), ("/terms", "0.3")]
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
