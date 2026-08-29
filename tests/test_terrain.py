"""Tests for the USGS imagery and elevation layer.

The network is not touched here. Upstream access is replaced, so these test
the parts that decide safety and correctness: what a caller is allowed to ask
for, what happens when data is missing, and whether the slope arithmetic is
right.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest

from web import terrain
from web.app import create_app
from web.config import load_settings


@pytest.fixture
def app():
    settings = replace(load_settings(), secret_key="k", secret_key_is_ephemeral=False,
                       rate_limit_per_minute=6000, rate_limit_burst=500)
    return create_app(settings)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clear_caches():
    terrain._tiles._data.clear()
    terrain._elevation._data.clear()
    yield


# --- what a caller may ask for --------------------------------------------

@pytest.mark.parametrize("z,x,y,ok", [
    (0, 0, 0, True), (15, 1000, 1000, True), (19, 5, 5, True),
    (20, 0, 0, False), (-1, 0, 0, False),
    (15, 1 << 15, 0, False), (15, 0, -1, False),
])
def test_tile_bounds(z, x, y, ok):
    assert terrain.valid_tile(z, x, y) is ok


def test_out_of_range_tile_is_a_client_error_not_a_gateway_error(client):
    """The caller got it wrong, so it must not read as an upstream failure."""
    assert client.get("/api/tile/15/99999999/0").status_code == 400
    assert client.get("/api/tile/25/0/0").status_code == 400


def test_only_the_usgs_hosts_are_reachable():
    """No part of a URL comes from a request, and the host is checked anyway."""
    assert terrain.ALLOWED_HOSTS == {
        terrain.IMAGERY_HOST, terrain.NAIP_HOST, terrain.ELEVATION_HOST,
    }
    with pytest.raises(terrain.TerrainError, match="unexpected host"):
        terrain._open("https://example.com/anything")
    with pytest.raises(terrain.TerrainError, match="unexpected host"):
        terrain._open("http://169.254.169.254/latest/meta-data/")


def test_tls_verification_is_never_disabled():
    """An unverified fetch would let anyone on the path substitute the
    elevation this tool reports as fact."""
    context = terrain._ssl_context()
    assert context.verify_mode is not None
    import ssl
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True

    source = (terrain.__file__)
    with open(source) as fh:
        text = fh.read()
    assert "CERT_NONE" not in text
    assert "check_hostname = False" not in text


def test_coordinates_outside_the_globe_are_refused():
    with pytest.raises(terrain.TerrainError, match="outside the globe"):
        terrain.sample_elevations([(200.0, 0.0)])
    with pytest.raises(terrain.TerrainError, match="outside the globe"):
        terrain.sample_elevations([(0.0, 91.0)])


def test_field_request_bounds_are_enforced(client):
    for payload in [{"lat": 999, "lon": 0}, {"lat": 0, "lon": 999},
                    {"lat": 42, "lon": -93, "heading_deg": 400},
                    {"lat": 42, "lon": -93, "extent_m": 5},
                    {"lat": 42, "lon": -93, "extent_m": 5000}]:
        assert client.post("/api/field", json=payload).status_code == 422


def test_unknown_field_is_rejected(client):
    assert client.post("/api/field", json={"lat": 42, "lon": -93, "x": 1}).status_code == 422


# --- missing data ----------------------------------------------------------

def _fake_samples(values):
    def _open(url, data=None):
        payload = {"samples": [
            {"locationId": i, "value": str(v), "resolution": 1}
            for i, v in enumerate(values)
        ]}
        return json.dumps(payload).encode()
    return _open


def test_no_data_sentinel_is_refused_not_treated_as_sea_level(monkeypatch):
    """3DEP reports missing coverage as a large negative number. Turning that
    into an elevation would invent a cliff."""
    monkeypatch.setattr(terrain, "_open", _fake_samples([-1000000.0] * 9))
    with pytest.raises(terrain.TerrainError, match="no elevation data"):
        terrain.field_slope(51.5, -0.12, 90.0)


def test_a_short_sample_list_is_refused(monkeypatch):
    monkeypatch.setattr(terrain, "_open", _fake_samples([100.0, 101.0]))
    with pytest.raises(terrain.TerrainError, match="no samples"):
        terrain.field_slope(42.0, -93.0, 90.0)


def test_unreadable_upstream_response_is_refused(monkeypatch):
    monkeypatch.setattr(terrain, "_open", lambda url, data=None: b"<html>oops</html>")
    with pytest.raises(terrain.TerrainError, match="unreadable"):
        terrain.field_slope(42.0, -93.0, 90.0)


# --- the slope arithmetic --------------------------------------------------

def _plane(grad_east, grad_north, base=100.0):
    """Elevations for the 3x3 grid field_slope samples, on a known plane."""
    def _open(url, data=None):
        import urllib.parse
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        points = json.loads(query["geometry"][0])["points"]
        lat0 = points[4][1]
        mlat, mlon = 111_320.0, 111_320.0 * math.cos(math.radians(lat0))
        lon0 = points[4][0]
        samples = []
        for i, (lon, lat) in enumerate(points):
            east = (lon - lon0) * mlon
            north = (lat - lat0) * mlat
            samples.append({"locationId": i,
                            "value": str(base + grad_east * east + grad_north * north),
                            "resolution": 1})
        return json.dumps({"samples": samples}).encode()
    return _open


def test_flat_ground_gives_zero_slope(monkeypatch):
    monkeypatch.setattr(terrain, "_open", _plane(0.0, 0.0))
    result = terrain.field_slope(42.0, -93.0, 90.0)
    assert result.side_slope_deg == pytest.approx(0.0, abs=1e-6)
    assert result.total_slope_deg == pytest.approx(0.0, abs=1e-6)


def test_a_known_plane_gives_the_known_slope(monkeypatch):
    """Ground rising 10 cm per metre eastward is 5.71 degrees."""
    monkeypatch.setattr(terrain, "_open", _plane(0.10, 0.0))
    expected = math.degrees(math.atan(0.10))
    result = terrain.field_slope(42.0, -93.0, 0.0)  # driving north
    # Driving north, an eastward gradient is entirely a side slope.
    assert result.side_slope_deg == pytest.approx(expected, abs=0.02)
    assert abs(result.along_slope_deg) == pytest.approx(0.0, abs=0.02)
    assert result.total_slope_deg == pytest.approx(expected, abs=0.02)


def test_driving_up_the_slope_moves_it_from_across_to_along(monkeypatch):
    """The same ground, driven two ways. This is the whole point of the
    feature: only the across component is the side slope."""
    monkeypatch.setattr(terrain, "_open", _plane(0.10, 0.0))
    across = terrain.field_slope(42.0, -93.0, 0.0)     # north, slope to the side
    along = terrain.field_slope(42.0, -93.0, 90.0)     # east, straight up it

    assert across.side_slope_deg > 5.0
    assert along.side_slope_deg == pytest.approx(0.0, abs=0.05)
    assert abs(along.along_slope_deg) > 5.0
    assert across.total_slope_deg == pytest.approx(along.total_slope_deg, abs=0.02)


def test_downhill_side_is_reported(monkeypatch):
    monkeypatch.setattr(terrain, "_open", _plane(0.10, 0.0))
    north = terrain.field_slope(42.0, -93.0, 0.0)
    south = terrain.field_slope(42.0, -93.0, 180.0)
    assert north.downhill_is_right != south.downhill_is_right


# --- caching ---------------------------------------------------------------

def test_repeated_lookups_do_not_ask_upstream_again(monkeypatch):
    calls = {"n": 0}
    inner = _plane(0.05, 0.0)

    def counting(url, data=None):
        calls["n"] += 1
        return inner(url, data)

    monkeypatch.setattr(terrain, "_open", counting)
    terrain.field_slope(42.0, -93.0, 90.0)
    terrain.field_slope(42.0, -93.0, 90.0)
    terrain.field_slope(42.0, -93.0, 45.0)  # same samples, different heading
    assert calls["n"] == 1


def test_the_tile_cache_is_bounded():
    cache = terrain._Cache(limit=3)
    for i in range(10):
        cache.put(i, b"x")
    assert len(cache._data) == 3


# --- the browser still talks to nobody -------------------------------------

def test_csp_is_unchanged_by_the_imagery_feature(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "img-src 'self' data:" in csp
    assert "nationalmap" not in csp
    assert "usgs" not in csp.lower()


def test_the_page_requests_imagery_from_this_origin_only():
    from pathlib import Path
    source = (Path(terrain.__file__).parent / "static" / "js" / "terrain.js").read_text()
    assert "/api/" in source
    assert "https://" not in source and "http://" not in source


def test_attribution_is_shown_and_returned(client):
    assert "U.S. Geological Survey" in client.get("/").get_data(as_text=True)
    assert "U.S. Geological Survey" in terrain.ATTRIBUTION


# --- the aerial photograph -------------------------------------------------

JPEG = bytes([0xFF, 0xD8]) + b"x" * 200_000
BLANK = bytes([0xFF, 0xD8]) + b"x" * 5_000


def test_the_tile_service_stops_at_zoom_16():
    """Asking above this returned 404 for every tile, which is why the ground
    silently stayed plain: nine failures and no imagery."""
    assert terrain.IMAGERY_MAX_ZOOM == 16


def test_field_image_returns_a_photograph(monkeypatch):
    monkeypatch.setattr(terrain, "_open", lambda url, data=None, timeout=None: JPEG)
    blob, meta = terrain.fetch_field_image(42.03, -93.65, 160.0)
    assert blob is JPEG
    assert meta["metres_per_pixel"] == pytest.approx(2 * 160.0 / 1024)
    assert meta["ground_half_m"] == 160.0


def test_blank_imagery_outside_coverage_is_refused(monkeypatch):
    """NAIP does not fail outside the United States: it returns a valid but
    blank JPEG, which the magic-byte check alone happily accepted."""
    monkeypatch.setattr(terrain, "_open", lambda url, data=None, timeout=None: BLANK)
    with pytest.raises(terrain.TerrainError, match="no aerial imagery"):
        terrain.fetch_field_image(51.5, -0.12, 160.0)


def test_a_json_error_body_is_not_mistaken_for_an_image(monkeypatch):
    monkeypatch.setattr(terrain, "_open",
                        lambda url, data=None, timeout=None: b'{"error":{"code":400}}')
    with pytest.raises(terrain.TerrainError, match="did not return a photograph"):
        terrain.fetch_field_image(42.0, -93.0, 160.0)


def test_web_mercator_stretch_is_corrected(monkeypatch):
    """Mercator metres are stretched by 1/cos(latitude). Ignoring that would
    scale the photograph against the machine standing on it."""
    seen = {}

    def capture(url, data=None, timeout=None):
        seen["url"] = url
        return JPEG

    monkeypatch.setattr(terrain, "_open", capture)
    terrain.fetch_field_image(60.0, 0.0, 100.0)  # cos(60) = 0.5

    import urllib.parse
    bbox = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)["bbox"][0]
    x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
    # 100 ground metres at 60 degrees is 200 mercator metres either side.
    assert (x1 - x0) / 2 == pytest.approx(200.0, rel=1e-6)


def test_images_get_a_longer_timeout_than_json():
    """Six seconds failed on perfectly good 175 kB responses."""
    assert terrain.IMAGE_TIMEOUT > terrain.TIMEOUT


def test_image_extent_and_size_are_clamped(monkeypatch):
    monkeypatch.setattr(terrain, "_open", lambda url, data=None, timeout=None: JPEG)
    _, small = terrain.fetch_field_image(42.0, -93.0, 1.0)
    _, huge = terrain.fetch_field_image(42.0, -93.0, 99999.0)
    assert small["ground_half_m"] == 40.0
    assert huge["ground_half_m"] == 1500.0


def test_field_image_endpoint_validates_its_input(client, monkeypatch):
    monkeypatch.setattr(terrain, "_open", lambda url, data=None, timeout=None: JPEG)
    assert client.get("/api/field-image?lat=42&lon=-93&extent=160").status_code == 200
    assert client.get("/api/field-image?lat=abc&lon=-93").status_code == 400
    assert client.get("/api/field-image?lat=999&lon=-93").status_code == 400
    assert client.get("/api/field-image").status_code == 400


def test_field_image_endpoint_reports_missing_coverage(client, monkeypatch):
    monkeypatch.setattr(terrain, "_open", lambda url, data=None, timeout=None: BLANK)
    r = client.get("/api/field-image?lat=51.5&lon=-0.12&extent=160")
    assert r.status_code == 502
    assert "no aerial imagery" in r.get_json()["message"]


def test_naip_host_is_in_the_allowlist():
    assert terrain.NAIP_HOST in terrain.ALLOWED_HOSTS
    assert len(terrain.ALLOWED_HOSTS) == 3


def test_the_client_asks_this_origin_for_the_photograph():
    from pathlib import Path
    source = (Path(terrain.__file__).parent / "static" / "js" / "terrain.js").read_text()
    assert "/api/field-image?" in source
    assert "https://" not in source
