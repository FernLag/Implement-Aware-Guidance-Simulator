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

from aggsim.catalog.tyres import parse_tyre, wheel_dimensions

from .appearance import livery_for, profile_for

# Tyre parsing and wheel dimensions live in aggsim.catalog.tyres, because the
# 3D view and the Stage 7 robot description must agree about the machine, and
# both are derived from catalogued tyre codes rather than invented here.


def machine_geometry(tractor, implement, geometry) -> dict:
    """Everything the renderer needs, with each value marked sourced or not."""
    wheelbase = tractor.wheelbase.value
    dims = wheel_dimensions(tractor)
    front_d = dims["front_radius"] * 2.0
    rear_d = dims["rear_radius"] * 2.0
    front_w, rear_w = dims["front_width"], dims["rear_width"]
    track = dims["track_width"]

    profile_name, profile = profile_for(tractor)

    payload = {
        "manufacturer": tractor.manufacturer,
        "livery": livery_for(tractor.manufacturer),
        "profile": profile,
        "profile_name": profile_name,
        "wheelbase": {"value": round(wheelbase, 3), "sourced": not tractor.wheelbase.assumed},
        "track_width": {"value": round(track, 3), "sourced": False},
        "front_wheel": {
            "diameter": round(front_d, 3), "width": round(front_w, 3),
            "sourced": dims["front_sourced"], "code": dims["front_code"],
            "assumed_aspect": dims["front_assumed_aspect"],
        },
        "rear_wheel": {
            "diameter": round(rear_d, 3), "width": round(rear_w, 3),
            "sourced": dims["rear_sourced"], "code": dims["rear_code"],
            "assumed_aspect": dims["rear_assumed_aspect"],
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
            # Decides which tools are drawn along the bar: discs, tines, row
            # units or laser modules. Appearance only.
            "draft_class": implement.draft_class or "",
            "manufacturer": implement.manufacturer,
            "livery": livery_for(implement.manufacturer, implement=True),
            "working_width": {"value": round(geometry.working_width, 3),
                              "sourced": not implement.working_width.assumed},
            "hitch_distance": {"value": round(geometry.hitch_distance, 3), "sourced": False},
            "implement_wheelbase": {"value": round(geometry.implement_wheelbase, 3),
                                    "sourced": False},
            "frame_depth": {"value": round(max(0.8, geometry.working_width * 0.06), 3),
                            "sourced": False},
            # Rows are drawn only where the manufacturer publishes a spacing.
            # A disk harrow does not work in rows, and inventing a spacing for
            # one that does not state it would put a fabricated number on the
            # screen looking exactly like a real one.
            "row_spacing": None if implement.row_spacing is None else {
                "value": round(implement.row_spacing.value, 4),
                "sourced": not implement.row_spacing.assumed,
                "rows": int(round(geometry.working_width / implement.row_spacing.value)),
            },
        }

    payload["drawing_only"] = [
        "track_width", "body", "frame_depth",
        "hitch_distance", "implement_wheelbase",
    ]
    return payload
