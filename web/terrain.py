"""Real aerial imagery and elevation, from USGS.

Two public services, both free, neither needing a key or an account:

    imagery    basemap.nationalmap.gov  USGS National Map imagery tiles
    elevation  elevation.nationalmap.gov  3DEP, sampled at 1 m where available

WHY THIS IS PROXIED RATHER THAN FETCHED BY THE BROWSER. Loading tiles directly
would widen the content security policy and make every visitor's browser talk
to a third party. Fetching them here keeps `img-src 'self'`, so from the
visitor's side nothing leaves this origin and the site still sets no cookies.
The server makes the outbound request instead, which the privacy page states.

SERVER SIDE REQUEST FORGERY. The host is a fixed allowlist and no part of a
URL is taken from the request. Tile coordinates are integers checked against
the zoom level, and coordinates are checked against the globe, so a caller
cannot steer these requests anywhere else.

COVERAGE. Both services are United States only. Outside it the elevation
service returns its no-data value, which is reported as unavailable rather
than converted into a slope of zero.
"""

from __future__ import annotations

import json
import math
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass

IMAGERY_HOST = "basemap.nationalmap.gov"
ELEVATION_HOST = "elevation.nationalmap.gov"
ALLOWED_HOSTS = frozenset({IMAGERY_HOST, ELEVATION_HOST})

TILE_URL = (
    "https://" + IMAGERY_HOST +
    "/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}"
)
SAMPLES_URL = (
    "https://" + ELEVATION_HOST +
    "/arcgis/rest/services/3DEPElevation/ImageServer/getSamples"
)

MAX_ZOOM = 19
TIMEOUT = 6.0
USER_AGENT = "implement-aware-guidance-simulator/1.0 (research tool)"

# 3DEP reports missing data as a large negative sentinel rather than null.
NO_DATA_BELOW = -1e5

ATTRIBUTION = "Imagery and elevation courtesy of the U.S. Geological Survey"


class TerrainError(RuntimeError):
    """Upstream did not give us usable data."""


class _Cache:
    """Small LRU, so a busy page does not hammer a public service."""

    def __init__(self, limit: int) -> None:
        self._data: OrderedDict = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def put(self, key, value) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._limit:
                self._data.popitem(last=False)


_tiles = _Cache(limit=512)
_elevation = _Cache(limit=256)


def _ssl_context() -> ssl.SSLContext:
    """A verifying TLS context that works on installs with no system bundle.

    Some Python builds, notably the python.org macOS ones, ship without a root
    certificate file at the default path, so every HTTPS call fails with
    CERTIFICATE_VERIFY_FAILED. certifi supplies the bundle where that happens.
    Verification is never disabled: an unverified fetch would let anyone on the
    path substitute the imagery and the elevation this tool reports as fact.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_context = _ssl_context()


def _open(url: str, data: bytes | None = None) -> bytes:
    host = urllib.parse.urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        # Belt on top of the fact that no URL here is caller supplied.
        raise TerrainError("refusing to fetch from an unexpected host")
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=_context) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise TerrainError(f"upstream returned {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TerrainError(f"upstream unavailable: {reason}") from None


# ---------------------------------------------------------------- imagery

def valid_tile(z: int, x: int, y: int) -> bool:
    if not (0 <= z <= MAX_ZOOM):
        return False
    span = 1 << z
    return 0 <= x < span and 0 <= y < span


def fetch_tile(z: int, x: int, y: int) -> bytes:
    if not valid_tile(z, x, y):
        raise TerrainError("tile coordinates out of range")
    key = (z, x, y)
    cached = _tiles.get(key)
    if cached is not None:
        return cached
    blob = _open(TILE_URL.format(z=z, x=x, y=y))
    if not blob or len(blob) > 512 * 1024:
        raise TerrainError("unexpected tile payload")
    _tiles.put(key, blob)
    return blob


def tile_for(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Web Mercator tile containing a coordinate."""
    span = 1 << zoom
    x = int((lon + 180.0) / 360.0 * span)
    rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * span)
    return max(0, min(span - 1, x)), max(0, min(span - 1, y))


