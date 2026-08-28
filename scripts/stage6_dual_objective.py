"""Stage 6 outputs: the dual-objective tuning comparison.

    python scripts/stage6_dual_objective.py

The central experiment. For each configuration, find the lookahead gain that
minimises RMS tractor cross-track error and, separately, the one that
minimises RMS worst-case implement edge error -- then report how far apart
they land and how that scales with implement width, hitch distance and slope.

If the two optima coincide across the configuration space, that is reported
as a negative result. No finding is forced.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from aggsim.analysis.coverage import coverage_between_passes
from aggsim.analysis.tuning import scan_gains
from aggsim.catalog import load_catalog
from aggsim.config import load_steering
from aggsim.config.terrain import Terrain
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry import ABLine
from aggsim.model import State, from_tractor, implement_from_catalog
from aggsim.sim import SimConfig, simulate

LINE = ABLine((0.0, 0.0), (1.0, 0.0))
OUT_DIR = Path("results")
GAINS = np.arange(0.05, 1.61, 0.05)
# Line-acquisition error at the end of a headland turn. NOT arbitrary: below
# about 2 m the correction is gentle enough that both objectives fall
# monotonically to the shortest lookahead searched, so neither has an interior
# optimum and the comparison is vacuous. 3 m is a realistic re-acquisition
# error and puts both minima inside the range.
E0 = 3.0
# dt and duration verified not to move either optimum: 0.005/0.01/0.02 and
# 60/90 s all return identical k_tractor and k_implement.
DURATION = 60.0
DT = 0.02
CORRECTION_SIZES = (2.0, 3.0, 5.0)


def runner(params, geometry, speed, terrain, steering, e0=E0):
    def run(k):
        cfg = SimConfig(speed=speed, dt=DT, duration=DURATION)
        ctrl = make_pure_pursuit(LINE, speed, PurePursuitGains(k=k, l_min=3.0), params)
        return simulate(State(0.0, e0, 0.0), LINE, ctrl, params, cfg,
                        steering=steering, terrain=terrain, geometry=geometry)
    return run


def main() -> None:
    catalog = load_catalog()
    steering = load_steering()
    params = from_tractor(catalog.tractor("jd_6145r"))

    trailed = [i for i in catalog.implements.values() if i.type == "trailed"]
    trailed.sort(key=lambda i: i.working_width.value)

    print("Stage 6: dual-objective tuning comparison")
    print(f"  tractor John Deere 6145R, actuator lag on, {E0} m acquisition offset")
    print(f"  gains {GAINS[0]:.2f}-{GAINS[-1]:.2f} step {GAINS[1]-GAINS[0]:.2f}, "
          "parabolic sub-grid refinement")

    records = []

    # --- sweep 1: implement width x slope --------------------------------
    print("\n  SWEEP 1: implement x slope (v = 3 m/s, tilled slip 0.12)")
    print(f'    {"implement":34s} {"w":>6} {"b":>5} {"slope":>6} '
          f'{"k_tract":>8} {"k_impl":>8} {"gap":>7} {"penalty":>8}')
    for imp in trailed:
        g = implement_from_catalog(imp)
        for deg in (0.0, 5.0, 10.0):
            terrain = Terrain(slope_angle=np.radians(deg), slip=0.12)
            res = scan_gains(runner(params, g, 3.0, terrain, steering),
                             GAINS, g.working_width)
            penalty = res.edge_penalty_at_tractor_optimum()
            rec = dict(implement=imp.id, model=imp.model,
                       width=g.working_width, hitch=g.hitch_distance,
                       b=g.implement_wheelbase, speed=3.0, slope=deg, slip=0.12,
                       k_tractor=res.k_tractor, k_implement=res.k_implement,
                       k_skip=res.k_skip, divergence=res.divergence,
                       penalty=penalty, interior=res.interior,
                       whip=res.tractor_improves_while_implement_worsens())
            records.append(rec)
            flag = "" if res.interior else "  <- endpoint, not an optimum"
            print(f'    {imp.model[:34]:34s} {g.working_width:6.2f} '
                  f'{g.implement_wheelbase:5.2f} {deg:6.1f} '
                  f'{res.k_tractor:8.3f} {res.k_implement:8.3f} '
                  f'{res.divergence:+7.3f} {penalty * 100:7.2f}%{flag}')
            sys.stdout.flush()

    # --- sweep 2: speed ---------------------------------------------------
    print("\n  SWEEP 2: speed (3 implements, 10 deg slope, tilled)")
    speed_recs = []
    for imp in (trailed[0], trailed[len(trailed) // 2], trailed[-1]):
        g = implement_from_catalog(imp)
        for speed in (2.0, 3.0, 4.0, 5.0):
            terrain = Terrain(slope_angle=np.radians(10.0), slip=0.12)
            res = scan_gains(runner(params, g, speed, terrain, steering),
                             GAINS, g.working_width)
            speed_recs.append(dict(model=imp.model, width=g.working_width,
                                   speed=speed, k_tractor=res.k_tractor,
                                   k_implement=res.k_implement,
                                   divergence=res.divergence))
            print(f'    {imp.model[:30]:30s} v={speed:4.1f}  '
                  f'k_t={res.k_tractor:.3f} k_i={res.k_implement:.3f} '
                  f'gap={res.divergence:+.3f}')

    # --- sweep 3: slip ----------------------------------------------------
    print("\n  SWEEP 3: soil slip (widest implement, 10 deg slope, v = 3 m/s)")
    slip_recs = []
    g_wide = implement_from_catalog(trailed[-1])
    for name, slip in (("concrete", 0.06), ("firm", 0.095),
                       ("tilled", 0.12), ("sandy", 0.18)):
        terrain = Terrain(slope_angle=np.radians(10.0), slip=slip)
        res = scan_gains(runner(params, g_wide, 3.0, terrain, steering),
                         GAINS, g_wide.working_width)
        slip_recs.append(dict(soil=name, slip=slip, k_tractor=res.k_tractor,
                              k_implement=res.k_implement, divergence=res.divergence))
        print(f'    {name:10s} s={slip:.3f}  k_t={res.k_tractor:.3f} '
              f'k_i={res.k_implement:.3f} gap={res.divergence:+.3f}')

    # --- sweep 4: correction magnitude -----------------------------------
    print("\n  SWEEP 4: correction magnitude (10 deg slope, tilled, v = 3 m/s)")
    corr_recs = []
    for imp in (trailed[0], trailed[3], trailed[-1]):
        g = implement_from_catalog(imp)
        for e0 in CORRECTION_SIZES:
            terrain = Terrain(slope_angle=np.radians(10.0), slip=0.12)
            res = scan_gains(runner(params, g, 3.0, terrain, steering, e0=e0),
                             GAINS, g.working_width)
            corr_recs.append(dict(model=imp.model, width=g.working_width, e0=e0,
                                  k_tractor=res.k_tractor,
                                  k_implement=res.k_implement,
                                  divergence=res.divergence,
                                  interior=res.interior))
            print(f'    {imp.model[:30]:30s} w={g.working_width:5.2f} e0={e0:.1f}  '
                  f'k_t={res.k_tractor:.3f} k_i={res.k_implement:.3f} '
                  f'gap={res.divergence:+.4f}')
            sys.stdout.flush()

    # --- detail curve for one representative configuration ---------------
    g_mid = implement_from_catalog(trailed[len(trailed) // 2])
    terrain = Terrain(slope_angle=np.radians(10.0), slip=0.12)
    detail = scan_gains(runner(params, g_mid, 3.0, terrain, steering),
                        GAINS, g_mid.working_width)

    # --- agronomic units --------------------------------------------------
    print("\n  AGRONOMIC UNITS: skip and overlap at each optimum")
    print(f'    {"implement":34s} {"w":>6} {"skip@k_t":>10} {"skip@k_i":>10} {"% width":>9}')
    agro = []
    for imp in trailed:
        g = implement_from_catalog(imp)
        terr = Terrain(slope_angle=np.radians(10.0), slip=0.12)
        run = runner(params, g, 3.0, terr, steering)
        rec = next(r for r in records if r["implement"] == imp.id and r["slope"] == 10.0)
        cov_t = coverage_between_passes(run(rec["k_tractor"]), run(rec["k_tractor"]),
                                        g.working_width)
        cov_i = coverage_between_passes(run(rec["k_implement"]), run(rec["k_implement"]),
                                        g.working_width)
        agro.append(dict(model=imp.model, width=g.working_width,
                         skip_t=cov_t.rms_skip, skip_i=cov_i.rms_skip,
                         pct=cov_t.rms_skip_percent))
        print(f'    {imp.model[:34]:34s} {g.working_width:6.2f} '
              f'{cov_t.rms_skip * 100:9.2f}cm {cov_i.rms_skip * 100:9.2f}cm '
              f'{cov_t.rms_skip_percent:8.3f}%')

    # --- verdict ----------------------------------------------------------
    usable = [r for r in records if r["interior"]]
    gaps = np.array([r["divergence"] for r in usable])
    penalties = np.array([r["penalty"] for r in usable])
    whips = [r for r in usable if r["whip"]]
    print("\n  VERDICT")
    print(f"    configurations: {len(records)} run, {len(usable)} with both "
          "minima interior to the searched range")
    if not len(gaps):
        print("    no configuration produced two genuine optima; "
              "nothing can be concluded")
        gaps = np.array([0.0]); penalties = np.array([0.0])
    print(f"    divergence k_implement - k_tractor: mean {gaps.mean():+.4f}, "
          f"range {gaps.min():+.3f} to {gaps.max():+.3f}")
    print(f"    grid step is {GAINS[1] - GAINS[0]:.2f}; "
          f"{np.sum(np.abs(gaps) > (GAINS[1] - GAINS[0]))} of {len(gaps)} "
          "configurations diverge by more than one grid step")
    print(f"    cost of tuning for the tractor: mean {penalties.mean() * 100:.2f}%, "
          f"max {penalties.max() * 100:.2f}% extra RMS edge error")
    print(f"    configurations where tightening the tractor worsens the "
          f"implement: {len(whips)} of {len(records)}")

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "stage6_results.json").write_text(json.dumps(
        dict(records=records, speed=speed_recs, slip=slip_recs,
             correction=corr_recs, agronomic=agro),
        indent=2, default=float))

    # --- figure -----------------------------------------------------------
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9), constrained_layout=True)

    ax = axes[0, 0]
    ax.plot(detail.gains, detail.rms_tractor / detail.rms_tractor.min(), lw=1.8,
            label="RMS tractor cross-track")
    ax.plot(detail.gains, detail.rms_edge / detail.rms_edge.min(), lw=1.8,
            label="RMS worst implement edge")
    ax.plot(detail.gains, detail.rms_skip / detail.rms_skip.min(), lw=1.4, ls=":",
            label="RMS skip between passes")
    ax.axvline(detail.k_tractor, color="C0", ls="--", lw=1.2)
    ax.axvline(detail.k_implement, color="C1", ls="--", lw=1.2)
    ax.set_yscale("log")
    ax.set(xlabel="lookahead gain k (s)",
           ylabel="RMS, normalised to own minimum (log)", ylim=(0.9, 60),
           title=f"(a) The two objective curves, {g_mid.working_width:.1f} m implement\n"
                 f"k_tractor = {detail.k_tractor:.3f}, k_implement = {detail.k_implement:.3f}")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[0, 1]
    for deg, marker in ((0.0, "o"), (5.0, "s"), (10.0, "^")):
        sub = [r for r in records if r["slope"] == deg and r["interior"]]
        ax.plot([r["width"] for r in sub], [r["divergence"] for r in sub],
                marker + "-", lw=1.5, label=f"slope {deg:.0f} deg")
    ax.axhline(0.0, color="k", lw=1.0)
    ax.axhspan(-(GAINS[1] - GAINS[0]), GAINS[1] - GAINS[0], color="grey", alpha=0.15,
               label="+/- one grid step")
    ax.set(xlabel="implement working width (m)",
           ylabel="k_implement - k_tractor (s)",
           title="(b) Divergence vs width and slope")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[1, 0]
    ax.plot([r["width"] for r in usable], [r["penalty"] * 100 for r in usable],
            "o", alpha=0.75)
    ax.set(xlabel="implement working width (m)",
           ylabel="extra RMS edge error at k_tractor (%)",
           title="(c) Cost of optimising the tractor objective")
    ax.grid(alpha=0.3)

    ax = axes[1, 1]
    ax.plot([a["width"] for a in agro], [a["skip_t"] * 100 for a in agro],
            "o-", lw=1.8, label="skip at k_tractor")
    ax.plot([a["width"] for a in agro], [a["skip_i"] * 100 for a in agro],
            "s--", lw=1.8, label="skip at k_implement")
    ax.set(xlabel="implement working width (m)", ylabel="RMS skip between passes (cm)",
           title="(d) Agronomic units: uncovered ground between passes\n"
                 "(10 deg slope, tilled soil)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    out = OUT_DIR / "stage6_dual_objective.png"
    fig.savefig(out, dpi=140)
    print(f"\n  wrote {out} and stage6_results.json")


if __name__ == "__main__":
    main()
