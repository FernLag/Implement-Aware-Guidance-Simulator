"""Kinematic bicycle model and its integrator.

    x_dot     = v cos(theta)
    y_dot     = v sin(theta)
    theta_dot = (v / L) tan(delta)

Written by hand rather than taken from a library so its behaviour is fully
understood and defensible.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VehicleParams:
    """Geometry the vehicle model and controllers need.

    Deliberately decoupled from the catalog's `Tractor` type: the simulation
    should not depend on catalog bookkeeping, and Stage 7 will construct these
    from a ROS parameter server instead.
    """

    wheelbase: float  # m
    max_steer_angle: float  # rad

    def __post_init__(self) -> None:
        if self.wheelbase <= 0:
            raise ValueError("wheelbase must be positive")
        if not 0 < self.max_steer_angle < np.pi / 2:
            raise ValueError("max_steer_angle must lie in (0, pi/2)")


def from_tractor(tractor) -> VehicleParams:
    """Build vehicle parameters from a Stage 0 catalog entry."""
    return VehicleParams(
        wheelbase=tractor.wheelbase.value,
        max_steer_angle=tractor.max_steer_angle.value,
    )


def kinematic_derivative(
    state_vec: np.ndarray, v: float, delta: float, wheelbase: float
) -> np.ndarray:
    """Time derivative of (x, y, theta)."""
    theta = state_vec[2]
    return np.array(
        [
            v * np.cos(theta),
            v * np.sin(theta),
            (v / wheelbase) * np.tan(delta),
        ]
    )


def rk4_step(
    state_vec: np.ndarray, v: float, delta: float, wheelbase: float, dt: float
) -> np.ndarray:
    """One fixed-step RK4 integration of the bicycle model.

    `v` and `delta` are held constant across the step (zero-order hold). The
    system is therefore autonomous over the interval, which is why no time
    argument appears. This models a real digital controller, which emits a
    held command at a fixed rate -- and it is the assumption Stage 2's
    actuator lag builds on.
    """

    def f(s: np.ndarray) -> np.ndarray:
        return kinematic_derivative(s, v, delta, wheelbase)

    k1 = f(state_vec)
    k2 = f(state_vec + 0.5 * dt * k1)
    k3 = f(state_vec + 0.5 * dt * k2)
    k4 = f(state_vec + dt * k3)
    return state_vec + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)


def steering_derivative(delta: float, delta_cmd: float, tau: float, rate_limit: float) -> float:
    """Rate of change of the actual steering angle (Stage 2).

        delta_dot = clamp((delta_cmd - delta) / tau, -rate_limit, +rate_limit)

    The clamp sits inside the derivative, so the ODE is non-smooth at the
    rate limit. RK4 still integrates it, but its formal order drops while the
    limit is active -- an honest consequence of a saturating plant, not an
    error. It matters only during large corrections, where the actuator is
    rate-bound and the trajectory is dominated by the limit rather than by
    integration accuracy.
    """
    return float(np.clip((delta_cmd - delta) / tau, -rate_limit, rate_limit))


def augmented_derivative(
    vec: np.ndarray, v: float, delta_cmd: float, wheelbase: float,
    tau: float, rate_limit: float,
) -> np.ndarray:
    """Derivative of the augmented state (x, y, theta, delta)."""
    theta, delta = vec[2], vec[3]
    return np.array(
        [
            v * np.cos(theta),
            v * np.sin(theta),
            (v / wheelbase) * np.tan(delta),
            steering_derivative(delta, delta_cmd, tau, rate_limit),
        ]
    )


def rk4_step_augmented(
    vec: np.ndarray, v: float, delta_cmd: float, wheelbase: float,
    tau: float, rate_limit: float, dt: float,
) -> np.ndarray:
    """One RK4 step of the augmented plant, delta_cmd held across the step."""

    def f(s: np.ndarray) -> np.ndarray:
        return augmented_derivative(s, v, delta_cmd, wheelbase, tau, rate_limit)

    k1 = f(vec)
    k2 = f(vec + 0.5 * dt * k1)
    k3 = f(vec + 0.5 * dt * k2)
    k4 = f(vec + dt * k3)
    return vec + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
