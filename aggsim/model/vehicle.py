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

from .implement import hitch_angle_derivative


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
    """Build vehicle parameters from a Stage 0 catalog entry.

    Refuses articulated machines. The bicycle model steers by a front-wheel
    angle; an articulated tractor pivots about a frame joint between two
    bodies and its yaw response depends on how mass is split across that
    joint. Running one through this model would produce plausible numbers
    that mean nothing, which is worse than an error.
    """
    if getattr(tractor, "steering_type", "wheel_steer") == "articulated":
        raise ValueError(
            f"{tractor.id} steers by frame articulation; the Stage 1 bicycle "
            "model represents front-wheel steering only. Catalogued for "
            "reference, not simulatable until an articulated model exists."
        )
    return VehicleParams(
        wheelbase=tractor.wheelbase.value,
        max_steer_angle=tractor.max_steer_angle.value,
    )


def _terrain_terms(v: float, terrain) -> tuple[float, float]:
    """(effective forward speed, signed lateral drift) for a terrain, or none."""
    if terrain is None:
        return v, 0.0
    return v * terrain.speed_factor, terrain.lateral_drift


def kinematic_derivative(
    state_vec: np.ndarray, v: float, delta: float, wheelbase: float, terrain=None
) -> np.ndarray:
    """Time derivative of (x, y, theta).

    With terrain, forward speed is scaled by (1 - slip) and a lateral drift
    velocity is added perpendicular to the heading. The drift enters the
    position equations only: it translates the vehicle without yawing it,
    which is what a uniform down-slope pull does to a rigid body already in
    steady sideslip.
    """
    theta = state_vec[2]
    v_eff, drift = _terrain_terms(v, terrain)
    # Left-of-heading unit vector is (-sin theta, cos theta).
    return np.array(
        [
            v_eff * np.cos(theta) - drift * np.sin(theta),
            v_eff * np.sin(theta) + drift * np.cos(theta),
            (v_eff / wheelbase) * np.tan(delta),
        ]
    )


def rk4_step(
    state_vec: np.ndarray, v: float, delta: float, wheelbase: float, dt: float,
    terrain=None,
) -> np.ndarray:
    """One fixed-step RK4 integration of the bicycle model.

    `v` and `delta` are held constant across the step (zero-order hold). The
    system is therefore autonomous over the interval, which is why no time
    argument appears. This models a real digital controller, which emits a
    held command at a fixed rate -- and it is the assumption Stage 2's
    actuator lag builds on.
    """

    def f(s: np.ndarray) -> np.ndarray:
        return kinematic_derivative(s, v, delta, wheelbase, terrain)

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
    tau: float, rate_limit: float, terrain=None,
) -> np.ndarray:
    """Derivative of the augmented state (x, y, theta, delta)."""
    theta, delta = vec[2], vec[3]
    v_eff, drift = _terrain_terms(v, terrain)
    return np.array(
        [
            v_eff * np.cos(theta) - drift * np.sin(theta),
            v_eff * np.sin(theta) + drift * np.cos(theta),
            (v_eff / wheelbase) * np.tan(delta),
            steering_derivative(delta, delta_cmd, tau, rate_limit),
        ]
    )


def rk4_step_augmented(
    vec: np.ndarray, v: float, delta_cmd: float, wheelbase: float,
    tau: float, rate_limit: float, dt: float, terrain=None,
) -> np.ndarray:
    """One RK4 step of the augmented plant, delta_cmd held across the step."""

    def f(s: np.ndarray) -> np.ndarray:
        return augmented_derivative(s, v, delta_cmd, wheelbase, tau, rate_limit, terrain)

    k1 = f(vec)
    k2 = f(vec + 0.5 * dt * k1)
    k3 = f(vec + 0.5 * dt * k2)
    k4 = f(vec + dt * k3)
    return vec + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)


def plant_derivative(
    vec: np.ndarray, v: float, delta_cmd: float, wheelbase: float,
    tau: float | None, rate_limit: float | None, terrain=None, geometry=None,
) -> np.ndarray:
    """Derivative of the full plant state (x, y, theta, delta, theta_i).

    `tau is None` means an ideal actuator: the wheels are already at the
    commanded angle, so delta has no dynamics of its own and its derivative
    is zero (the caller assigns delta directly). That keeps Stages 1 and 3
    bit-for-bit reproducible while Stage 4 runs on the same code path.

    `geometry is None` means no implement; theta_i then simply tracks the
    tractor heading so the state stays well defined.
    """
    theta, delta, theta_i = vec[2], vec[3], vec[4]
    v_eff, drift = _terrain_terms(v, terrain)
    theta_dot = (v_eff / wheelbase) * np.tan(delta)

    delta_dot = (
        0.0 if tau is None else steering_derivative(delta, delta_cmd, tau, rate_limit)
    )

    if geometry is None:
        theta_i_dot = theta_dot
    else:
        # The implement drifts at its own rate (see Terrain: at ratio 1.0 the
        # steady-state hitch angle is exactly zero, so side-draft contributes
        # no steady divergence).
        drift_i = drift if terrain is None else terrain.implement_drift
        theta_i_dot = hitch_angle_derivative(
            theta, theta_i, theta_dot, v_eff, drift, drift_i, geometry
        )

    return np.array(
        [
            v_eff * np.cos(theta) - drift * np.sin(theta),
            v_eff * np.sin(theta) + drift * np.cos(theta),
            theta_dot,
            delta_dot,
            theta_i_dot,
        ]
    )


def rk4_step_plant(
    vec: np.ndarray, v: float, delta_cmd: float, wheelbase: float,
    tau: float | None, rate_limit: float | None, dt: float,
    terrain=None, geometry=None,
) -> np.ndarray:
    """One RK4 step of the full plant, delta_cmd held across the step."""

    def f(s: np.ndarray) -> np.ndarray:
        return plant_derivative(
            s, v, delta_cmd, wheelbase, tau, rate_limit, terrain, geometry
        )

    k1 = f(vec)
    k2 = f(vec + 0.5 * dt * k1)
    k3 = f(vec + 0.5 * dt * k2)
    k4 = f(vec + dt * k3)
    return vec + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
