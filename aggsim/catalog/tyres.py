"""Wheel dimensions derived from catalogued tyre codes.

A tyre size code carries a real overall diameter:

    metric   480/80R50  ->  50 in rim + 2 x 480 mm x 0.80 sidewall
    imperial 18.4R34    ->  34 in rim + 2 x 18.4 in x aspect

so a wheel drawn or simulated from one is the size the machine actually rolls
on. This lives beside the catalog rather than in a renderer because it is
derived from sourced data and is used by both the 3D view and the Stage 7
robot description, which must agree about the machine.

Track width is the one dimension here that is NOT derived. No manufacturer in
this catalog publishes it, so it is an assumption and is marked as one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INCH = 0.0254

# Imperial codes give a section width but no aspect ratio. Pre-metric
# agricultural sizes run near 0.82. The one assumed number in this module.
IMPERIAL_ASPECT = 0.82

_METRIC = re.compile(r"^(\d{2,3})/(\d{2,3})R(\d{2})$")
_IMPERIAL = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)[R-](\d{2})$")


@dataclass(frozen=True)
class Tyre:
    diameter: float  # m
    width: float  # m
    code: str
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
        return Tyre(rim_in * INCH + 2.0 * width * (aspect_pct / 100.0), width, text, False)

    m = _IMPERIAL.match(text)
    if m:
        section_in, rim_in = float(m[1]), int(m[2])
        width = section_in * INCH
        return Tyre(rim_in * INCH + 2.0 * width * IMPERIAL_ASPECT, width, text, True)

    return None


def wheel_dimensions(tractor) -> dict:
    """Radii, widths and a track width for a catalogued tractor.

    Radii come from the tyre codes where they exist. Track width does not
    exist anywhere and is assumed, which the returned dictionary records.
    """
    front = parse_tyre(tractor.tire_front)
    rear = parse_tyre(tractor.tire_rear)
    wheelbase = tractor.wheelbase.value

    front_d = front.diameter if front else wheelbase * 0.55
    rear_d = rear.diameter if rear else wheelbase * 0.68

    return {
        "front_radius": front_d / 2.0,
        "rear_radius": rear_d / 2.0,
        "front_width": front.width if front else 0.42,
        "rear_width": rear.width if rear else 0.58,
        "front_sourced": front is not None,
        "rear_sourced": rear is not None,
        "front_code": front.code if front else None,
        "rear_code": rear.code if rear else None,
        "front_assumed_aspect": front.assumed_aspect if front else True,
        "rear_assumed_aspect": rear.assumed_aspect if rear else True,
        # Row-crop tractors are commonly set near a 60 inch row spacing. Not
        # published, so assumed, and never used by the kinematic model.
        "track_width": max(1.52, rear_d * 1.05),
        "track_sourced": False,
    }
