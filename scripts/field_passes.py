"""Field work: parallel passes, headland turns, and coverage between neighbours.

    python scripts/field_passes.py

Stages 1 to 6 drive one endless straight line, which isolates the tracking
behaviour and is the right place to start. Two things only appear once the
machine works a field.

THE TURN. A pass does not begin on its line. It begins wherever the headland
turn left the machine, and the implement arrives later and further out than
the tractor does. Stage 6 stands in for that with an acquisition offset; here
it is the real thing.

THE NEIGHBOUR. Skip and overlap are properties of two passes. Until now the
analysis compared a pass with a copy of itself, which assumes both were worked
identically. With a plan the passes are compared with the neighbours that were
actually driven, in the opposite direction, minutes apart, each entering from
its own turn.

The figure also shows the one result that only a return pass can produce: on a
side slope the settled offset changes sign every pass. The hillside has not
moved; the machine has turned round.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from aggsim.analysis.coverage import coverage_across_passes
from aggsim.catalog import load_catalog
from aggsim.config import load_steering
from aggsim.config.terrain import Terrain
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry.field import FieldPlan
from aggsim.model import State, from_tractor, implement_from_catalog
from aggsim.sim import SimConfig, simulate

TRACTOR_ID = "jd_6145r"
IMPLEMENT_ID = "jd_1775nt_16row30"  # 12.19 m trailed planter
SPEED = 3.0
PASSES = 6
LENGTH = 180.0
SLOPE_DEG = 8.0
SLIP = 0.12

OUT_DIR = Path(__file__).resolve().parent.parent / "results"


def work_field(params, geometry, plan, terrain):
    gains = PurePursuitGains(k=0.5, l_min=3.0)

    def make(line):
        return make_pure_pursuit(line, SPEED, gains, params)

    # Generous: the run stops itself at the far headland of the last pass, so
    # over-estimating the time costs nothing and under-estimating truncates.
    distance = PASSES * (plan.length + 2 * plan.headland + 4 * plan.working_width)
    x0, y0, h0 = plan.entry(0)
    return simulate(
        State(x0, y0, h0), plan.line(0), make(plan.line(0)), params,
        SimConfig(speed=SPEED, dt=0.02, duration=1.3 * distance / SPEED),
        steering=load_steering(), terrain=terrain, geometry=geometry,
        plan=plan, make_controller=make,
    )


def crop_stats(log, plan, index):
    """One pass scored over the crop, with the headland turn left out.

    Including the turn reports how far the machine was from a line it had not
    started following, which is a statistic about the turn and not the work.
    """
    sl = log.pass_slice(index)
    x, err, edge = log.x[sl], log.cross_track[sl], log.worst_edge[sl]
    worked = (x >= 0.0) & (x <= plan.length)
    crop = err[worked]
    tail = max(1, len(crop) // 5)
    return {
        "entry": float(crop[0]),
        "settled": float(np.mean(crop[-tail:])),
        "rms_edge": float(np.sqrt(np.mean(edge[worked] ** 2))),
        "peak_edge": float(np.max(np.abs(edge[worked]))),
        "turn_peak": float(np.max(np.abs(err))),
    }


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    catalog = load_catalog()
    tractor = catalog.tractor(TRACTOR_ID)
    implement = catalog.implement(IMPLEMENT_ID)
    params = from_tractor(tractor)
    geometry = implement_from_catalog(implement)

    plan = FieldPlan(working_width=geometry.working_width, passes=PASSES,
                     length=LENGTH)

    print("Field work: parallel passes with headland turns")
    print(f"  {tractor.name} and {implement.name}")
    print(f"  {PASSES} passes, {LENGTH:.0f} m long, "
          f"{plan.working_width:.2f} m apart "
          f"({plan.summary()['worked_area_ha']:.2f} ha)\n")

    cases = {
        "flat": Terrain(slip=SLIP),
        f"{SLOPE_DEG:.0f} deg side slope": Terrain(
            slope_angle=math.radians(SLOPE_DEG), slope_sign=1.0, slip=SLIP),
    }

    logs, stats, boundaries = {}, {}, {}
    for name, terrain in cases.items():
        log = work_field(params, geometry, plan, terrain)
        logs[name] = log
        stats[name] = [crop_stats(log, plan, i) for i in range(log.passes_worked)]
        boundaries[name] = [coverage_across_passes(log, plan, i)
                            for i in range(log.passes_worked - 1)]

        print(f"  {name.upper()}  ({log.passes_worked} passes worked, "
              f"{log.t[-1]:.0f} s)")
        print("    pass  dir    entered   settled   RMS edge  peak edge   turn peak")
        for i, st in enumerate(stats[name]):
            print(f"    {i + 1:>4}  {'out' if plan.forward(i) else 'back':<5}"
                  f"{st['entry']:+9.3f} {st['settled']:+9.3f} "
                  f"{st['rms_edge']:10.3f} {st['peak_edge']:10.3f} "
                  f"{st['turn_peak']:11.2f}")

        print("    between   mean skip   worst gap   worst overlap   lost m2/100m")
        for cov in boundaries[name]:
            print(f"    {cov.lower + 1} and {cov.upper + 1}  "
                  f"{cov.mean_skip * 100:+10.2f} cm {cov.worst_skip * 100:10.2f} cm "
                  f"{cov.worst_overlap * 100:12.2f} cm {cov.gap_area_per_100m:13.2f}")
        print()

    # ---------------------------------------------------------------- figure
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.0))
    fig.suptitle(
        f"Field work: {PASSES} passes of {implement.name} behind {tractor.name}",
        fontsize=13)

    # (a) the path over the ground, which is the point of the whole feature
    ax = axes[0][0]
    log = logs[f"{SLOPE_DEG:.0f} deg side slope"]
    for i in range(plan.passes):
        y = plan.offset(i)
        ax.plot([0, plan.length], [y, y], color="0.75", lw=1.0, zorder=1)
    ax.plot(log.x, log.y, color="darkolivegreen", lw=1.3, zorder=3,
            label="tractor path")
    ax.plot(log.edge_left_xy[:, 0], log.edge_left_xy[:, 1], color="sienna",
            lw=0.6, alpha=0.7, zorder=2)
    ax.plot(log.edge_right_xy[:, 0], log.edge_right_xy[:, 1], color="sienna",
            lw=0.6, alpha=0.7, zorder=2, label="implement edges")
    ax.axvline(0.0, color="0.4", ls=":", lw=1.0)
    ax.axvline(plan.length, color="0.4", ls=":", lw=1.0)
    ax.set(xlabel="x (m)", ylabel="y (m)",
           title="(a) The worked field. Grey lines are the guidance lines;\n"
                 "the turns happen outside the dotted headlands")
    ax.legend(fontsize=8, loc="lower right")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(alpha=0.3)

    # (b) the sign flip, which only a return pass can show
    ax = axes[0][1]
    for name, marker in (("flat", "s--"), (f"{SLOPE_DEG:.0f} deg side slope", "o-")):
        ax.plot(range(1, len(stats[name]) + 1),
                [st["settled"] for st in stats[name]], marker, lw=1.6, label=name)
    ax.axhline(0.0, color="k", lw=1.0)
    ax.set(xlabel="pass", ylabel="settled cross-track error (m)",
           title="(b) On a side slope the settled offset changes sign every\n"
                 "pass: the hill has not moved, the machine has turned round")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (c) what the turn costs, against what the work costs
    ax = axes[1][0]
    name = f"{SLOPE_DEG:.0f} deg side slope"
    idx = np.arange(1, len(stats[name]) + 1)
    ax.bar(idx - 0.2, [st["turn_peak"] for st in stats[name]], 0.4,
           color="indianred", label="peak error during the turn")
    ax.bar(idx + 0.2, [st["peak_edge"] for st in stats[name]], 0.4,
           color="darkolivegreen", label="peak edge error over the crop")
    ax.set(xlabel="pass", ylabel="error (m)", yscale="log",
           title="(c) The turn is metres wide and the work is centimetres.\n"
                 "Scoring them together describes the turn, not the work")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="y")

    # (d) coverage: measured against the real neighbour
    ax = axes[1][1]
    for name, colour in (("flat", "steelblue"),
                         (f"{SLOPE_DEG:.0f} deg side slope", "crimson")):
        for k, cov in enumerate(boundaries[name]):
            ax.plot(cov.along, cov.skip * 100, color=colour, lw=1.0,
                    alpha=0.8, label=name if k == 0 else None)
    ax.axhline(0.0, color="k", lw=1.0)
    ax.set(xlabel="distance along the field (m)", ylabel="skip (cm)",
           title="(d) Ground between neighbouring passes, measured between the\n"
                 "two passes driven. Positive is uncovered")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = OUT_DIR / "field_passes.png"
    fig.savefig(out, dpi=140)
    print(f"  wrote {out}")

    print("\nASSUMED PARAMETERS IN THIS RUN")
    print(f"  headland = {plan.headland:g} m\n    Room for the turn. Not a "
          "machine specification; chosen so the turn completes clear of the "
          "crop for every implement in the catalog.")
    for name, param in Terrain(slope_angle=0.1).params().items():
        print(f"  {name} = {param.value:g} {param.unit}\n    {param.rationale.strip()}")


if __name__ == "__main__":
    main()
