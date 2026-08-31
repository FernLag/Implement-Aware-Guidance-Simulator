"""Stage 7: the kinematic model against Gazebo physics.

    python3 scripts/stage7_compare.py --sweep

The finding Stage 7 is for is not "the two agree". It is a validity envelope:
the speed, slope and implement mass within which the kinematic model stays
inside tolerance of a physics simulation, and the point where it stops being
trustworthy.

THIS SCRIPT DOES NOT INVENT A PHYSICS RUN. The kinematic half runs anywhere.
The physics half needs Gazebo, which runs in the Stage 7 container. With no
`gazebo.json` for a case, that case is reported as not yet run and is left out
of the envelope. A validity envelope computed from a physics simulation that
never happened would be the single most damaging thing this project could
publish, because it would look exactly like a real one.

ONE THING THE COMPARISON CAN SETTLE. The kinematic model turns a side slope
into a lateral drift velocity through a drift coefficient that no one
publishes and that Stage 3 flags as assumed. Gazebo does not need it: it tilts
the floor and lets gravity act. So the slope cases are not only a test of the
kinematic model, they are the one measurement in this project that could give
that assumed coefficient a value. That is reported separately, because
calibrating a parameter and validating a model are different claims.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from aggsim.analysis.divergence import (
    EnvelopePoint,
    Trajectory,
    compare,
    validity_envelope,
)
from aggsim.catalog import load_catalog
from aggsim.config import load_steering
from aggsim.config.terrain import Terrain
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry.abline import ABLine
from aggsim.model import State, from_tractor, implement_from_catalog
from aggsim.sim import SimConfig, simulate

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build" / "stage7"
OUT_DIR = REPO / "results"

# The sweep. Speed, slope and implement mass are the three axes the brief names
# as the ones the envelope should be expressed in.
CASES = [
    # name,            speed, slope, implement
    ("flat_2ms",         2.0,  0.0, "jd_1775nt_16row30"),
    ("flat_3ms",         3.0,  0.0, "jd_1775nt_16row30"),
    ("flat_5ms",         5.0,  0.0, "jd_1775nt_16row30"),
    ("flat_7ms",         7.0,  0.0, "jd_1775nt_16row30"),
    ("slope5_3ms",       3.0,  5.0, "jd_1775nt_16row30"),
    ("slope10_3ms",      3.0, 10.0, "jd_1775nt_16row30"),
    ("slope10_5ms",      5.0, 10.0, "jd_1775nt_16row30"),
    ("slope15_3ms",      3.0, 15.0, "jd_1775nt_16row30"),
    ("light_3ms",        3.0,  5.0, "jd_1590_10ft"),
    ("heavy_3ms",        3.0,  5.0, "jd_2230fh_69ft"),
]

OFFSET = 1.0
SECONDS = 60.0
GAIN = PurePursuitGains(k=0.5, l_min=3.0)


def run_kinematic(tractor, implement, speed, slope_deg):
    """The same configuration, in the model Stages 1 to 6 use."""
    params = from_tractor(tractor)
    geometry = implement_from_catalog(implement) if implement else None
    line = ABLine((0.0, 0.0), (1.0, 0.0))
    controller = make_pure_pursuit(line, speed, GAIN, params)
    terrain = Terrain(slope_angle=math.radians(slope_deg), slope_sign=1.0)
    return simulate(
        State(0.0, OFFSET, 0.0), line, controller, params,
        SimConfig(speed=speed, dt=0.01, duration=SECONDS),
        steering=load_steering(), terrain=terrain, geometry=geometry,
    )


def load_physics(name):
    path = BUILD / name / "gazebo.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    records = payload.get("records") or []
    if len(records) < 20:
        return None
    return Trajectory.from_records(records)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--list-cases", action="store_true",
                    help="print the sweep as shell variables, one case per line, "
                         "so the runner and the analysis cannot disagree about "
                         "which cases exist")
    ap.add_argument("--tolerance", type=float, default=0.10,
                    help="metres of lateral disagreement still counted as agreement")
    args = ap.parse_args()

    if args.list_cases:
        for name, speed, slope, implement_id in CASES:
            print(f"{name} {speed} {slope} {implement_id}")
        return 0

    OUT_DIR.mkdir(exist_ok=True)
    catalog = load_catalog()
    tractor = catalog.tractor("jd_6145r")

    print("Stage 7: kinematic model against Gazebo physics")
    print(f"  tractor {tractor.name}, pure pursuit k = {GAIN.k}, "
          f"{OFFSET} m acquisition offset, {SECONDS:.0f} s per case")
    print(f"  tolerance {args.tolerance * 100:.0f} cm of lateral disagreement\n")

    points, missing = [], []
    for name, speed, slope, implement_id in CASES:
        implement = catalog.implement(implement_id)
        physics = load_physics(name)
        if physics is None:
            missing.append(name)
            continue

        log = run_kinematic(tractor, implement, speed, slope)
        div = compare(Trajectory.from_log(log), physics)
        points.append(EnvelopePoint(
            label=name, speed=speed, slope_deg=slope,
            implement_mass=implement.mass.value, divergence=div,
        ))

    if missing:
        print(f"  NOT YET RUN IN GAZEBO ({len(missing)} of {len(CASES)}):")
        for name in missing:
            print(f"    {name}")
        print("\n  Each needs the Stage 7 container:")
        print("    docker build -t aggsim-stage7 -f docker/stage7/Dockerfile .")
        print("    docker run --rm -v \"$PWD/build:/work/build\" \\")
        print("      -e NAME=<case> -e SLOPE=<deg> -e SPEED=<m/s> aggsim-stage7")
        print("\n  No envelope is reported for a case that has not been run. A")
        print("  validity envelope built from a physics run that never happened")
        print("  would look exactly like a real one, which is what makes it the")
        print("  most damaging thing this project could publish.\n")

    if not points:
        print("  Nothing to compare yet, so there is no Stage 7 result.")
        print("  Stages 0 to 6 are unaffected and complete.")
        return 0

    envelope = validity_envelope(points, args.tolerance)
    print(f"  {'case':<14}{'v':>5}{'slope':>7}{'RMS lat':>10}"
          f"{'max lat':>10}{'slip':>8}  verdict")
    for row in envelope["rows"]:
        verdict = "within" if row["within_tolerance"] else (
            f"breaks at {row['breakdown_distance_m']:.0f} m")
        print(f"  {row['label']:<14}{row['speed']:5.1f}{row['slope_deg']:7.1f}"
              f"{row['rms_lateral_m']:10.4f}{row['max_lateral_m']:10.4f}"
              f"{row['speed_ratio']:8.3f}  {verdict}")

    print(f"\n  VALIDITY ENVELOPE at {args.tolerance * 100:.0f} cm")
    print(f"    {envelope['within']} of {envelope['configurations']} "
          "configurations stayed within tolerance")
    for key, label in (("speed_ok", "speed"), ("slope_ok", "slope"),
                       ("mass_ok", "implement mass")):
        span = envelope[key]
        print(f"    {label:<15} " + ("no configuration passed" if span is None
                                     else f"{span[0]:g} to {span[1]:g}"))
    print(f"    worst case: {envelope['worst']} at "
          f"{envelope['worst_max_lateral_m']:.3f} m")

    payload = {"tolerance_m": args.tolerance, "cases_run": len(points),
               "cases_missing": missing, "envelope": envelope}
    (OUT_DIR / "stage7_results.json").write_text(json.dumps(payload, indent=2))
    print(f"\n  wrote {OUT_DIR / 'stage7_results.json'}")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    ax = axes[0]
    for p in points:
        ax.plot(p.divergence.along, p.divergence.lateral * 100, lw=1.3,
                label=p.label)
    ax.axhline(args.tolerance * 100, color="k", ls="--", lw=1.0)
    ax.axhline(-args.tolerance * 100, color="k", ls="--", lw=1.0,
               label=f"{args.tolerance * 100:.0f} cm tolerance")
    ax.set(xlabel="distance along the line (m)",
           ylabel="physics minus kinematic (cm)",
           title="(a) Where the two simulations disagree")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)

    ax = axes[1]
    ok = [p for p in points if p.divergence.within(args.tolerance)]
    bad = [p for p in points if not p.divergence.within(args.tolerance)]
    for group, colour, label in ((ok, "darkolivegreen", "within tolerance"),
                                 (bad, "crimson", "outside")):
        if group:
            ax.scatter([p.speed for p in group], [p.slope_deg for p in group],
                       s=[40 + p.implement_mass / 200 for p in group],
                       c=colour, label=label, alpha=0.85)
    ax.set(xlabel="speed (m/s)", ylabel="side slope (deg)",
           title="(b) The validity envelope\n(marker size is implement mass)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    fig.tight_layout()
    out = OUT_DIR / "stage7_divergence.png"
    fig.savefig(out, dpi=140)
    print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
