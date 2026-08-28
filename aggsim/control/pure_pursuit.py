"""Pure pursuit path tracking.

ARCHITECTURAL RULE (CLAUDE.md, applies from Stage 1): a controller is a pure
function -- state in, steering command out. No plotting, no I/O, no coupling
to the simulation loop. Stage 7 wraps this exact function in a ROS 2 node, so
anything that reaches outside these arguments would have to be rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geometry.abline import ABLine, wrap_angle
from ..model.state import State
from ..model.vehicle import VehicleParams


@dataclass(frozen=True)
class PurePursuitGains:
    """Lookahead schedule: L_d = k * v + l_min.

    `k` is the tuning knob Stage 6 sweeps. `l_min` keeps the lookahead finite
    at standstill, where a speed-proportional term alone would collapse to
    zero and make the steering law singular.
    """

    k: float
    l_min: float

    def __post_init__(self) -> None:
        if self.k < 0:
            raise ValueError("lookahead gain k must be non-negative")
        if self.l_min <= 0:
            raise ValueError("l_min must be positive to keep L_d > 0 at v = 0")

    def lookahead(self, v: float) -> float:
        return self.k * abs(v) + self.l_min


def pure_pursuit(
    state: State,
    line: ABLine,
    v: float,
    gains: PurePursuitGains,
    params: VehicleParams,
) -> float:
    """Steering angle command, radians, positive = left.

        delta = arctan(2 L sin(alpha) / L_d)

    `alpha` is the angle between the heading and the bearing to the lookahead
    point. The law is exact for a circular arc through the vehicle's rear axle
    that passes through the lookahead point.
    """
    l_d = gains.lookahead(v)
    goal = line.lookahead_point(state.x, state.y, l_d)

    bearing = np.arctan2(goal[1] - state.y, goal[0] - state.x)
    alpha = wrap_angle(bearing - state.theta)

    delta = np.arctan2(2.0 * params.wheelbase * np.sin(alpha), l_d)
    return float(np.clip(delta, -params.max_steer_angle, params.max_steer_angle))


def make_pure_pursuit(line: ABLine, v: float, gains: PurePursuitGains, params: VehicleParams):
    """Bind the configuration, leaving a State -> delta function for the loop.

    The binding happens here so the simulation loop can stay agnostic about
    which controller it is driving -- Stage 5 adds Stanley behind the same
    signature.
    """

    def controller(state: State) -> float:
        return pure_pursuit(state, line, v, gains, params)

    return controller
