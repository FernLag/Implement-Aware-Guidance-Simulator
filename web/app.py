"""Flask application for the guidance simulator.

Route handlers stay thin. Validation lives in `schemas`, limits and headers in
`security`, and the physics in `aggsim`, which this package never modifies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, url_for
from pydantic import ValidationError

from .config import Settings, load_settings
from .schemas import FieldRequest, SimulationRequest
from .security import (
    RateLimiter, apply_security_headers, build_csp, too_many_requests,
)
from .simulation import SimulationError, catalog_payload, run_simulation
from .terrain import (
    ATTRIBUTION, TerrainError, fetch_field_image, fetch_tile, field_slope,
    tile_for, valid_tile,
)

log = logging.getLogger("aggsim.web")

PAGES = {
    "index": ("Run a guidance pass", "Simulate how a tractor and its implement track a straight AB line, and see where the two disagree."),
    "catalog": ("Equipment catalog", "Eighteen tractors and twenty one implements, every parameter either traceable to a published source or flagged as an assumption."),
    "method": ("How the model works", "The kinematic bicycle model, pure pursuit and Stanley control, side slope drift, and the implement edge metric, with the closed forms each was checked against."),
    "privacy": ("Privacy", "What this site stores, what it does not, and why it sets no cookies at all."),
    "terms": ("Terms of use", "The terms covering use of this simulator and the limits of what its results mean."),
}


_ASSET_VERSIONS: dict[str, str] = {}


def _asset_version(app: Flask, filename: str) -> str:
    """A short fingerprint of a static file, used as a cache-busting query.

    Without it a browser can keep serving an old script after a deploy, which
    looks exactly like a bug in the new code and wastes time chasing it. The
    value changes when the file does and stays put when it does not.
    """
    cached = _ASSET_VERSIONS.get(filename)
    if cached is not None and not app.debug:
        return cached
    try:
        path = Path(app.static_folder or "") / filename
        stamp = f"{int(path.stat().st_mtime)}-{path.stat().st_size}"
    except OSError:
        stamp = "0"
    _ASSET_VERSIONS[filename] = stamp
    return stamp


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

    @app.url_defaults
    def _version_static(endpoint, values):
        if endpoint == "static" and "filename" in values:
            values["v"] = _asset_version(app, values["filename"])

    # ---- cross cutting ---------------------------------------------------

    @app.before_request
    def _rate_limit():
        # Static assets are cheap and frequent; limiting them would break
        # ordinary page loads long before it stopped anyone.
        if request.endpoint == "static":
            return None
        scope = "api" if request.path.startswith("/api/") else "page"
        cost = 4.0 if request.path.startswith("/api/simulate") else 1.0
        if request.path == "/api/field-image":
            # One image replaces nine tiles, so it is worth a little more.
            scope, cost = "tile", 1.5
        elif request.path == "/healthz":
            # Waking a sleeping instance takes several polls, so this must not
            # be the thing that rate limits the visitor out.
            scope, cost = "health", 0.2
        elif request.path.startswith("/api/tile/"):
            # Tiles are small, cached, and a single view needs several, so they
            # cost less than a simulation while still being counted.
            scope, cost = "tile", 0.5
        elif request.path == "/api/field":
            cost = 3.0
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

    @app.post("/api/simulate.csv")
    def api_simulate_csv():
        """The same run as /api/simulate, as a CSV anyone can open.

        Served from here rather than assembled in the browser so the content
        security policy does not have to allow blob URLs, and so the numbers in
        the file are the ones the model produced rather than ones rounded for
        display.
        """
        raw = request.get_json(silent=True)
        if not isinstance(raw, dict):
            return jsonify({"error": "bad_request",
                            "message": "Body must be a JSON object."}), 400
        try:
            req = SimulationRequest(**raw)
        except ValidationError as exc:
            return jsonify({"error": "validation_failed",
                            "fields": [{"field": ".".join(str(p) for p in e["loc"]),
                                        "message": e["msg"]} for e in exc.errors()]}), 422
        try:
            result = run_simulation(req, settings.max_simulation_steps)
        except SimulationError as exc:
            return jsonify({"error": "cannot_simulate", "message": str(exc)}), 422

        series = result["series"]
        columns = [c for c in ("t", "x", "y", "theta", "delta", "cross_track",
                               "implement_cross_track", "worst_edge")
                   if c in series]
        lines = [
            "# Implement-Aware Guidance Simulator",
            f"# tractor,{result['tractor']['name']}",
            f"# implement,{result['implement']['name'] if result['implement'] else 'none'}",
            f"# controller,{req.controller}",
            f"# speed_m_s,{req.speed}",
            f"# side_slope_deg,{req.slope_deg}",
            f"# slip,{req.slip}",
            "# Simulation output from a kinematic model, not measurements.",
            ",".join(columns),
        ]
        rows = len(series["t"])
        for i in range(rows):
            lines.append(",".join(
                "" if series[c][i] is None else f"{series[c][i]}" for c in columns
            ))

        response = app.response_class("\n".join(lines) + "\n", mimetype="text/csv")
        response.headers["Content-Disposition"] = 'attachment; filename="guidance-run.csv"'
        return response

    @app.get("/api/tile/<int:z>/<int:x>/<int:y>")
    def api_tile(z, x, y):
        """Proxy one USGS imagery tile.

        Proxied rather than fetched by the browser so that img-src can stay
        'self': from the visitor's side nothing leaves this origin.
        """
        # A coordinate the caller got wrong is their error, not the upstream's.
        if not valid_tile(z, x, y):
            return jsonify({"error": "bad_tile",
                            "message": "Tile coordinates are out of range."}), 400
        try:
            blob = fetch_tile(z, x, y)
        except TerrainError as exc:
            return jsonify({"error": "tile_unavailable", "message": str(exc)}), 502
        response = app.response_class(blob, mimetype="image/jpeg")
        # Aerial imagery does not change, so let it cache hard. This is what
        # keeps the load on a free public service reasonable.
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        response.headers["X-Imagery-Attribution"] = ATTRIBUTION
        return response

    @app.get("/api/field-image")
    def api_field_image():
        """One aerial photograph of a field, proxied.

        Every parameter is parsed and clamped here; nothing from the request
        reaches a URL. Preferred over the tile route because NAIP is 0.3 m at
        source and one request replaces nine.
        """
        try:
            lat = float(request.args.get("lat", ""))
            lon = float(request.args.get("lon", ""))
            extent = float(request.args.get("extent", 160.0))
        except (TypeError, ValueError):
            return jsonify({"error": "bad_request",
                            "message": "lat, lon and extent must be numbers."}), 400
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return jsonify({"error": "bad_request",
                            "message": "Coordinates are outside the globe."}), 400
        try:
            blob, meta = fetch_field_image(lat, lon, extent)
        except TerrainError as exc:
            return jsonify({"error": "imagery_unavailable", "message": str(exc)}), 502

        response = app.response_class(blob, mimetype="image/jpeg")
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        response.headers["X-Imagery-Attribution"] = ATTRIBUTION
        response.headers["X-Ground-Half-Metres"] = str(meta["ground_half_m"])
        response.headers["X-Metres-Per-Pixel"] = str(meta["metres_per_pixel"])
        return response

    @app.post("/api/field")
    def api_field():
        if not request.is_json:
            return jsonify({"error": "bad_request",
                            "message": "Send application/json."}), 415
        raw = request.get_json(silent=True)
        if not isinstance(raw, dict):
            return jsonify({"error": "bad_request",
                            "message": "Body must be a JSON object."}), 400
        try:
            req = FieldRequest(**raw)
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
            slope = field_slope(req.lat, req.lon, req.heading_deg, req.extent_m)
        except TerrainError as exc:
            return jsonify({"error": "no_elevation", "message": str(exc)}), 502

        zoom = 16
        tx, ty = tile_for(req.lat, req.lon, zoom)
        return jsonify({
            "elevation_m": slope.elevation,
            "side_slope_deg": slope.side_slope_deg,
            "along_slope_deg": slope.along_slope_deg,
            "total_slope_deg": slope.total_slope_deg,
            "aspect_deg": slope.aspect_deg,
            "downhill_is_right": slope.downhill_is_right,
            "samples": slope.samples,
            "resolution_m": slope.resolution,
            "heading_deg": slope.heading_deg,
            "extent_m": req.extent_m,
            "tile": {"z": zoom, "x": tx, "y": ty},
            "attribution": ATTRIBUTION,
        })

    @app.get("/healthz")
    def healthz():
        """Liveness, readable cross-origin.

        This exists so a static landing page hosted elsewhere can tell when a
        sleeping free-tier instance has woken up, and show that instead of a
        blank thirty second wait. It is the ONLY route that answers
        cross-origin, it takes no input, and it returns no data about anything,
        so widening it costs nothing.
        """
        response = jsonify({"ok": True, "service": "guidance-simulator"})
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Cache-Control"] = "no-store"
        return response

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