# -------------------------------------------------------------- elevation

@dataclass(frozen=True)
class FieldSlope:
    elevation: float
    side_slope_deg: float
    along_slope_deg: float
    total_slope_deg: float
    aspect_deg: float
    samples: int
    resolution: float
    heading_deg: float
    downhill_is_right: bool


def sample_elevations(points: list[tuple[float, float]]) -> list[float]:
    """Elevations in metres for (lon, lat) pairs, in one upstream request."""
    for lon, lat in points:
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise TerrainError("coordinate outside the globe")

    key = tuple(round(v, 6) for pair in points for v in pair)
    cached = _elevation.get(key)
    if cached is not None:
        return cached

    geometry = {
        "points": [[round(lon, 7), round(lat, 7)] for lon, lat in points],
        "spatialReference": {"wkid": 4326},
    }
    query = urllib.parse.urlencode({
        "geometry": json.dumps(geometry),
        "geometryType": "esriGeometryMultipoint",
        "returnFirstValueOnly": "true",
        "f": "json",
    })
    blob = _open(SAMPLES_URL + "?" + query)
    try:
        payload = json.loads(blob)
    except ValueError:
        raise TerrainError("elevation service returned something unreadable") from None

    samples = payload.get("samples")
    if not samples or len(samples) != len(points):
        raise TerrainError("elevation service returned no samples for this location")

    ordered = sorted(samples, key=lambda s: s.get("locationId", 0))
    values = []
    for sample in ordered:
        try:
            value = float(sample.get("value"))
        except (TypeError, ValueError):
            raise TerrainError("elevation sample was not a number") from None
        if value < NO_DATA_BELOW:
            raise TerrainError("no elevation data covers this location")
        values.append(value)

    _elevation.put(key, values)
    return values


