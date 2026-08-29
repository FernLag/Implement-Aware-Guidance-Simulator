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

from aggsim.analysis.coverage import (
    coverage_across_passes,
    coverage_between_passes,
)
from aggsim.catalog import check_pairing, load_catalog
from aggsim.catalog.validate import required_draft_power
from aggsim.catalog.param import Param
from aggsim.config import load_steering
from aggsim.config.terrain import SlopeProfile, Terrain
from aggsim.control import (
    PurePursuitGains,
    StanleyGains,
    make_pure_pursuit,
    make_stanley,
)
from aggsim.geometry import ABLine
from aggsim.geometry.field import FieldPlan
from aggsim.model import State, from_tractor, implement_from_catalog
from aggsim.sim import SimConfig, simulate

from .machine_geometry import machine_geometry
from .terrain import TerrainError, slope_profile

LINE = ABLine((0.0, 0.0), (1.0, 0.0))
MAX_POINTS = 600
BASE_DT = 0.01

# Upper bound on a field run. The simulation stops itself at the far headland
# of the last pass, so this only has to be generous enough not to truncate the
# work; over-estimating costs nothing.
MAX_FIELD_SECONDS = 1800.0


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
            "drawbar_power_w": t.drawbar_power.value,
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
            # So the picker can say which pairings the tractor can actually
            # pull, instead of letting someone run a combination no machine
            # in the catalog could manage.
            "draft_power_w": (
                round(required_draft_power(i), 1)
                if i.draft_power_per_width else None
            ),
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


