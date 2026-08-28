"""Stage 1 outputs: straight-line tracking under pure pursuit.

    python scripts/stage1_straight_line.py

Produces the two Stage 1 figures -- path overlaid on the reference line, and
cross-track error against time -- plus the steering command, which Stage 2
will need as its baseline before actuator lag is added.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from aggsim.catalog import load_catalog
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry import ABLine
from aggsim.model import State, from_tractor
from aggsim.sim import SimConfig, simulate

TRACTOR_ID = "jd_6145r"
INITIAL_OFFSETS = (3.0, 1.0, -2.0)  # m, signed: positive is left of the line
OUT_DIR = Path("results")


def main() -> None:
    catalog = load_catalog()
    tractor = catalog.tractor(TRACTOR_ID)
    params = from_tractor(tractor)

    line = ABLine((0.0, 0.0), (1.0, 0.0))
    gains = PurePursuitGains(k=0.5, l_min=3.0)
    config = SimConfig(speed=3.0, dt=0.01, duration=60.0)

    print(f"Stage 1: straight-line tracking\n  tractor: {tractor.name}")
    print(f"  wheelbase L = {params.wheelbase:.3f} m  ({tractor.wheelbase.describe()})")
    print(f"  speed {config.speed} m/s, dt {config.dt} s, L_d = {gains.k}v + {gains.l_min} m")

    runs = []
    for e0 in INITIAL_OFFSETS:
        controller = make_pure_pursuit(line, config.speed, gains, params)
        log = simulate(State(0.0, e0, 0.0), line, controller, params, config)
        runs.append((e0, log))
        # Overshoot is the largest excursion of OPPOSITE sign to the start,
        # i.e. how far past the line the correction carries the tractor.
        opposite = -np.sign(e0) * log.cross_track
        overshoot = max(float(np.max(opposite)), 0.0)
        settle = log.t[np.abs(log.cross_track) > 0.02]
        settle_t = float(settle[-1]) if settle.size else 0.0
        print(
            f"  e0 = {e0:+.1f} m -> final {log.final_cross_track():+.2e} m, "
            f"overshoot {overshoot:.3f} m, settles (<2 cm) at {settle_t:.1f} s"
        )

    OUT_DIR.mkdir(exist_ok=True)
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), constrained_layout=True)

    ax = axes[0]
    ax.axhline(0.0, color="k", lw=1.2, ls="--", label="AB line")
    for e0, log in runs:
        ax.plot(log.x, log.y, lw=1.6, label=f"start {e0:+.1f} m")
    ax.set(xlabel="east (m)", ylabel="north (m)", title="Path overlay against reference line")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)

    ax = axes[1]
    ax.axhline(0.0, color="k", lw=0.8, ls="--")
    for e0, log in runs:
        ax.plot(log.t, log.cross_track, lw=1.6, label=f"start {e0:+.1f} m")
    ax.set(xlabel="time (s)", ylabel="cross-track error (m)",
           title="Tractor cross-track error (positive = left of line)")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)

    ax = axes[2]
    for e0, log in runs:
        ax.plot(log.t, np.degrees(log.delta), lw=1.6, label=f"start {e0:+.1f} m")
    ax.axhline(np.degrees(params.max_steer_angle), color="r", lw=0.8, ls=":",
               label="steering limit (assumed)")
    ax.axhline(-np.degrees(params.max_steer_angle), color="r", lw=0.8, ls=":")
    ax.set(xlabel="time (s)", ylabel="steering command (deg)",
           title="Commanded steering angle -- Stage 2 baseline, no actuator lag yet")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)

    out = OUT_DIR / "stage1_straight_line.png"
    fig.savefig(out, dpi=140)
    print(f"\n  wrote {out}")

    # Assumptions are printed, never silently applied.
    print()
    for name, field, param in catalog.assumed_params():
        if name == tractor.name and field in ("wheelbase", "max_steer_angle"):
            print(f"ASSUMED  {name} :: {field} = {param.value:g} {param.unit}")
            print(f"         {param.rationale.strip()}")


if __name__ == "__main__":
    main()
