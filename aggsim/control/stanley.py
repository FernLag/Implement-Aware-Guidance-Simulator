"""Stanley path tracking (Stage 5).

    delta = psi - arctan(k_e * e_f / (v + k_s))

Front-axle referenced: `e_f` is the cross-track error of the FRONT axle, not
of the state's rear-axle reference point, and `psi` is heading error.

SIGN NOTE. CLAUDE.md writes the law with a plus. That form assumes cross-track
error is positive to the RIGHT of the path. This project fixed the opposite
convention in Stage 1 (positive to the left, so that the implement edge
metric of Stage 4 shares a frame with it), so the cross-track term is
subtracted here. Check: sitting left of the line with the heading aligned
gives psi = 0 and delta < 0, steering right, back towards the line.

The two terms do different jobs. `psi` aligns the vehicle with the path
direction; the arctan term is a proportional pull towards the path whose
authority falls off with speed. `k_s` softens the denominator so the gain
stays finite at standstill.

ARCHITECTURAL RULE: a pure function of state, like pure_pursuit. The
simulation loop takes either behind the same State -> delta signature.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geometry.abline import ABLine, wrap_angle
from ..model.state import State
from ..model.vehicle import VehicleParams


@dataclass(frozen=True)
class StanleyGains:
    """Cross-track gain and the low-speed softening constant."""

    k_e: float
    k_s: float = 1.0

    def __post_init__(self) -> None:
        if self.k_e <= 0:
            raise ValueError("cross-track gain k_e must be positive")
        if self.k_s <= 0:
            raise ValueError("k_s must be positive to keep the gain finite at v = 0")


def front_axle_position(state: State, params: VehicleParams) -> tuple[float, float]:
    """The Stanley reference point, one wheelbase ahead of the state."""
    return (
        state.x + params.wheelbase * np.cos(state.theta),
        state.y + params.wheelbase * np.sin(state.theta),
    )


def stanley(
    state: State,
    line: ABLine,
    v: float,
    gains: StanleyGains,
    params: VehicleParams,
) -> float:
    """Steering angle command, radians, positive = left."""
    fx, fy = front_axle_position(state, params)
    e_f = line.cross_track(fx, fy)
    psi = wrap_angle(line.heading - state.theta)

    delta = psi - np.arctan2(gains.k_e * e_f, abs(v) + gains.k_s)
    return float(np.clip(delta, -params.max_steer_angle, params.max_steer_angle))


def make_stanley(line: ABLine, v: float, gains: StanleyGains, params: VehicleParams):
    """Bind configuration, leaving a State -> delta function for the loop."""

    def controller(state: State) -> float:
        return stanley(state, line, v, gains, params)

    return controller
