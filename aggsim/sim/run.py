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
import math
from typing import Callable

import numpy as np

from ..config.steering import SteeringParams
from ..config.terrain import Terrain
from ..geometry.abline import ABLine, wrap_angle
from ..model.state import State
from ..model.implement import ImplementGeometry, edge_errors, implement_position
from ..model.vehicle import VehicleParams, rk4_step_plant


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
    cross_track: np.ndarray  # tractor rear axle, signed, + left of line
    # Stage 4 signals. None when the run carries no implement.
    theta_implement: np.ndarray | None = None
    implement_cross_track: np.ndarray | None = None  # implement centreline
    edge_left: np.ndarray | None = None  # left edge placement error
    edge_right: np.ndarray | None = None  # right edge placement error
    # True when the hitch reached its mechanical stop at any point. Past that
    # the one-trailer kinematics describe a machine folded into itself, so the
    # run is reported as invalid rather than presented as a result.
    jackknifed: bool = False
    jackknife_time: float | None = None

    @property
    def worst_edge(self) -> np.ndarray:
        """Signed larger-magnitude edge error at each step."""
        if self.edge_left is None:
            raise ValueError("run carried no implement")
        pick = np.abs(self.edge_left) >= np.abs(self.edge_right)
        return np.where(pick, self.edge_left, self.edge_right)

    def rms_worst_edge(self, settle_time: float = 0.0) -> float:
        mask = self.t >= settle_time
        return float(np.sqrt(np.mean(self.worst_edge[mask] ** 2)))

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
    terrain: Terrain | None = None,
    geometry: ImplementGeometry | None = None,
) -> SimLog:
    """Integrate the vehicle under a controller, logging error each step."""
    n = config.n_steps
    jackknifed = False
    jackknife_time = None
    t = np.zeros(n + 1)
    xs = np.zeros(n + 1)
    ys = np.zeros(n + 1)
    thetas = np.zeros(n + 1)
    deltas = np.zeros(n + 1)
    cmds = np.zeros(n + 1)
    errors = np.zeros(n + 1)
    theta_i = np.zeros(n + 1)
    imp_err = np.zeros(n + 1)
    edge_l = np.zeros(n + 1)
    edge_r = np.zeros(n + 1)

    # (x, y, theta, delta, theta_i). The implement starts aligned with the
    # tractor, which is the steady state on flat ground with zero steering.
    vec = np.array(
        [initial_state.x, initial_state.y, initial_state.theta,
         initial_delta, initial_state.theta]
    )

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

        if geometry is not None:
            theta_i[i] = vec[4]
            centre = implement_position(state.x, state.y, state.theta, vec[4], geometry)
            imp_err[i] = line.cross_track(centre[0], centre[1])
            edge_l[i], edge_r[i] = edge_errors(
                line, state.x, state.y, state.theta, vec[4], geometry
            )

        if i < n:
            vec = rk4_step_plant(
                vec, config.speed, delta_cmd, params.wheelbase,
                tau, rate_limit, config.dt, terrain, geometry,
            )
            if steering is not None:
                vec[3] = float(
                    np.clip(vec[3], -params.max_steer_angle, params.max_steer_angle)
                )
            if geometry is not None and not geometry.is_rigid:
                # Hold the hitch at its stop rather than letting the implement
                # rotate freely. Before this the model would happily wind the
                # hitch angle past a full turn, which a drawbar cannot do.
                limit = geometry.max_hitch_angle
                relative = wrap_angle(vec[4] - vec[2])
                if abs(relative) > limit:
                    vec[4] = vec[2] + math.copysign(limit, relative)
                    if not jackknifed:
                        jackknifed = True
                        jackknife_time = (i + 1) * config.dt

    return SimLog(
        t=t, x=xs, y=ys, theta=thetas,
        delta=deltas, delta_cmd=cmds, cross_track=errors,
        theta_implement=theta_i if geometry is not None else None,
        implement_cross_track=imp_err if geometry is not None else None,
        edge_left=edge_l if geometry is not None else None,
        edge_right=edge_r if geometry is not None else None,
        jackknifed=jackknifed,
        jackknife_time=jackknife_time,
    )
