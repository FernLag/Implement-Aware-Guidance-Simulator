"""Fixed-step simulation loop.

The loop knows nothing about which controller it drives: it calls a
`State -> delta` function. That keeps the controller boundary clean enough
for Stage 5 to drop Stanley in unchanged, and for Stage 7 to move the same
controller into a ROS 2 node.

Actuator dynamics are toggleable. `steering=None` gives the ideal actuator of
Stage 1, where the wheels adopt the commanded angle instantly; passing
`SteeringParams` engages the Stage 2 lag and rate limit. Keeping the ideal
path available is what lets Stage 2 attribute a change in behaviour to the
actuator rather than to a coincidental change elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..config.steering import SteeringParams
from ..geometry.abline import ABLine
from ..model.state import State
from ..model.vehicle import VehicleParams, rk4_step, rk4_step_augmented


@dataclass(frozen=True)
class SimConfig:
    speed: float  # m/s, constant in Stages 1-2
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
    delta: np.ndarray  # actual steering angle at the wheels
    delta_cmd: np.ndarray  # controller output
    cross_track: np.ndarray

    def rms_cross_track(self, settle_time: float = 0.0) -> float:
        mask = self.t >= settle_time
        return float(np.sqrt(np.mean(self.cross_track[mask] ** 2)))

    def final_cross_track(self) -> float:
        return float(self.cross_track[-1])

    def is_settled(self, tol: float = 0.02, tail_fraction: float = 0.25) -> bool:
        """True if |error| stays under `tol` over the final tail of the run."""
        cut = self.t[-1] * (1.0 - tail_fraction)
        return bool(np.all(np.abs(self.cross_track[self.t >= cut]) < tol))


def simulate(
    initial_state: State,
    line: ABLine,
    controller: Callable[[State], float],
    params: VehicleParams,
    config: SimConfig,
    steering: SteeringParams | None = None,
    initial_delta: float = 0.0,
) -> SimLog:
    """Integrate the vehicle under a controller, logging error each step."""
    n = config.n_steps
    t = np.zeros(n + 1)
    xs = np.zeros(n + 1)
    ys = np.zeros(n + 1)
    thetas = np.zeros(n + 1)
    deltas = np.zeros(n + 1)
    cmds = np.zeros(n + 1)
    errors = np.zeros(n + 1)

    vec = np.append(initial_state.as_array(), initial_delta)

    tau = steering.tau.value if steering else None
    rate_limit = steering.rate_limit.value if steering else None

    for i in range(n + 1):
        state = State.from_array(vec[:3])
        delta_cmd = controller(state)

        # With an ideal actuator the wheels are always at the commanded angle.
        if steering is None:
            vec[3] = delta_cmd

        t[i] = i * config.dt
        xs[i] = state.x
        ys[i] = state.y
        thetas[i] = state.theta
        deltas[i] = vec[3]
        cmds[i] = delta_cmd
        errors[i] = line.cross_track(state.x, state.y)

        if i < n:
            if steering is None:
                vec[:3] = rk4_step(
                    vec[:3], config.speed, delta_cmd, params.wheelbase, config.dt
                )
            else:
                vec = rk4_step_augmented(
                    vec, config.speed, delta_cmd, params.wheelbase,
                    tau, rate_limit, config.dt,
                )
                vec[3] = float(
                    np.clip(vec[3], -params.max_steer_angle, params.max_steer_angle)
                )

    return SimLog(
        t=t, x=xs, y=ys, theta=thetas,
        delta=deltas, delta_cmd=cmds, cross_track=errors,
    )
