"""Stage 2 outputs: steering actuator lag and the onset of oscillation.

    python scripts/stage2_actuator_dynamics.py

Shows tracking degrading as speed rises with lag present, and identifies the
speed at which oscillation begins for a given lookahead gain k.

Both actuator parameters are assumptions (no manufacturer publishes them), so
the last panel sweeps tau: a stability conclusion that rests on an assumed
number is only worth as much as its sensitivity to that number.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from aggsim.analysis import analyse_oscillation, onset_speed
from aggsim.catalog import load_catalog
from aggsim.config import load_steering
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry import ABLine
from aggsim.model import State, from_tractor
from aggsim.sim import SimConfig, simulate

TRACTOR_ID = "jd_6145r"
LINE = ABLine((0.0, 0.0), (1.0, 0.0))
OUT_DIR = Path("results")

# Field speeds for tillage and seeding sit around 2-4 m/s (7-15 km/h); the
# sweep runs well past that to locate the boundary even when it is unreachable
# in practice.
SPEED_GRID = np.arange(1.0, 25.1, 1.0)


def make_run(params, steering, k, l_min=3.0, duration=300.0, dt=0.01, e0=1.0):
    def run(v):
        cfg = SimConfig(speed=float(v), dt=dt, duration=duration)
        ctrl = make_pure_pursuit(LINE, cfg.speed, PurePursuitGains(k=k, l_min=l_min), params)
        return simulate(State(0.0, e0, 0.0), LINE, ctrl, params, cfg, steering=steering)

    return run


def main() -> None:
    catalog = load_catalog()
    tractor = catalog.tractor(TRACTOR_ID)
    params = from_tractor(tractor)
    steering = load_steering()

    print("Stage 2: steering actuator dynamics")
    print(f"  tractor: {tractor.name}, L = {params.wheelbase:.3f} m")
    print(f"  tau = {steering.tau.value:.2f} s (ASSUMED), "
          f"rate limit = {np.degrees(steering.rate_limit.value):.0f} deg/s (ASSUMED)")

    OUT_DIR.mkdir(exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)

    # (a) command vs actual, showing the lag itself
    ax = axes[0, 0]
    run = make_run(params, steering, k=0.3, duration=25.0, e0=3.0)
    log = run(6.0)
    ax.plot(log.t, np.degrees(log.delta_cmd), lw=1.8, label="commanded")
    ax.plot(log.t, np.degrees(log.delta), lw=1.8, ls="--", label="actual at wheels")
    ax.set(xlabel="time (s)", ylabel="steering angle (deg)", xlim=(0, 15),
           title=f"(a) Lag and rate limit, tau = {steering.tau.value:.2f} s, v = 6 m/s\n"
                 "straight ramps = actuator rate-bound at 25 deg/s")
    ax.legend()
    ax.grid(alpha=0.3)

    # (b) tracking degrading with speed
    ax = axes[0, 1]
    print("\n  tracking vs speed (k = 0.10):")
    for v in (6.0, 9.0, 10.0, 12.0):
        log = make_run(params, steering, k=0.10, duration=300.0)(v)
        m = analyse_oscillation(log)
        ax.plot(log.t, log.cross_track, lw=1.2,
                label=f"v = {v:.0f} m/s  ({'settles' if m.settled else 'sustained'})")
        print(f"    v = {v:5.1f} m/s  {m.classify()}")
    ax.axhline(0.0, color="k", lw=0.8, ls="--")
    ax.set(xlabel="time (s)", ylabel="cross-track error (m)",
           title="(b) Tracking degrades as speed rises (k = 0.10)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (c) damping ratio vs speed, several gains
    ax = axes[1, 0]
    print("\n  damping ratio vs speed:")
    speeds = np.arange(4.0, 20.1, 2.0)
    for k in (0.05, 0.10, 0.20, 0.30, 0.50):
        run = make_run(params, steering, k=k, duration=100.0)
        zetas = [analyse_oscillation(run(v)).damping_ratio for v in speeds]
        ax.plot(speeds, zetas, "o-", ms=4, lw=1.5, label=f"k = {k:.2f} s")
    ax.set(xlabel="speed (m/s)", ylabel="damping ratio (zeta)",
           title="(c) Damping falls with speed (descriptive; not the criterion)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (d) sensitivity of the onset speed to the ASSUMED tau
    ax = axes[1, 1]
    print("\n  onset speed vs assumed tau (k = 0.30):")
    taus = np.array([0.1, 0.2, 0.3, 0.5, 0.8, 1.2])
    onsets, plotted_taus = [], []
    for tau in taus:
        v = onset_speed(make_run(params, steering.replace(tau=float(tau)), k=0.30),
                        SPEED_GRID, tolerance=0.25)
        print(f"    tau = {tau:.2f} s -> " + ("no onset below 25 m/s" if v is None
                                              else f"{v:.2f} m/s ({v * 3.6:.1f} km/h)"))
        if v is not None:
            onsets.append(v)
            plotted_taus.append(tau)
    if onsets:
        ax.plot(plotted_taus, onsets, "o-", lw=1.8, color="crimson")
    ax.axvline(steering.tau.value, color="k", ls="--", lw=1.0,
               label=f"assumed baseline tau = {steering.tau.value:.2f} s")
    ax.axhspan(2.0, 4.0, color="green", alpha=0.12, label="typical field speed")
    ax.set(xlabel="steering time constant tau (s)  [ASSUMED]",
           ylabel="oscillation onset speed (m/s)",
           title="(d) Onset speed vs the assumed tau (k = 0.30)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    out = OUT_DIR / "stage2_actuator_dynamics.png"
    fig.savefig(out, dpi=140)
    print(f"\n  wrote {out}")

    print("\nASSUMED PARAMETERS IN THIS RUN")
    for name, param in steering.params().items():
        print(f"  {name} = {param.value:g} {param.unit}")
        print(f"    {param.rationale.strip()}")


if __name__ == "__main__":
    main()
