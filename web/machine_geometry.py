"""Dimensions for drawing a machine, kept separate from the physics.

The simulation needs a wheelbase and a working width. A picture needs wheel
diameters, a track width and a body size as well, and those are not all
published. This module derives what it can from sourced catalog data and
flags the rest, using the same distinction the catalog does.

Nothing here feeds back into the model. A drawing dimension being wrong makes
the picture look odd; it cannot change a result. The payload marks which is
which so the interface can say so.

TYRE CODES ARE REAL DATA. The catalog carries manufacturer tyre sizes, and an
overall diameter follows from the code itself:

    metric   480/80R50  ->  50 in rim + 2 x 480 mm x 0.80 sidewall
    imperial 18.4R34    ->  34 in rim + 2 x 18.4 in x aspect

so a drawn wheel is the size the machine actually rolls on, not a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INCH = 0.0254

# Imperial tyre codes give a section width but no aspect ratio. Pre-metric
# agricultural sizes run near 0.82. This is the one number here that is
# assumed rather than read from the code.
IMPERIAL_ASPECT = 0.82

_METRIC = re.compile(r"^(\d{2,3})/(\d{2,3})R(\d{2})$")
_IMPERIAL = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)[R-](\d{2})$")


@dataclass(frozen=True)
class Tyre:
    diameter: float  # m
    width: float  # m
    derived_from: str
    assumed_aspect: bool


def parse_tyre(code: str | None) -> Tyre | None:
    """Overall diameter and section width from a tyre size code."""
    if not code:
        return None
    text = code.strip().replace(" ", "")

    m = _METRIC.match(text)
    if m:
        section_mm, aspect_pct, rim_in = int(m[1]), int(m[2]), int(m[3])
        width = section_mm / 1000.0
        diameter = rim_in * INCH + 2.0 * width * (aspect_pct / 100.0)
        return Tyre(diameter, width, text, assumed_aspect=False)

    m = _IMPERIAL.match(text)
    if m:
        section_in, rim_in = float(m[1]), int(m[2])
        width = section_in * INCH
        diameter = rim_in * INCH + 2.0 * width * IMPERIAL_ASPECT
        return Tyre(diameter, width, text, assumed_aspect=True)

    return None


def machine_geometry(tractor, implement, geometry) -> dict:
    """Everything the renderer needs, with each value marked sourced or not."""
    wheelbase = tractor.wheelbase.value
    front = parse_tyre(tractor.tire_front)
    rear = parse_tyre(tractor.tire_rear)

    # Fall back on proportions of the wheelbase where a tyre code is missing.
    front_d = front.diameter if front else wheelbase * 0.55
    rear_d = rear.diameter if rear else wheelbase * 0.68
    front_w = front.width if front else 0.42
    rear_w = rear.width if rear else 0.58

    # Track width is not published by any manufacturer in this catalog. Row
    # crop tractors are commonly set near a 60 inch row spacing, and the value
    # only affects how wide the machine looks.
    track = max(1.52, rear_d * 1.05)

    payload = {
        "wheelbase": {"value": round(wheelbase, 3), "sourced": not tractor.wheelbase.assumed},
        "track_width": {"value": round(track, 3), "sourced": False},
        "front_wheel": {
            "diameter": round(front_d, 3), "width": round(front_w, 3),
            "sourced": front is not None,
            "code": front.derived_from if front else None,
            "assumed_aspect": front.assumed_aspect if front else True,
        },
        "rear_wheel": {
            "diameter": round(rear_d, 3), "width": round(rear_w, 3),
            "sourced": rear is not None,
            "code": rear.derived_from if rear else None,
            "assumed_aspect": rear.assumed_aspect if rear else True,
        },
        # Body size is drawing only. Proportional to the wheelbase so a compact
        # utility tractor does not come out the size of a row crop one.
        "body": {
            "length": round(wheelbase * 1.15, 3),
            "width": round(track * 0.62, 3),
            "height": round(wheelbase * 0.42, 3),
            "sourced": False,
        },
        "implement": None,
    }

    if implement is not None and geometry is not None:
        payload["implement"] = {
            "name": implement.name,
            "type": geometry.type,
            "working_width": {"value": round(geometry.working_width, 3),
                              "sourced": not implement.working_width.assumed},
            "hitch_distance": {"value": round(geometry.hitch_distance, 3), "sourced": False},
            "implement_wheelbase": {"value": round(geometry.implement_wheelbase, 3),
                                    "sourced": False},
            "frame_depth": {"value": round(max(0.8, geometry.working_width * 0.06), 3),
                            "sourced": False},
        }

    payload["drawing_only"] = [
        "track_width", "body", "frame_depth",
        "hitch_distance", "implement_wheelbase",
    ]
    return payload
