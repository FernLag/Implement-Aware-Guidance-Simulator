"""Stage 3 outputs: side slope and wheel slip.

    python scripts/stage3_terrain.py

The headline demonstration is that pure pursuit holds a STEADY-STATE offset on
a side slope -- it never returns to the line. This is the setup for Stage 5,
where Stanley's explicit cross-track term should eliminate it.

The offset has a closed form, e_ss = L_d * v_d / sqrt(v_eff^2 + v_d^2), so
panel (b) plots simulation against theory rather than simulation alone.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from aggsim.catalog import load_catalog
from aggsim.config import load_steering
from aggsim.config.terrain import Terrain, load_soils
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry import ABLine
from aggsim.model import State, from_tractor
from aggsim.sim import SimConfig, simulate

TRACTOR_ID = "jd_6145r"
LINE = ABLine((0.0, 0.0), (1.0, 0.0))
GAINS = PurePursuitGains(k=0.5, l_min=3.0)
SPEED = 3.0
OUT_DIR = Path("results")


def run(params, terrain, *, e0=0.0, duration=200.0, speed=SPEED, steering=None):
    cfg = SimConfig(speed=speed, dt=0.01, duration=duration)
    ctrl = make_pure_pursuit(LINE, cfg.speed, GAINS, params)
    return simulate(State(0.0, e0, 0.0), LINE, ctrl, params, cfg,
                    steering=steering, terrain=terrain)


def predicted(terrain, speed=SPEED):
    v_eff = speed * terrain.speed_factor
    v_d = terrain.lateral_drift
    return GAINS.lookahead(speed) * v_d / np.hypot(v_eff, v_d)


def main() -> None:
    catalog = load_catalog()
    tractor = catalog.tractor(TRACTOR_ID)
    params = from_tractor(tractor)
    soils = load_soils()

    print("Stage 3: terrain effects")
    print(f"  tractor: {tractor.name}, v = {SPEED} m/s, L_d = {GAINS.lookahead(SPEED):.1f} m")

    OUT_DIR.mkdir(exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)

    # (a) the demonstration: a steady offset that never decays
    ax = axes[0, 0]
    print("\n  steady-state offset (slope only):")
    for deg in (0.0, 5.0, 10.0, 15.0):
        terrain = Terrain(slope_angle=np.radians(deg))
        log = run(params, terrain, e0=1.0)
        ax.plot(log.t, log.cross_track, lw=1.6, label=f"slope {deg:.0f} deg")
        print(f"    phi = {deg:4.1f} deg -> e_ss = {log.final_cross_track():.4f} m")
    ax.axhline(0.0, color="k", lw=0.8, ls="--")
    ax.set(xlabel="time (s)", ylabel="cross-track error (m)", xlim=(0, 60),
           title="(a) Pure pursuit holds a steady offset on a side slope\n"
                 "(started 1 m off the line; it never returns to zero)")
    ax.legend()
    ax.grid(alpha=0.3)

    # (b) simulation against the closed form
    ax = axes[0, 1]
    degs = np.arange(0.0, 20.1, 2.5)
    sim = [run(params, Terrain(slope_angle=np.radians(d))).final_cross_track() for d in degs]
    theory = [predicted(Terrain(slope_angle=np.radians(d))) for d in degs]
    ax.plot(degs, theory, "-", lw=2.5, color="0.6", label="closed form")
    ax.plot(degs, sim, "o", ms=6, color="crimson", label="simulation")
    ax.set(xlabel="side slope (deg)", ylabel="steady-state offset (m)",
           title="(b) e_ss = L_d v_d / sqrt(v_eff^2 + v_d^2)\n"
                 "no wheelbase term: offset is identical for all tractors")
    ax.legend()
    ax.grid(alpha=0.3)
    print(f"\n  max |simulation - closed form| = {np.max(np.abs(np.array(sim) - theory)):.2e} m")

    # (c) slip: alone it costs nothing; on a slope it costs authority
    ax = axes[1, 0]
    print("\n  slip effect (10 deg slope):")
    for name in ("concrete", "firm_untilled", "tilled", "sandy"):
        slip = soils[name]
        terrain = Terrain(slope_angle=np.radians(10.0), slip=slip.value)
        log = run(params, terrain)
        tag = "ASSUMED" if slip.assumed else "sourced"
        ax.plot(log.t, log.cross_track, lw=1.6,
                label=f"{name} s={slip.value:.3f} ({tag})")
        print(f"    {name:14s} s={slip.value:.3f}  e_ss = {log.final_cross_track():.4f} m  [{tag}]")
    slip_only = run(params, Terrain(slip=0.18), e0=1.0)
    ax.plot(slip_only.t, slip_only.cross_track, lw=1.6, ls="--", color="k",
            label="slip alone, no slope")
    ax.axhline(0.0, color="k", lw=0.8, ls=":")
    ax.set(xlabel="time (s)", ylabel="cross-track error (m)", xlim=(0, 120),
           title="(c) Slip alone leaves no offset; on a slope it worsens one")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (d) sensitivity to the assumed drift coefficient
    ax = axes[1, 1]
    from aggsim.catalog.param import Param
    print("\n  sensitivity to the assumed drift coefficient (10 deg slope):")
    coeffs = np.array([0.02, 0.05, 0.10, 0.20, 0.40])
    offs = []
    for c in coeffs:
        p = Param(value=float(c), unit="s", assumed=True, rationale="swept")
        terrain = Terrain(slope_angle=np.radians(10.0), drift_coefficient=p)
        offs.append(run(params, terrain).final_cross_track())
        print(f"    c = {c:.2f} s -> e_ss = {offs[-1]:.4f} m")
    ax.plot(coeffs, offs, "o-", lw=1.8, color="darkgreen")
    ax.axvline(0.10, color="k", ls="--", lw=1.0, label="assumed baseline c = 0.10 s")
    ax.set(xlabel="drift coefficient c (s)  [ASSUMED]",
           ylabel="steady-state offset (m)",
           title="(d) The offset magnitude is set by an assumed constant;\n"
                 "its EXISTENCE is not")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    out = OUT_DIR / "stage3_terrain.png"
    fig.savefig(out, dpi=140)
    print(f"\n  wrote {out}")

    print("\nASSUMED PARAMETERS IN THIS RUN")
    c = Terrain(slope_angle=0.1).drift_coefficient
    print(f"  drift_coefficient = {c.value:g} {c.unit}\n    {c.rationale.strip()}")
    print(f"  sandy slip = {soils['sandy'].value:g}\n    {soils['sandy'].rationale.strip()}")


if __name__ == "__main__":
    main()