def field_slope(lat: float, lon: float, heading_deg: float,
                extent_m: float = 60.0) -> FieldSlope:
    """Local ground slope at a field, split into side slope and along slope.

    A plane is least-squares fitted to a grid of elevation samples, giving a
    gradient in metres of rise per metre travelled. That gradient is then
    resolved along the guidance line and across it, because only the across
    component is the side slope the simulation uses.
    """
    metres_per_deg_lat = 111_320.0
    metres_per_deg_lon = metres_per_deg_lat * max(0.05, math.cos(math.radians(lat)))

    offsets = []
    for gx in (-1, 0, 1):
        for gy in (-1, 0, 1):
            offsets.append((gx * extent_m / 2.0, gy * extent_m / 2.0))

    points = [
        (lon + east / metres_per_deg_lon, lat + north / metres_per_deg_lat)
        for east, north in offsets
    ]
    heights = sample_elevations(points)

    # Least squares plane z = a*east + b*north + c.
    n = len(offsets)
    sx = sum(o[0] for o in offsets)
    sy = sum(o[1] for o in offsets)
    sxx = sum(o[0] * o[0] for o in offsets)
    syy = sum(o[1] * o[1] for o in offsets)
    sxy = sum(o[0] * o[1] for o in offsets)
    sz = sum(heights)
    sxz = sum(o[0] * h for o, h in zip(offsets, heights))
    syz = sum(o[1] * h for o, h in zip(offsets, heights))

    det = sxx * (syy * n - sy * sy) - sxy * (sxy * n - sy * sx) + sx * (sxy * sy - syy * sx)
    if abs(det) < 1e-9:
        raise TerrainError("elevation samples were degenerate")

    a = (sxz * (syy * n - sy * sy) - sxy * (syz * n - sy * sz) + sx * (syz * sy - syy * sz)) / det
    b = (sxx * (syz * n - sy * sz) - sxz * (sxy * n - sy * sx) + sx * (sxy * sz - syz * sx)) / det

    # Heading is compass degrees. Travel direction and its right hand side,
    # both as (east, north).
    psi = math.radians(heading_deg)
    along = (math.sin(psi), math.cos(psi))
    across = (math.cos(psi), -math.sin(psi))

    grad_along = a * along[0] + b * along[1]
    grad_across = a * across[0] + b * across[1]
    grad_total = math.hypot(a, b)

    centre = heights[len(heights) // 2]
    aspect = (math.degrees(math.atan2(-a, -b)) + 360.0) % 360.0

    return FieldSlope(
        elevation=round(centre, 2),
        side_slope_deg=round(abs(math.degrees(math.atan(grad_across))), 3),
        along_slope_deg=round(math.degrees(math.atan(grad_along)), 3),
        total_slope_deg=round(math.degrees(math.atan(grad_total)), 3),
        aspect_deg=round(aspect, 1),
        samples=len(points),
        resolution=1.0,
        heading_deg=heading_deg,
        # Positive across-gradient means the ground rises to the right, so the
        # machine drifts left. The simulation takes that as slope_sign.
        downhill_is_right=grad_across < 0,
    )


MAX_PROFILE_STATIONS = 60


def slope_profile(lat: float, lon: float, heading_deg: float, length_m: float,
                  lateral_m: float = 8.0) -> dict:
    """Side slope along a real guidance line, station by station.

    A single slope number answers what a machine does on a uniform hillside.
    This answers what it does in a particular field, which is a different
    question: the ground rolls, so the disturbance changes under the machine
    as it drives.

    At each station the ground is sampled to the left and right of the line and
    the cross gradient taken from the difference. Positive means the ground
    rises to the right, so the machine drifts left, which matches the sign
    convention the simulation uses throughout.

    The station count is capped so one request stays reasonable for a free
    public service; spacing widens for a longer run rather than the request
    growing without bound.
    """
    length_m = max(20.0, min(5000.0, float(length_m)))
    stations = min(MAX_PROFILE_STATIONS, max(4, int(length_m / 6.0) + 1))
    spacing = length_m / (stations - 1)

    psi = math.radians(heading_deg)
    along = (math.sin(psi), math.cos(psi))
    across = (math.cos(psi), -math.sin(psi))

    metres_per_deg_lat = 111_320.0
    metres_per_deg_lon = metres_per_deg_lat * max(0.05, math.cos(math.radians(lat)))

    points = []
    for i in range(stations):
        d = i * spacing
        for side in (-lateral_m, 0.0, lateral_m):
            east = along[0] * d + across[0] * side
            north = along[1] * d + across[1] * side
            points.append((lon + east / metres_per_deg_lon,
                           lat + north / metres_per_deg_lat))

    heights = sample_elevations(points)

    positions, slopes, elevations = [], [], []
    for i in range(stations):
        left, centre, right = heights[3 * i], heights[3 * i + 1], heights[3 * i + 2]
        gradient = (right - left) / (2.0 * lateral_m)
        positions.append(round(i * spacing, 3))
        slopes.append(round(math.atan(gradient), 6))
        elevations.append(round(centre, 2))

    degrees = [math.degrees(a) for a in slopes]
    return {
        "positions_m": positions,
        "side_slope_rad": slopes,
        "side_slope_deg": [round(d, 3) for d in degrees],
        "elevation_m": elevations,
        "stations": stations,
        "spacing_m": round(spacing, 2),
        "length_m": round(length_m, 1),
        "lateral_m": lateral_m,
        "min_deg": round(min(degrees), 3),
        "max_deg": round(max(degrees), 3),
        "mean_abs_deg": round(sum(abs(d) for d in degrees) / len(degrees), 3),
        "elevation_change_m": round(max(elevations) - min(elevations), 2),
        "resolution_m": 1.0,
        "attribution": ATTRIBUTION,
    }


def cache_stats() -> dict:
    return {
        "tiles": {"hits": _tiles.hits, "misses": _tiles.misses},
        "elevation": {"hits": _elevation.hits, "misses": _elevation.misses},
    }
