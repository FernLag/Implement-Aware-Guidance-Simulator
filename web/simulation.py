"""Bridge between the web layer and the simulation core.

The core is imported, never modified. This module converts a validated
request into the objects `aggsim` already expects, runs one pass, and returns
plain JSON-safe data.

Series are downsampled before they leave here. A 300 second run at a 10 ms
timestep is 30,000 samples per channel, which no chart needs and which would
make the response two orders of magnitude larger than the information in it.
"""

from __future__ import annotations

import math

import numpy as np

from aggsim.analysis.coverage import coverage_between_passes
from aggsim.catalog import load_catalog
from aggsim.catalog.param import Param
from aggsim.config import load_steering
from aggsim.config.terrain import Terrain
from aggsim.control import (
    PurePursuitGains,
    StanleyGains,
    make_pure_pursuit,
    make_stanley,
)
from aggsim.geometry import ABLine
from aggsim.model import State, from_tractor, implement_from_catalog
from aggsim.sim import SimConfig, simulate

LINE = ABLine((0.0, 0.0), (1.0, 0.0))
MAX_POINTS = 600
BASE_DT = 0.01


class SimulationError(ValueError):
    """A request that is well formed but cannot be run as asked."""


def _catalog():
    return load_catalog()


def catalog_payload() -> dict:
    """Machines and their provenance, for the picker and the catalog page."""
    catalog = _catalog()

    def param(p: Param | None) -> dict | None:
        if p is None:
            return None
        return {
            "value": p.value,
            "unit": p.unit,
            "assumed": p.assumed,
            "source": p.source,
            "rationale": p.rationale,
            "note": p.note,
        }

    tractors = []
    for t in sorted(catalog.tractors.values(), key=lambda x: x.wheelbase.value):
        tractors.append({
            "id": t.id,
            "name": t.name,
            "manufacturer": t.manufacturer,
            "years": t.years,
            "steering_type": t.steering_type,
            "simulatable": t.steering_type != "articulated",
            "notes": t.notes,
            "wheelbase": param(t.wheelbase),
            "mass": param(t.mass),
            "engine_power": param(t.engine_power),
            "drawbar_power": param(t.drawbar_power),
            "max_steer_angle": param(t.max_steer_angle),
        })

    implements = []
    for i in sorted(catalog.implements.values(), key=lambda x: x.working_width.value):
        implements.append({
            "id": i.id,
            "name": i.name,
            "manufacturer": i.manufacturer,
            "type": i.type,
            "notes": i.notes,
            "working_width": param(i.working_width),
            "mass": param(i.mass),
            "hitch_distance": param(i.hitch_distance),
            "implement_wheelbase": param(i.implement_wheelbase),
        })

    assumed = [
        {"entry": name, "field": field, "value": p.value, "unit": p.unit,
         "rationale": p.rationale}
        for name, field, p in catalog.assumed_params()
    ]

    return {"tractors": tractors, "implements": implements, "assumed": assumed}


def _downsample(array: np.ndarray, step: int) -> list[float]:
    thinned = array[::step]
    return [None if not math.isfinite(v) else round(float(v), 6) for v in thinned]


def run_simulation(req, max_steps: int) -> dict:
    catalog = _catalog()

    try:
        tractor = catalog.tractor(req.tractor)
    except KeyError:
        raise SimulationError(f"Unknown tractor '{req.tractor}'.") from None

    try:
        params = from_tractor(tractor)
    except ValueError as exc:
        raise SimulationError(str(exc)) from None

    geometry = None
    implement = None
    if req.implement:
        try:
            implement = catalog.implement(req.implement)
        except KeyError:
            raise SimulationError(f"Unknown implement '{req.implement}'.") from None
        geometry = implement_from_catalog(implement)

    # Bound CPU by total integration steps, coarsening the timestep rather
    # than refusing the request outright.
    dt = BASE_DT
    steps = int(req.duration / dt)
    if steps > max_steps:
        dt = req.duration / max_steps
        steps = max_steps

    terrain = Terrain(
        slope_angle=math.radians(req.slope_deg),
        slope_sign=float(req.slope_sign),
        slip=req.slip,
        implement_drift_ratio=Param(
            value=req.implement_drift_ratio,
            unit="dimensionless",
            assumed=True,
            rationale="selected in the web interface",
        ),
    )

    if req.controller == "pure_pursuit":
        controller = make_pure_pursuit(
            LINE, req.speed,
            PurePursuitGains(k=req.lookahead_gain, l_min=req.lookahead_min),
            params,
        )
    else:
        controller = make_stanley(
            LINE, req.speed, StanleyGains(k_e=req.stanley_gain), params
        )

    config = SimConfig(speed=req.speed, dt=dt, duration=req.duration)
    log = simulate(
        State(0.0, req.initial_offset, 0.0), LINE, controller, params, config,
        steering=load_steering() if req.actuator else None,
        terrain=terrain, geometry=geometry,
    )

    step = max(1, len(log.t) // MAX_POINTS)
    series = {
        "t": _downsample(log.t, step),
        "x": _downsample(log.x, step),
        "y": _downsample(log.y, step),
        "cross_track": _downsample(log.cross_track, step),
        "delta_cmd": _downsample(np.degrees(log.delta_cmd), step),
        "delta": _downsample(np.degrees(log.delta), step),
    }

    summary = {
        "final_cross_track": round(log.final_cross_track(), 5),
        "rms_cross_track": round(log.rms_cross_track(), 5),
        "peak_cross_track": round(float(np.max(np.abs(log.cross_track))), 5),
        "settled": bool(log.is_settled()),
        "dt": round(dt, 5),
        "steps": steps,
    }

    if geometry is not None:
        series["implement_cross_track"] = _downsample(log.implement_cross_track, step)
        series["worst_edge"] = _downsample(log.worst_edge, step)
        coverage = coverage_between_passes(log, log, geometry.working_width)
        summary.update({
            "final_worst_edge": round(float(log.worst_edge[-1]), 5),
            "rms_worst_edge": round(log.rms_worst_edge(), 5),
            "peak_worst_edge": round(float(np.max(np.abs(log.worst_edge))), 5),
            "rms_skip_m": round(coverage.rms_skip, 5),
            "rms_skip_percent": round(coverage.rms_skip_percent, 4),
            "worst_skip_m": round(coverage.worst_skip, 5),
            "working_width": geometry.working_width,
        })

    return {
        "tractor": {"id": tractor.id, "name": tractor.name,
                    "wheelbase": tractor.wheelbase.value},
        "implement": None if implement is None else {
            "id": implement.id, "name": implement.name,
            "type": implement.type, "width": implement.working_width.value,
        },
        "series": series,
        "summary": summary,
    }
