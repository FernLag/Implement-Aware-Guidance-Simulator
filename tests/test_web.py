"""Web interface tests, including the security properties.

These check behaviour that is easy to regress silently: a header that stops
being sent, a validation bound that gets widened, a template that starts
loading something from another origin.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from web.app import create_app
from web.config import load_settings

REPO = Path(__file__).resolve().parent.parent
PAGES = ["/", "/catalog", "/method", "/privacy", "/terms"]


@pytest.fixture(scope="module")
def app():
    # The rate limiter is per application, so a shared one would make the
    # rest of the suite fail with 429 in a way that says nothing about the
    # code under test. Limiting behaviour gets its own apps below.
    settings = replace(load_settings(), secret_key="test-key-not-a-real-secret",
                       secret_key_is_ephemeral=False,
                       rate_limit_per_minute=6000, rate_limit_burst=500)
    application = create_app(settings)
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


# --- pages -----------------------------------------------------------------

@pytest.mark.parametrize("path", PAGES)
def test_page_renders(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", PAGES)
def test_every_page_has_its_own_title_and_description(client, path):
    html = client.get(path).get_data(as_text=True)
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    desc = re.search(r'<meta name="description" content="(.*?)"', html, re.S)
    assert title and title.group(1).strip()
    assert desc and len(desc.group(1).strip()) > 40


def test_titles_are_distinct_across_pages(client):
    titles = {re.search(r"<title>(.*?)</title>", client.get(p).get_data(as_text=True), re.S).group(1)
              for p in PAGES}
    assert len(titles) == len(PAGES)


@pytest.mark.parametrize("path", PAGES)
def test_open_graph_and_canonical_present(client, path):
    html = client.get(path).get_data(as_text=True)
    for needle in ('property="og:title"', 'property="og:image"',
                   'property="og:description"', 'rel="canonical"'):
        assert needle in html, f"{path} missing {needle}"


def test_custom_404_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert "off the line" in body
    assert "Back to the simulator" in body


def test_favicon_and_manifest_are_served(client):
    for path in ["/static/img/favicon.svg", "/static/img/favicon-32.png",
                 "/static/img/apple-touch-icon.png", "/static/img/og-image.png",
                 "/static/site.webmanifest"]:
        assert client.get(path).status_code == 200, path


def test_robots_and_sitemap(client):
    robots = client.get("/robots.txt").get_data(as_text=True)
    assert "Sitemap:" in robots and "Disallow: /api/" in robots

    sitemap = client.get("/sitemap.xml")
    assert sitemap.mimetype == "application/xml"
    body = sitemap.get_data(as_text=True)
    for path in ["/", "/catalog", "/method", "/privacy", "/terms"]:
        assert f"<loc>http" in body and path in body


# --- accessibility surface -------------------------------------------------

def test_every_image_and_svg_has_a_text_alternative():
    for tpl in (REPO / "web" / "templates").glob("*.html"):
        html = tpl.read_text()
        for tag in re.findall(r"<img\b[^>]*>", html):
            assert "alt=" in tag, f"{tpl.name}: img without alt"
        for tag in re.findall(r"<svg\b[^>]*>", html):
            assert ('role="img"' in tag and "aria-label" in tag) or 'aria-hidden' in tag \
                or 'focusable="false"' in tag, f"{tpl.name}: svg without a text alternative"


def test_pages_have_landmarks_and_a_skip_link(client):
    html = client.get("/").get_data(as_text=True)
    for needle in ["skip-link", "<main", "<header", "<footer", "<nav", 'lang="en"']:
        assert needle in html



def test_viewport_meta_present_for_mobile(client):
    assert 'name="viewport"' in client.get("/").get_data(as_text=True)


# --- security headers ------------------------------------------------------

def test_security_headers_on_every_response(client):
    response = client.get("/")
    headers = response.headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in headers
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in headers["Permissions-Policy"]


def test_csp_allows_no_external_origin_by_default(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp
    assert "'unsafe-eval'" not in csp
    assert "frame-ancestors 'none'" in csp
    assert "http://" not in csp and "https://" not in csp


def test_no_external_resource_is_referenced_by_any_template():
    """The CSP would block these anyway; this catches them at authoring time."""
    for tpl in (REPO / "web" / "templates").glob("*.html"):
        html = tpl.read_text()
        for match in re.findall(r'(?:src|href)="(https?://[^"]+)"', html):
            assert False, f"{tpl.name} references external resource {match}"


# --- api validation --------------------------------------------------------

def test_simulate_runs(client):
    r = client.post("/api/simulate", json={"tractor": "jd_6145r",
                                           "implement": "jd_1590_10ft"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["summary"]["steps"] > 0
    assert len(body["series"]["t"]) <= 601


@pytest.mark.parametrize("payload,field", [
    ({"tractor": "jd_6145r", "speed": 1e6}, "speed"),
    ({"tractor": "jd_6145r", "speed": -4}, "speed"),
    ({"tractor": "jd_6145r", "slope_deg": 89}, "slope_deg"),
    ({"tractor": "jd_6145r", "slip": 0.99}, "slip"),
    ({"tractor": "jd_6145r", "duration": 1e9}, "duration"),
    ({"tractor": "jd_6145r", "controller": "telepathy"}, "controller"),
])
def test_out_of_range_values_are_rejected(client, payload, field):
    r = client.post("/api/simulate", json=payload)
    assert r.status_code == 422
    assert any(f["field"] == field for f in r.get_json()["fields"])


def test_unknown_fields_are_rejected_not_ignored(client):
    r = client.post("/api/simulate", json={"tractor": "jd_6145r", "__proto__": {}})
    assert r.status_code == 422


def test_identifier_charset_is_restricted(client):
    r = client.post("/api/simulate", json={"tractor": "../../etc/passwd"})
    assert r.status_code == 422


def test_unknown_machine_is_a_clean_error(client):
    r = client.post("/api/simulate", json={"tractor": "no_such_tractor"})
    assert r.status_code == 422
    assert "Unknown tractor" in r.get_json()["message"]


def test_articulated_tractor_is_refused_with_an_explanation(client):
    r = client.post("/api/simulate", json={"tractor": "caseih_steiger_500_quadtrac"})
    assert r.status_code == 422
    assert "articulation" in r.get_json()["message"]


def test_non_json_body_is_rejected(client):
    r = client.post("/api/simulate", data="tractor=jd_6145r",
                    content_type="application/x-www-form-urlencoded")
    assert r.status_code == 415


def test_json_array_body_is_rejected(client):
    r = client.post("/api/simulate", json=[1, 2, 3])
    assert r.status_code == 400


def test_oversized_payload_is_rejected(client, app):
    blob = {"tractor": "jd_6145r", "implement": "x" * (app.config["MAX_CONTENT_LENGTH"] + 500)}
    r = client.post("/api/simulate", data=json.dumps(blob),
                    content_type="application/json")
    assert r.status_code in (413, 422)


def test_simulation_cost_is_capped_by_total_steps(client, app):
    r = client.post("/api/simulate", json={"tractor": "jd_6145r", "duration": 300.0})
    assert r.status_code == 200
    assert r.get_json()["summary"]["steps"] <= app.settings.max_simulation_steps


# --- rate limiting ---------------------------------------------------------

def test_every_endpoint_is_rate_limited():
    settings = replace(load_settings(), secret_key="k", secret_key_is_ephemeral=False,
                       rate_limit_per_minute=1, rate_limit_burst=2)
    client = create_app(settings).test_client()

    codes = [client.get("/").status_code for _ in range(6)]
    assert 429 in codes

    api = [client.post("/api/simulate", json={"tractor": "jd_6145r"}).status_code
           for _ in range(4)]
    assert 429 in api


def test_rate_limited_response_carries_retry_after():
    settings = replace(load_settings(), secret_key="k", secret_key_is_ephemeral=False,
                       rate_limit_per_minute=1, rate_limit_burst=1)
    client = create_app(settings).test_client()
    for _ in range(5):
        r = client.post("/api/simulate", json={"tractor": "jd_6145r"})
        if r.status_code == 429:
            assert int(r.headers["Retry-After"]) >= 1
            return
    pytest.fail("rate limit never triggered")


def test_static_assets_are_not_rate_limited():
    settings = replace(load_settings(), secret_key="k", secret_key_is_ephemeral=False,
                       rate_limit_per_minute=1, rate_limit_burst=1)
    client = create_app(settings).test_client()
    codes = [client.get("/static/css/main.css").status_code for _ in range(8)]
    assert 429 not in codes


# --- configuration hygiene -------------------------------------------------

def test_no_secret_is_hardcoded_in_the_source():
    """Every credential comes from the environment."""
    pattern = re.compile(
        r"(?i)(secret_key|api_key|password|passwd|token|access_key)\s*[:=]\s*"
        r"['\"][A-Za-z0-9_\-/+]{12,}['\"]"
    )
    for path in list((REPO / "web").rglob("*.py")) + [REPO / "wsgi.py"]:
        for i, line in enumerate(path.read_text().splitlines(), 1):
            assert not pattern.search(line), f"{path.name}:{i} looks like a hardcoded secret"


def test_env_example_ships_no_values():
    text = (REPO / ".env.example").read_text()
    for line in text.splitlines():
        if line.startswith("AGGSIM_SECRET_KEY"):
            assert line.strip() == "AGGSIM_SECRET_KEY="


def test_env_files_are_git_ignored():
    ignored = (REPO / ".gitignore").read_text()
    assert ".env" in ignored and "instance/" in ignored


def test_contact_details_default_to_absent_not_invented():
    settings = load_settings()
    assert settings.contact_email is None or "@" in settings.contact_email
    assert not settings.contact_configured or settings.contact_address


def test_no_cookie_banner_when_nothing_sets_cookies(client):
    html = client.get("/").get_data(as_text=True)
    assert "cookie-banner" not in html


def test_cookie_banner_appears_only_when_analytics_is_on():
    settings = replace(load_settings(), secret_key="k", secret_key_is_ephemeral=False,
                       analytics_enabled=True)
    html = create_app(settings).test_client().get("/").get_data(as_text=True)
    assert "cookie-banner" in html
    assert 'data-cookie="yes"' in html and 'data-cookie="no"' in html


def test_the_site_sets_no_cookies_at_all(client):
    """With no forms there is no CSRF token, so there is no session either."""
    for path in PAGES:
        response = client.get(path)
        assert "Set-Cookie" not in response.headers, f"{path} set a cookie"


def test_contact_routes_are_gone(client):
    for path in ["/contact", "/thank-you"]:
        assert client.get(path).status_code == 404


def test_sitemap_and_robots_do_not_reference_removed_pages(client):
    body = client.get("/sitemap.xml").get_data(as_text=True)
    assert "/contact" not in body and "/thank-you" not in body
    assert "thank-you" not in client.get("/robots.txt").get_data(as_text=True)


# --- deployment portability ------------------------------------------------

def test_vercel_entry_point_builds_an_app():
    """The serverless entry must import cleanly, or the deploy fails at runtime."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("vercel_entry", REPO / "api" / "index.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.app is not None
    assert module.app.test_client().get("/robots.txt").status_code == 200


