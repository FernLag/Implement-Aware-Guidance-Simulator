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
NAIP_HOST = "imagery.nationalmap.gov"
ELEVATION_HOST = "elevation.nationalmap.gov"
ALLOWED_HOSTS = frozenset({IMAGERY_HOST, NAIP_HOST, ELEVATION_HOST})

TILE_URL = (
    "https://" + IMAGERY_HOST +
    "/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}"
)
SAMPLES_URL = (
    "https://" + ELEVATION_HOST +
    "/arcgis/rest/services/3DEPElevation/ImageServer/getSamples"
)

# The National Map imagery tile service stops at zoom 16. Asking for 17 or
# above returns 404 for every tile, which is exactly what happened when this
# was first wired up: nine tiles all failed and the ground silently stayed
# plain. Nothing above this is worth requesting.
IMAGERY_MAX_ZOOM = 16
MAX_ZOOM = 19

NAIP_URL = (
    "https://" + NAIP_HOST +
    "/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage"
)
# NAIP is 0.3 m at source, against 1.77 m for a zoom 16 tile.
NAIP_PIXELS = 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
# Outside its coverage NAIP does not fail: it returns a valid but blank JPEG,
# which compresses to a fraction of the size of real imagery. Measured, a
# genuine 1024 px field photograph runs 120 to 220 kB while a blank one is
# under 20 kB. This is a heuristic and is treated as one: the real guard is
# that the interface only asks for imagery once the elevation lookup has
# already confirmed the location is covered.
MIN_REAL_IMAGE_BYTES = 30 * 1024
TIMEOUT = 6.0
# A full field photograph is a couple of hundred kilobytes and the service is
# sometimes slow to render one. Six seconds was enough to fail on perfectly
# good responses, so image requests get their own budget.
IMAGE_TIMEOUT = 20.0
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


def _open(url: str, data: bytes | None = None, timeout: float = TIMEOUT) -> bytes:
    host = urllib.parse.urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        # Belt on top of the fact that no URL here is caller supplied.
        raise TerrainError("refusing to fetch from an unexpected host")
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_context) as response:
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


def _mercator(lat: float, lon: float) -> tuple[float, float]:
    r = 6378137.0
    x = r * math.radians(lon)
    y = r * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y


def fetch_field_image(lat: float, lon: float, ground_half_m: float,
                      pixels: int = NAIP_PIXELS) -> tuple[bytes, dict]:
    """One aerial photograph covering a known square of ground.

    Preferred over the tile service for two reasons. NAIP is 0.3 m at source
    against 1.77 m for the best available tile, and asking for an exact
    bounding box means the mapping from field coordinates to image pixels is
    exact rather than reconstructed from tile arithmetic.

    Web Mercator distances are stretched by 1/cos(latitude), so the requested
    box is widened by that factor to cover the ground metres asked for. Getting
    this wrong would scale the photograph against the machine.
    """
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise TerrainError("coordinate outside the globe")
    ground_half_m = max(40.0, min(1500.0, float(ground_half_m)))
    pixels = max(256, min(2048, int(pixels)))

    scale = 1.0 / max(0.05, math.cos(math.radians(lat)))
    half = ground_half_m * scale
    cx, cy = _mercator(lat, lon)
    query = urllib.parse.urlencode({
        "bbox": f"{cx - half},{cy - half},{cx + half},{cy + half}",
        "bboxSR": 3857, "imageSR": 3857,
        "size": f"{pixels},{pixels}",
        "format": "jpeg", "f": "image",
    })

    key = ("naip", round(lat, 5), round(lon, 5), round(ground_half_m, 1), pixels)
    cached = _tiles.get(key)
    if cached is not None:
        return cached

    blob = _open(NAIP_URL + "?" + query, timeout=IMAGE_TIMEOUT)
    if not blob or len(blob) > MAX_IMAGE_BYTES:
        raise TerrainError("unexpected image payload")
    if blob[:2] != bytes([0xFF, 0xD8]):
        # The service answers some errors as JSON with a 200, so the bytes are
        # the only reliable signal that a photograph came back at all.
        raise TerrainError("the imagery service did not return a photograph")
    if len(blob) < MIN_REAL_IMAGE_BYTES:
        raise TerrainError("no aerial imagery covers this location")

    meta = {
        "pixels": pixels,
        "ground_half_m": round(ground_half_m, 1),
        "metres_per_pixel": round(2.0 * ground_half_m / pixels, 4),
        "source": "USGS NAIP",
    }
    _tiles.put(key, (blob, meta))
    return blob, meta


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
    # A grid of several hundred points does not fit in a URL. Servers commonly
    # cut off around 8 kB, and the failure is a 414 rather than anything that
    # explains itself, so anything large goes in a request body instead.
    if len(query) > 3000:
        blob = _open(SAMPLES_URL, data=query.encode("ascii"),
                     timeout=IMAGE_TIMEOUT)
    else:
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


GRID_MIN, GRID_MAX = 5, 21


def elevation_grid(lat: float, lon: float, heading_deg: float,
                   half_m: float, n: int = 17) -> dict:
    """Ground height over a square of field, as an n x n grid.

    `slope_profile` reads the ground along one line, which is all the
    simulation needs. Drawing the ground needs it in two dimensions.

    The frame matches the one the renderer and the imagery mapper already use:
    x runs along the driving heading, y runs across it to the left, and the
    centre of the grid is the requested coordinate. Heights are returned
    relative to that centre point, so the numbers are relief in metres rather
    than altitude above the sea, which is what the renderer wants and which
    keeps them small.

    Row major from the most negative y to the most positive, each row running
    from the most negative x to the most positive.
    """
    n = max(GRID_MIN, min(GRID_MAX, int(n)))
    half_m = max(20.0, min(600.0, float(half_m)))

    psi = math.radians(heading_deg)
    sin_p, cos_p = math.sin(psi), math.cos(psi)

    metres_per_deg_lat = 111_320.0
    metres_per_deg_lon = metres_per_deg_lat * max(0.05, math.cos(math.radians(lat)))

    step = (2.0 * half_m) / (n - 1)
    points = []
    for j in range(n):
        across = -half_m + j * step
        for i in range(n):
            along = -half_m + i * step
            # Same transform as the imagery mapper, so the height grid and the
            # photograph describe the same ground.
            east = along * sin_p - across * cos_p
            north = along * cos_p + across * sin_p
            points.append((lon + east / metres_per_deg_lon,
                           lat + north / metres_per_deg_lat))

    heights = sample_elevations(points)
    centre = heights[(n // 2) * n + (n // 2)]
    relief = [round(h - centre, 3) for h in heights]

    return {
        "n": n,
        "half_m": round(half_m, 2),
        "step_m": round(step, 3),
        "centre_elevation_m": round(centre, 2),
        "heights_m": relief,
        "min_m": round(min(relief), 2),
        "max_m": round(max(relief), 2),
        "relief_m": round(max(relief) - min(relief), 2),
        "heading_deg": heading_deg,
        "resolution_m": 1.0,
        "attribution": ATTRIBUTION,
    }


def cache_stats() -> dict:
    return {
        "tiles": {"hits": _tiles.hits, "misses": _tiles.misses},
        "elevation": {"hits": _elevation.hits, "misses": _elevation.misses},
    }