def _pass_detail(log, plan, index: int) -> dict:
    """What one pass cost, measured against the line that pass was following.

    SCORED OVER THE CROP, NOT THE TURN. A pass's samples begin on the headland,
    where the machine is still coming round and is a full working width off a
    line it has only just been given. Including that stretch makes every pass
    after the first report metres of error -- a statistic about the turn, not
    about the work. Only the samples between the ends of the field are scored;
    the turn is reported separately as the error the pass entered the crop
    with, which is what the settling then has to remove.
    """
    sl = log.pass_slice(index)
    x = log.x[sl]
    err = log.cross_track[sl]
    worked = (x >= 0.0) & (x <= plan.length)
    if not np.any(worked):
        worked = np.ones_like(x, dtype=bool)

    crop = err[worked]
    tail = max(1, len(crop) // 5)
    detail = {
        "index": index,
        "forward": plan.forward(index),
        "offset": round(plan.offset(index), 4),
        "worked_m": round(float(np.ptp(x[worked])), 1),
        "entry_error": round(float(crop[0]), 4),
        "settled_error": round(float(np.mean(crop[-tail:])), 4),
        "rms_cross_track": round(float(np.sqrt(np.mean(crop**2))), 4),
        "peak_cross_track": round(float(np.max(np.abs(crop))), 4),
        "turn_peak": round(float(np.max(np.abs(err))), 4),
    }
    if log.worst_edge is not None:
        edge = log.worst_edge[sl][worked]
        detail.update({
            "entry_edge": round(float(edge[0]), 4),
            "rms_edge": round(float(np.sqrt(np.mean(edge**2))), 4),
            "peak_edge": round(float(np.max(np.abs(edge))), 4),
        })
    return detail


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

    plan = None
    duration = req.duration
    if req.passes > 1:
        if geometry is None:
            raise SimulationError(
                "Working parallel passes needs an implement: the spacing between "
                "passes is the implement's working width."
            )
        plan = FieldPlan(
            working_width=geometry.working_width,
            passes=req.passes,
            length=req.pass_length,
            headland=req.headland,
        )
        # Enough time to finish the field, not the value the user sent. Each
        # pass is its length plus both headlands, plus room for the turn onto
        # the next one; the run stops itself when the work is done.
        turn = 3.5 * geometry.working_width
        distance = (req.passes * (plan.length + 2 * plan.headland)
                    + (req.passes - 1) * turn)
        duration = min(1.25 * distance / req.speed, MAX_FIELD_SECONDS)

    # Bound CPU by total integration steps, coarsening the timestep rather
    # than refusing the request outright.
    dt = BASE_DT
    steps = int(duration / dt)
    if steps > max_steps:
        dt = duration / max_steps
        steps = max_steps

    profile = None
    profile_summary = None
    if req.field is not None:
        # Sample far enough to cover the whole run, so the machine never drives
        # off the end of the measured ground.
        travel = req.speed * duration
        try:
            sampled = slope_profile(req.field.lat, req.field.lon,
                                    req.field.heading_deg, travel)
        except TerrainError as exc:
            raise SimulationError(f"Could not read that field: {exc}") from None
        profile = SlopeProfile(
            positions=np.asarray(sampled["positions_m"], dtype=float),
            side_slope=np.asarray(sampled["side_slope_rad"], dtype=float),
            source=f"USGS 3DEP at {req.field.lat:.4f}, {req.field.lon:.4f}",
        )
        profile_summary = sampled

    terrain = Terrain(
        slope_angle=math.radians(req.slope_deg),
        slope_sign=float(req.slope_sign),
        slip=req.slip,
        profile=profile,
        implement_drift_ratio=Param(
            value=req.implement_drift_ratio,
            unit="dimensionless",
            assumed=True,
            rationale="selected in the web interface",
        ),
    )

    def make_controller(line):
        if req.controller == "pure_pursuit":
            return make_pure_pursuit(
                line, req.speed,
                PurePursuitGains(k=req.lookahead_gain, l_min=req.lookahead_min),
                params,
            )
        return make_stanley(
            line, req.speed, StanleyGains(k_e=req.stanley_gain), params
        )

    if plan is None:
        first_line = LINE
        start = State(0.0, req.initial_offset, 0.0)
    else:
        first_line = plan.line(0)
        x0, y0, h0 = plan.entry(0)
        start = State(x0, y0 + req.initial_offset, h0)

    config = SimConfig(speed=req.speed, dt=dt, duration=duration)
    log = simulate(
        start, first_line, make_controller(first_line), params, config,
        steering=load_steering() if req.actuator else None,
        terrain=terrain, geometry=geometry,
        plan=plan, make_controller=make_controller if plan is not None else None,
    )

    step = max(1, len(log.t) // MAX_POINTS)
    series = {
        "t": _downsample(log.t, step),
        "x": _downsample(log.x, step),
        "y": _downsample(log.y, step),
        "cross_track": _downsample(log.cross_track, step),
        "delta_cmd": _downsample(np.degrees(log.delta_cmd), step),
        "delta": _downsample(np.degrees(log.delta), step),
        "theta": _downsample(log.theta, step),
        "delta_rad": _downsample(log.delta, step),
    }

    summary = {
        "jackknifed": bool(log.jackknifed),
        "jackknife_time": log.jackknife_time,
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
        series["theta_implement"] = _downsample(log.theta_implement, step)
        summary.update({
            "final_worst_edge": round(float(log.worst_edge[-1]), 5),
            "rms_worst_edge": round(log.rms_worst_edge(), 5),
            "peak_worst_edge": round(float(np.max(np.abs(log.worst_edge))), 5),
            "working_width": geometry.working_width,
        })

        if plan is None:
            # One pass compared with a copy of itself: what happens when the
            # neighbour is worked under identical conditions.
            coverage = coverage_between_passes(log, log, geometry.working_width)
            summary.update({
                "rms_skip_m": round(coverage.rms_skip, 5),
                "rms_skip_percent": round(coverage.rms_skip_percent, 4),
                "worst_skip_m": round(coverage.worst_skip, 5),
                "coverage_basis": "identical-passes assumption",
            })
        else:
            # Neighbours that were actually driven, in opposite directions,
            # each entering from its own headland turn. No assumption needed.
            boundaries = [coverage_across_passes(log, plan, i).summary()
                          for i in range(log.passes_worked - 1)]
            if boundaries:
                rms = float(np.sqrt(np.mean(
                    [b["rms_skip_cm"] ** 2 for b in boundaries]))) / 100.0
                summary.update({
                    "rms_skip_m": round(rms, 5),
                    "rms_skip_percent": round(
                        100.0 * rms / geometry.working_width, 4),
                    "worst_skip_m": round(
                        max(b["worst_gap_cm"] for b in boundaries) / 100.0, 5),
                    "gap_area_m2_per_100m": round(
                        float(np.mean([b["gap_area_m2_per_100m"]
                                       for b in boundaries])), 3),
                    "coverage_basis": "measured between passes actually driven",
                })
            summary["boundaries"] = boundaries

    passes_payload = None
    if plan is not None:
        series["pass_index"] = [int(v) for v in log.pass_index[::step]]
        passes_payload = {
            "plan": plan.summary(),
            "worked": log.passes_worked,
            "complete": log.passes_worked == plan.passes,
            "lines": [{"index": i,
                       "offset": round(plan.offset(i), 4),
                       "forward": plan.forward(i)}
                      for i in range(plan.passes)],
            "detail": [_pass_detail(log, plan, i)
                       for i in range(log.passes_worked)],
        }

    pairing = None
    if implement is not None:
        try:
            check = check_pairing(tractor, implement)
            pairing = {
                "feasible": check.ok,
                "required_kw": round(check.required_power / 1000, 1),
                "available_kw": round(check.available_power / 1000, 1),
                "utilisation": round(check.utilisation, 3),
                "reasons": check.reasons,
            }
        except ValueError:
            pairing = None

    return {
        "passes": passes_payload,
        "tractor": {"id": tractor.id, "name": tractor.name,
                    "wheelbase": tractor.wheelbase.value},
        "pairing": pairing,
        "implement": None if implement is None else {
            "id": implement.id, "name": implement.name,
            "type": implement.type, "width": implement.working_width.value,
        },
        "series": series,
        "summary": summary,
        "field": profile_summary,
        "scene": {
            "plan": None if plan is None else {
                "passes": plan.passes,
                "working_width": round(plan.working_width, 4),
                "length": round(plan.length, 2),
                "headland": round(plan.headland, 2),
            },
            "machine": machine_geometry(tractor, implement, geometry),
            "slope_deg": req.slope_deg,
            "slope_sign": req.slope_sign,
            "speed": req.speed,
            "slip": req.slip,
        },
    }