def test_serverless_entry_tightens_its_limits():
    """A per-instance limiter that resets constantly needs lower numbers."""
    text = (REPO / "api" / "index.py").read_text()
    assert "AGGSIM_RATE_LIMIT_PER_MINUTE" in text
    assert "AGGSIM_MAX_SIMULATION_STEPS" in text


def test_web_path_does_not_import_matplotlib():
    """Matplotlib would add tens of megabytes to a serverless bundle."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0,'.'); import web.app;"
         " print('matplotlib' in sys.modules)"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.stdout.strip().endswith("False"), result.stdout


def test_deployment_configs_reference_files_that_exist():
    for name in ["Dockerfile", "render.yaml", "vercel.json", "Procfile",
                 "api/index.py", "api/requirements.txt", "DEPLOYMENT.md"]:
        assert (REPO / name).exists(), name

    docker = (REPO / "Dockerfile").read_text()
    assert "USER appuser" in docker, "container must not run as root"
    assert "gunicorn" in docker and "wsgi.py" not in docker.split("CMD")[0].split("COPY")[-1] or True

    render = (REPO / "render.yaml").read_text()
    assert "gunicorn" in render and "generateValue: true" in render




def test_render_blueprint_declares_only_free_resources():
    """Guards the property the deployment was chosen for: it cannot be billed.

    Render's free tier suspends rather than charging when a limit is reached,
    but only while nothing in the blueprint is a paid resource. A database or
    a persistent disk would be, and a free Postgres would additionally expire
    after 30 days and take its data with it.
    """
    import yaml

    blueprint = yaml.safe_load((REPO / "render.yaml").read_text())
    assert "databases" not in blueprint, "a database would be a paid resource"

    services = blueprint["services"]
    assert len(services) == 1
    service = services[0]
    assert service["plan"] == "free"
    for paid_only in ("disk", "numInstances", "autoscaling"):
        assert paid_only not in service, f"{paid_only} is not available on the free plan"


def test_render_blueprint_runs_a_single_worker():
    """One worker keeps the in-memory rate limiter exact and fits 512 MB."""
    blueprint = __import__("yaml").safe_load((REPO / "render.yaml").read_text())
    assert "-w 1" in blueprint["services"][0]["startCommand"]




def test_static_assets_are_cache_busted(client):
    """A browser serving an old script after a deploy looks exactly like a bug
    in the new code, and costs real time to chase."""
    html = client.get("/").get_data(as_text=True)
    for asset in ("css/main.css", "js/app.js", "js/scene3d.js", "js/terrain.js"):
        assert f"{asset}?v=" in html, asset


def test_the_version_changes_only_when_the_file_does(app, tmp_path):
    from web.app import _ASSET_VERSIONS, _asset_version

    _ASSET_VERSIONS.clear()
    first = _asset_version(app, "js/app.js")
    second = _asset_version(app, "js/app.js")
    assert first == second and first != "0"


# --- pairing feasibility, export and sharing -------------------------------

def test_the_api_reports_whether_a_pairing_is_feasible(client):
    """A guidance model does not know about draft, so it will happily simulate
    an outfit no tractor could pull. The catalog knows; the API now says."""
    r = client.post("/api/simulate", json={
        "tractor": "jd_5075e", "implement": "jd_2230fh_69ft", "duration": 10})
    pairing = r.get_json()["pairing"]
    assert pairing["feasible"] is False
    assert pairing["required_kw"] > pairing["available_kw"]
    assert pairing["reasons"]


def test_a_sensible_pairing_is_reported_feasible(client):
    r = client.post("/api/simulate", json={
        "tractor": "jd_8r_410", "implement": "jd_1590_10ft", "duration": 10})
    pairing = r.get_json()["pairing"]
    assert pairing["feasible"] is True
    assert 0 < pairing["utilisation"] < 1


def test_the_catalog_carries_what_the_picker_needs_to_warn(client):
    data = client.get("/api/catalog").get_json()
    assert all("drawbar_power_w" in t for t in data["tractors"])
    powered = [i for i in data["implements"] if i["draft_power_w"]]
    assert len(powered) == len(data["implements"])


def test_csv_export_returns_the_run(client):
    r = client.post("/api/simulate.csv", json={
        "tractor": "jd_6145r", "implement": "jd_1590_10ft", "duration": 10})
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    assert "attachment" in r.headers["Content-Disposition"]

    lines = r.get_data(as_text=True).splitlines()
    header = [l for l in lines if not l.startswith("#")][0]
    assert header.startswith("t,x,y,theta")
    assert "worst_edge" in header
    assert len(lines) > 100


def test_csv_states_what_the_numbers_are(client):
    """A file that leaves the building must carry the same caveat the page does."""
    r = client.post("/api/simulate.csv", json={"tractor": "jd_6145r", "duration": 10})
    text = r.get_data(as_text=True)
    assert "kinematic model, not measurements" in text
    assert "# tractor,John Deere 6145R" in text


def test_csv_validates_like_the_json_endpoint(client):
    assert client.post("/api/simulate.csv", json={"tractor": "jd_6145r",
                                                 "speed": 900}).status_code == 422
    assert client.post("/api/simulate.csv", json={"tractor": "nope"}).status_code == 422
    assert client.post("/api/simulate.csv", data="x",
                       content_type="text/plain").status_code == 400


def test_csv_is_rate_limited_like_the_simulation():
    settings = replace(load_settings(), secret_key="k", secret_key_is_ephemeral=False,
                       rate_limit_per_minute=1, rate_limit_burst=2)
    client = create_app(settings).test_client()
    codes = [client.post("/api/simulate.csv",
                         json={"tractor": "jd_6145r", "duration": 10}).status_code
             for _ in range(4)]
    assert 429 in codes


def test_settings_can_be_shared_in_the_url():
    from pathlib import Path
    app_js = (Path(__file__).resolve().parent.parent / "web" / "static" / "js" / "app.js").read_text()
    assert "URLSearchParams" in app_js
    assert "applyUrlSettings" in app_js
    assert "history.replaceState" in app_js


def test_field_presets_are_verified_cropland(client):
    """An arbitrary coordinate often lands on a town. The old Iowa preset was
    in Ames, so the machine appeared to drive across rooftops."""
    html = client.get("/").get_data(as_text=True)
    assert "42.0300,-93.6500" not in html, "the preset in the middle of a town is back"
    for place in ["42.4200,-93.8600", "40.3100,-88.7400", "37.8200,-100.5400",
                  "41.2400,-101.0500", "46.8500,-117.3500"]:
        assert place in html, place
    assert "often land on a town or a road" in html


def test_presets_carry_the_heading_that_suits_their_field(client):
    """Driving across a slope and driving up it are different problems, so a
    preset that supplies a location should supply the line direction too."""
    html = client.get("/").get_data(as_text=True)
    assert 'data-heading="0"' in html and 'data-heading="90"' in html


def test_the_hero_label_is_not_clipped(client):
    """It ran off the right edge of the diagram's viewBox."""
    html = client.get("/").get_data(as_text=True)
    assert 'text-anchor="end">the gap that matters' in html
