"""Stage 4 outputs: implement modelling and the second error metric.

    python scripts/stage4_implement.py

The core of the project. Reports three separate time series -- tractor
cross-track error, implement centreline error, worst-case implement edge
error -- so their divergence is directly visible, and isolates each of the
three mechanisms that drives them apart.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from aggsim.catalog import load_catalog
from aggsim.catalog.param import Param
from aggsim.config.terrain import Terrain
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry import ABLine
from aggsim.model import ImplementGeometry, State, from_tractor, implement_from_catalog
from aggsim.sim import SimConfig, simulate

TRACTOR_ID = "jd_6145r"
IMPLEMENT_ID = "jd_1775nt_16row30"  # 12.19 m trailed planter
LINE = ABLine((0.0, 0.0), (1.0, 0.0))
GAINS = PurePursuitGains(k=0.5, l_min=3.0)
SPEED = 3.0
OUT_DIR = Path("results")


def run(params, geometry, *, e0=0.0, terrain=None, duration=150.0):
    cfg = SimConfig(speed=SPEED, dt=0.01, duration=duration)
    ctrl = make_pure_pursuit(LINE, cfg.speed, GAINS, params)
    return simulate(State(0.0, e0, 0.0), LINE, ctrl, params, cfg,
                    terrain=terrain, geometry=geometry)


def ratio(r):
    return Param(value=r, unit="dimensionless", assumed=True, rationale="swept")


def main() -> None:
    catalog = load_catalog()
    tractor = catalog.tractor(TRACTOR_ID)
    implement = catalog.implement(IMPLEMENT_ID)
    params = from_tractor(tractor)
    geometry = implement_from_catalog(implement)

    print("Stage 4: implement modelling and the second error metric")
    print(f"  {tractor.name} + {implement.name}")
    print(f"  width {geometry.working_width:.3f} m, a = {geometry.hitch_distance:.2f} m, "
          f"b = {geometry.implement_wheelbase:.2f} m")

    OUT_DIR.mkdir(exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9), constrained_layout=True)

    # (a) mechanism 1 -- the implement lags during a correction (flat ground)
    ax = axes[0, 0]
    log = run(params, geometry, e0=3.0, duration=60.0)
    ax.plot(log.t, log.cross_track, lw=1.8, label="tractor cross-track")
    ax.plot(log.t, log.implement_cross_track, lw=1.8, label="implement centreline")
    ax.plot(log.t, log.worst_edge, lw=1.8, ls="--", label="worst implement edge")
    ax.axhline(0.0, color="k", lw=0.8, ls=":")
    ax.set(xlabel="time (s)", ylabel="error (m)", xlim=(0, 40),
           title="(a) Mechanism 1: trailed implement lags during a correction\n"
                 "flat ground, 3 m initial offset -- all three return to zero")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    print(f"\n  (a) flat, 3 m offset: peak tractor {np.max(np.abs(log.cross_track)):.3f} m, "
          f"peak worst edge {np.max(np.abs(log.worst_edge)):.3f} m")

    # (b) on a side slope, the two metrics settle to DIFFERENT values
    ax = axes[0, 1]
    slope = Terrain(slope_angle=np.radians(10.0))
    log = run(params, geometry, e0=0.0, terrain=slope)
    ax.plot(log.t, log.cross_track, lw=1.8, label="tractor cross-track")
    ax.plot(log.t, log.implement_cross_track, lw=1.8, label="implement centreline")
    ax.plot(log.t, log.edge_left, lw=1.2, alpha=0.8, label="left edge")
    ax.plot(log.t, log.edge_right, lw=1.2, alpha=0.8, label="right edge")
    ax.plot(log.t, log.worst_edge, lw=2.0, ls="--", color="k", label="worst edge")
    ax.axhline(0.0, color="k", lw=0.8, ls=":")
    ax.set(xlabel="time (s)", ylabel="error (m)", xlim=(0, 60),
           title="(b) 10 deg side slope: the two objectives settle apart")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    print(f"  (b) 10 deg slope steady state: tractor {log.cross_track[-1]:+.4f} m, "
          f"implement centreline {log.implement_cross_track[-1]:+.4f} m, "
          f"worst edge {log.worst_edge[-1]:+.4f} m "
          f"({abs(log.worst_edge[-1] / log.cross_track[-1]):.2f}x the tractor error)")

    # (c) mechanism 3 -- divergence grows with working width
    ax = axes[1, 0]
    print("\n  (c) divergence vs implement width (10 deg slope):")
    widths, tractor_e, edge_e = [], [], []
    for imp in catalog.implements.values():
        if imp.type != "trailed":
            continue
        g = implement_from_catalog(imp)
        lg = run(params, g, terrain=slope)
        widths.append(g.working_width)
        tractor_e.append(abs(lg.cross_track[-1]))
        edge_e.append(abs(lg.worst_edge[-1]))
        print(f"    {imp.model[:38]:38s} w={g.working_width:6.2f} m -> "
              f"tractor {tractor_e[-1]:.4f} m, worst edge {edge_e[-1]:.4f} m")
    order = np.argsort(widths)
    widths = np.array(widths)[order]
    ax.plot(widths, np.array(tractor_e)[order], "o-", lw=1.8, label="tractor cross-track")
    ax.plot(widths, np.array(edge_e)[order], "s-", lw=1.8, label="worst implement edge")
    ax.set(xlabel="implement working width (m)", ylabel="steady-state error (m)",
           title="(c) Mechanism 3: tractor error is flat in width;\n"
                 "edge error is not")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (d) mechanism 2 -- inert at ratio 1.0, real otherwise
    ax = axes[1, 1]
    print("\n  (d) mechanism 2, implement drift ratio r (10 deg slope):")
    ratios = np.array([0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4])
    hitch, worst = [], []
    for r in ratios:
        terrain = Terrain(slope_angle=np.radians(10.0), implement_drift_ratio=ratio(float(r)))
        lg = run(params, geometry, terrain=terrain)
        hitch.append(np.degrees(lg.theta_implement[-1] - lg.theta[-1]))
        worst.append(lg.worst_edge[-1])
        print(f"    r = {r:.1f} -> hitch angle {hitch[-1]:+6.3f} deg, "
              f"worst edge {worst[-1]:+.4f} m")
    ax.plot(ratios, worst, "o-", lw=1.8, color="crimson", label="worst edge error")
    ax.axvline(1.0, color="k", ls="--", lw=1.0,
               label="default r = 1.0 (mechanism inert)")
    ax2 = ax.twinx()
    ax2.plot(ratios, hitch, "s--", lw=1.4, color="steelblue", label="hitch angle")
    ax2.set_ylabel("steady hitch angle (deg)", color="steelblue")
    ax.set(xlabel="implement drift ratio r  [ASSUMED]",
           ylabel="worst edge error (m)",
           title="(d) Mechanism 2 vanishes at r = 1: zero hitch angle\n"
                 "is an exact equilibrium there")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.3)

    out = OUT_DIR / "stage4_implement.png"
    fig.savefig(out, dpi=140)
    print(f"\n  wrote {out}")

    print("\nASSUMED PARAMETERS IN THIS RUN")
    for name, param in Terrain(slope_angle=0.1).params().items():
        print(f"  {name} = {param.value:g} {param.unit}\n    {param.rationale.strip()}")
    for name in ("hitch_distance", "implement_wheelbase"):
        param = getattr(implement, name)
        print(f"  {implement.model} :: {name} = {param.value:g} {param.unit}")


if __name__ == "__main__":
    main()
