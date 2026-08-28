"""Fixed-step simulation loop.

The loop knows nothing about which controller it drives: it calls a
`State -> delta` function. That keeps the controller boundary clean enough
for Stage 5 to drop Stanley in unchanged, and for Stage 7 to move the same
controller into a ROS 2 node.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..geometry.abline import ABLine
from ..model.state import State
from ..model.vehicle import VehicleParams, rk4_step


@dataclass(frozen=True)
class SimConfig:
    speed: float  # m/s, constant in Stage 1
    dt: float  # s
    duration: float  # s

    def __post_init__(self) -> None:
        if self.dt <= 0 or self.duration <= 0:
            raise ValueError("dt and duration must be positive")

    @property
    def n_steps(self) -> int:
        return int(round(self.duration / self.dt))


@dataclass(frozen=True)
class SimLog:
    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    theta: np.ndarray
    delta: np.ndarray
    cross_track: np.ndarray

    def rms_cross_track(self, settle_time: float = 0.0) -> float:
        mask = self.t >= settle_time
        return float(np.sqrt(np.mean(self.cross_track[mask] ** 2)))

    def final_cross_track(self) -> float:
        return float(self.cross_track[-1])


def simulate(
    initial_state: State,
    line: ABLine,
    controller: Callable[[State], float],
    params: VehicleParams,
    config: SimConfig,
) -> SimLog:
    """Integrate the vehicle under a controller, logging error each step."""
    n = config.n_steps
    t = np.zeros(n + 1)
    xs = np.zeros(n + 1)
    ys = np.zeros(n + 1)
    thetas = np.zeros(n + 1)
    deltas = np.zeros(n + 1)
    errors = np.zeros(n + 1)

    state_vec = initial_state.as_array()

    for i in range(n + 1):
        state = State.from_array(state_vec)
        delta = controller(state)

        t[i] = i * config.dt
        xs[i] = state.x
        ys[i] = state.y
        thetas[i] = state.theta
        deltas[i] = delta
        errors[i] = line.cross_track(state.x, state.y)

        if i < n:
            state_vec = rk4_step(
                state_vec, config.speed, delta, params.wheelbase, config.dt
            )

    return SimLog(t=t, x=xs, y=ys, theta=thetas, delta=deltas, cross_track=errors)
