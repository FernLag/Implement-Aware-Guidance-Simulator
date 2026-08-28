"""Stage 5 outputs: Stanley against pure pursuit, on BOTH error metrics.

    python scripts/stage5_stanley_comparison.py

Runs both controllers under identical conditions, particularly on side
slopes, and scores each against both objectives -- tractor cross-track error
and worst-case implement edge error.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from aggsim.catalog import load_catalog
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

TRACTOR_ID = "jd_6145r"
IMPLEMENT_ID = "jd_1775nt_16row30"
LINE = ABLine((0.0, 0.0), (1.0, 0.0))
SPEED = 3.0
SLOPE_DEG = 10.0
OUT_DIR = Path("results")


def main() -> None:
    catalog = load_catalog()
    tractor = catalog.tractor(TRACTOR_ID)
    implement = catalog.implement(IMPLEMENT_ID)
    params = from_tractor(tractor)
    geometry = implement_from_catalog(implement)
    slope = Terrain(slope_angle=np.radians(SLOPE_DEG))
    L = params.wheelbase
    v_d = slope.lateral_drift

    def run(controller, terrain, duration=200.0, e0=0.0):
        cfg = SimConfig(speed=SPEED, dt=0.01, duration=duration)
        return simulate(State(0.0, e0, 0.0), LINE, controller, params, cfg,
                        terrain=terrain, geometry=geometry)

    pursuit = make_pure_pursuit(LINE, SPEED, PurePursuitGains(k=0.5, l_min=3.0), params)

    print("Stage 5: Stanley vs pure pursuit, both error metrics")
    print(f"  {tractor.name} + {implement.name} ({geometry.working_width:.2f} m)")
    print(f"  {SLOPE_DEG:.0f} deg side slope, v = {SPEED} m/s")
    floor = L * v_d / np.hypot(SPEED, v_d)
    print(f"  predicted Stanley rear-axle floor = L v_d / sqrt(v^2+v_d^2) = {floor:.4f} m")

    OUT_DIR.mkdir(exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9), constrained_layout=True)

    # (a) time series on the slope
    ax = axes[0, 0]
    pp = run(pursuit, slope)
    ax.plot(pp.t, pp.cross_track, lw=1.8, color="C0", label="pure pursuit: tractor")
    ax.plot(pp.t, pp.worst_edge, lw=1.8, ls="--", color="C0", label="pure pursuit: worst edge")
    st = run(make_stanley(LINE, SPEED, StanleyGains(k_e=20.0), params), slope)
    ax.plot(st.t, st.cross_track, lw=1.8, color="C3", label="Stanley k_e=20: tractor")
    ax.plot(st.t, st.worst_edge, lw=1.8, ls="--", color="C3", label="Stanley k_e=20: worst edge")
    ax.axhline(floor, color="k", lw=1.0, ls=":", label="crab floor L v_d / v")
    ax.axhline(0.0, color="k", lw=0.8)
    ax.set(xlabel="time (s)", ylabel="error (m)", xlim=(0, 60),
           title=f"(a) {SLOPE_DEG:.0f} deg slope: neither controller reaches zero")
    ax.legend(fontsize=7.5)
    ax.grid(alpha=0.3)

    # (b) offsets vs Stanley gain, against the closed forms
    ax = axes[0, 1]
    print("\n  steady-state offsets vs Stanley cross-track gain:")
    print(f'    {"k_e":>6} {"front":>9} {"rear":>9} {"worst edge":>11}')
    k_es = np.array([0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 40.0])
    fronts, rears, edges = [], [], []
    for k_e in k_es:
        log = run(make_stanley(LINE, SPEED, StanleyGains(k_e=float(k_e)), params), slope)
        fronts.append(log.cross_track[-1] + L * np.sin(log.theta[-1]))
        rears.append(log.cross_track[-1])
        edges.append(log.worst_edge[-1])
        print(f"    {k_e:6.1f} {fronts[-1]:9.4f} {rears[-1]:9.4f} {edges[-1]:11.4f}")
    ax.semilogx(k_es, fronts, "o-", label="Stanley front axle (controlled)")
    ax.semilogx(k_es, rears, "s-", label="Stanley rear axle")
    ax.semilogx(k_es, edges, "^-", label="Stanley worst implement edge")
    ax.axhline(pp.cross_track[-1], color="C0", ls="--", lw=1.2, label="pure pursuit: tractor")
    ax.axhline(pp.worst_edge[-1], color="C0", ls=":", lw=1.2, label="pure pursuit: worst edge")
    ax.axhline(floor, color="k", lw=1.0, ls=":")
    ax.set(xlabel="Stanley cross-track gain k_e", ylabel="steady-state error (m)",
           title="(b) Raising k_e zeroes the FRONT axle only;\n"
                 "the rear axle floors at the crab term")
    ax.legend(fontsize=7.5)
    ax.grid(alpha=0.3, which="both")

    # (c) the two objectives disagree about which controller is better
    ax = axes[1, 0]
    print("\n  both controllers against both metrics (steady state):")
    labels, tractor_errs, edge_errs = [], [], []
    configs = [
        ("pure pursuit\nk=0.2", make_pure_pursuit(LINE, SPEED, PurePursuitGains(k=0.2, l_min=3.0), params)),
        ("pure pursuit\nk=0.5", pursuit),
        ("pure pursuit\nk=1.0", make_pure_pursuit(LINE, SPEED, PurePursuitGains(k=1.0, l_min=3.0), params)),
        ("Stanley\nk_e=1", make_stanley(LINE, SPEED, StanleyGains(k_e=1.0), params)),
        ("Stanley\nk_e=5", make_stanley(LINE, SPEED, StanleyGains(k_e=5.0), params)),
        ("Stanley\nk_e=20", make_stanley(LINE, SPEED, StanleyGains(k_e=20.0), params)),
    ]
    for label, ctrl in configs:
        log = run(ctrl, slope)
        labels.append(label)
        tractor_errs.append(abs(log.cross_track[-1]))
        edge_errs.append(abs(log.worst_edge[-1]))
        print(f"    {label.replace(chr(10), ' '):24s} tractor {tractor_errs[-1]:.4f} m, "
              f"worst edge {edge_errs[-1]:.4f} m, ratio {edge_errs[-1]/tractor_errs[-1]:.2f}")
    idx = np.arange(len(labels))
    ax.bar(idx - 0.2, tractor_errs, 0.4, label="tractor cross-track")
    ax.bar(idx + 0.2, edge_errs, 0.4, label="worst implement edge")
    ax.set_xticks(idx)
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set(ylabel="steady-state error (m)",
           title="(c) Both controllers scored on both objectives")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="y")

    # (d) how much of the tractor gain reaches the implement
    ax = axes[1, 1]
    base_t, base_e = tractor_errs[1], edge_errs[1]  # pure pursuit k=0.5 reference
    t_gain = [100 * (1 - x / base_t) for x in tractor_errs]
    e_gain = [100 * (1 - x / base_e) for x in edge_errs]
    ax.plot(t_gain, e_gain, "o-", lw=1.8, color="purple")
    for lbl, a, b in zip(labels, t_gain, e_gain):
        ax.annotate(lbl.replace("\n", " "), (a, b), fontsize=7,
                    textcoords="offset points", xytext=(5, -8))
    lim = [min(t_gain + e_gain) - 5, max(t_gain + e_gain) + 10]
    ax.plot(lim, lim, "k--", lw=1.0, label="parity: gains transfer 1:1")
    ax.set(xlabel="improvement in TRACTOR error vs pure pursuit k=0.5 (%)",
           ylabel="improvement in EDGE error (%)", xlim=lim, ylim=lim,
           title="(d) Points below parity: tuning that flatters the tractor\n"
                 "delivers less to the implement")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    out = OUT_DIR / "stage5_stanley_comparison.png"
    fig.savefig(out, dpi=140)
    print(f"\n  wrote {out}")


if __name__ == "__main__":
    main()
