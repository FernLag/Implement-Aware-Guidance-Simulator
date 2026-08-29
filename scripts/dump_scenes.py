"""Dump one simulation result per implement, for the headless geometry check.

    python3 scripts/dump_scenes.py > scenes.json
    node scripts/check_scene_geometry.js scenes.json
"""

from __future__ import annotations

import json
import sys

from aggsim.catalog import load_catalog
from web.schemas import SimulationRequest
from web.simulation import run_simulation

MAX_STEPS = 40_000


def main() -> None:
    catalog = load_catalog()
    scenes = {}
    for implement_id in catalog.implements:
        scenes[implement_id] = run_simulation(
            SimulationRequest(tractor="jd_6145r", implement=implement_id,
                              duration=20.0, slope_deg=6.0, slip=0.1),
            MAX_STEPS,
        )
    scenes["__none__"] = run_simulation(
        SimulationRequest(tractor="jd_6145r", duration=20.0), MAX_STEPS
    )
    # A worked field, so the check covers the pass lines, the turns, and the
    # swath history that only exist in multi-pass mode.
    scenes["__field__"] = run_simulation(
        SimulationRequest(tractor="jd_6145r", implement="jd_1775nt_16row30",
                          passes=4, pass_length=120.0, slope_deg=6.0, slip=0.1),
        MAX_STEPS,
    )
    json.dump(scenes, sys.stdout)


if __name__ == "__main__":
    main()
