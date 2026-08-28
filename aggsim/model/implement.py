"""Implement kinematics and the second error metric (Stage 4).

THE POINT OF THE PROJECT. Coverage quality -- skip and overlap between
adjacent passes -- depends on where the implement's working edge is, not on
where the tractor is. This module computes both so they can be compared.

TRAILED KINEMATICS. Standard one-trailer model, derived from the rolling
constraint rather than quoted. With the hitch a distance `a` behind the
tractor rear axle and the implement axle a distance `b` behind the hitch,
requiring the implement axle to carry no lateral velocity in its own frame
gives

    theta_i_dot = (1/b) [ v_eff sin(theta - theta_i)
                          + (v_d - a theta_dot) cos(theta - theta_i)
                          - v_d_implement ]

Derivation sketch: the hitch is rigid on the tractor, so
p_h = p_r - a (cos theta, sin theta) and p_h_dot picks up a term -a theta_dot
normal to the tractor. The implement axle is p_i = p_h - b (cos theta_i,
sin theta_i). Projecting p_i_dot onto the implement's lateral axis and
setting it equal to the implement's own drift yields the expression above.

The final term is the implement's OWN down-slope drift. It is what makes side
slope a source of divergence rather than a common-mode offset: the tractor's
drift acts perpendicular to theta, the implement's perpendicular to theta_i,
and those differ whenever the hitch angle is non-zero.

MOUNTED implements have no hitch degree of freedom -- they ride with the
tractor, so theta_i == theta. A trailed implement with b -> 0 is the same
thing in the limit (the constraint forces theta_i to theta instantly), so
that case is routed to the rigid path rather than dividing by zero.

THE THREE DIVERGENCE MECHANISMS, and where each lives:

1. A trailed implement lags the tractor's heading during corrections.
   -> the theta_i state; absent for mounted.
2. Side slope induces implement side-draft relative to the tractor.
   -> the v_d_implement term above.
3. Heading error is amplified at the outer edge in proportion to half the
   working width.
   -> `edge_errors`: the edge contributes -/+ (w/2)(1 - cos theta_i). That is
   second order in ANGLE but exactly LINEAR in half-width, which is the
   proportionality claimed. On a 21.2 m implement a 10 degree implement
   heading error is worth 0.15 m of edge error; at 20 degrees, 0.60 m.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Below this implement wheelbase the hitch constraint is treated as rigid.
# The trailed equation divides by b, and as b -> 0 the implement heading is
# slaved to the tractor's, so the limit is the mounted case.
RIGID_WHEELBASE_TOL = 1e-9

# A drawbar cannot swing past the tractor. Beyond roughly this angle a real
# implement fouls the wheels or the drawbar reaches its stop, and past 90
# degrees the one-trailer model is describing something that cannot happen.
# No manufacturer publishes the mechanical limit, so this is an assumption,
# and a run that reaches it is flagged rather than quietly continued: once the
# hitch is against its stop the kinematics here no longer describe the machine.
DEFAULT_MAX_HITCH_ANGLE = 1.4835  # rad, 85 degrees


@dataclass(frozen=True)
class ImplementGeometry:
    """Geometry the Stage 4 model needs, decoupled from the catalog record."""

    type: str  # "mounted" | "trailed"
    working_width: float  # m
    hitch_distance: float = 0.0  # a: tractor rear axle -> hitch point, m
    implement_wheelbase: float = 0.0  # b: hitch -> implement axle, m
    max_hitch_angle: float = DEFAULT_MAX_HITCH_ANGLE  # rad, assumed

    def __post_init__(self) -> None:
        if self.type not in ("mounted", "trailed"):
            raise ValueError(f"unknown implement type {self.type!r}")
        if self.working_width < 0:
            raise ValueError("working width must be non-negative")
        if self.hitch_distance < 0 or self.implement_wheelbase < 0:
            raise ValueError("hitch geometry must be non-negative")
        if not 0 < self.max_hitch_angle <= np.pi:
            raise ValueError("max_hitch_angle must lie in (0, pi]")

    @property
    def half_width(self) -> float:
        return self.working_width / 2.0

    @property
    def is_rigid(self) -> bool:
        """True when the implement heading is slaved to the tractor's."""
        return self.type == "mounted" or self.implement_wheelbase <= RIGID_WHEELBASE_TOL


def from_catalog(implement) -> ImplementGeometry:
    """Build Stage 4 geometry from a Stage 0 catalog entry."""
    return ImplementGeometry(
        type=implement.type,
        working_width=implement.working_width.value,
        hitch_distance=(
            implement.hitch_distance.value if implement.hitch_distance else 0.0
        ),
        implement_wheelbase=(
            implement.implement_wheelbase.value if implement.implement_wheelbase else 0.0
        ),
    )


def hitch_angle_derivative(
    theta: float,
    theta_i: float,
    theta_dot: float,
    v_eff: float,
    drift_tractor: float,
    drift_implement: float,
    geometry: ImplementGeometry,
) -> float:
    """Rate of change of the implement heading.

    For a rigid (mounted, or zero-wheelbase) implement this is simply the
    tractor's yaw rate: the implement cannot articulate.
    """
    if geometry.is_rigid:
        return theta_dot

    a, b = geometry.hitch_distance, geometry.implement_wheelbase
    rel = theta - theta_i
    return (
        v_eff * np.sin(rel)
        + (drift_tractor - a * theta_dot) * np.cos(rel)
        - drift_implement
    ) / b


def implement_position(
    x: float, y: float, theta: float, theta_i: float, geometry: ImplementGeometry
) -> np.ndarray:
    """Position of the implement reference point (its axle).

    p_i = p_rear_axle - a (cos theta, sin theta) - b (cos theta_i, sin theta_i)

    The working elements are taken to lie on the lateral axis through this
    point. Real tools are distributed fore and aft of the axle; that
    refinement would add a longitudinal offset per implement, which the
    catalog does not carry and no manufacturer publishes.
    """
    a, b = geometry.hitch_distance, geometry.implement_wheelbase
    return np.array(
        [
            x - a * np.cos(theta) - b * np.cos(theta_i),
            y - a * np.sin(theta) - b * np.sin(theta_i),
        ]
    )


def edge_positions(
    x: float, y: float, theta: float, theta_i: float, geometry: ImplementGeometry
) -> tuple[np.ndarray, np.ndarray]:
    """(left, right) working edge positions, in world coordinates."""
    centre = implement_position(x, y, theta, theta_i, geometry)
    lateral = np.array([-np.sin(theta_i), np.cos(theta_i)])  # left of implement
    half = geometry.half_width
    return centre + half * lateral, centre - half * lateral


def edge_errors(
    line, x: float, y: float, theta: float, theta_i: float, geometry: ImplementGeometry
) -> tuple[float, float]:
    """Signed placement error of the (left, right) working edges.

    An edge is where it SHOULD be when it sits half a working width from the
    guidance line, so the error is measured against +/- w/2, not against the
    line itself. Without that the metric would report a perfectly placed wide
    implement as having a large error equal to its half width.
    """
    left, right = edge_positions(x, y, theta, theta_i, geometry)
    half = geometry.half_width
    return (
        line.cross_track(left[0], left[1]) - half,
        line.cross_track(right[0], right[1]) + half,
    )


def worst_edge_error(
    line, x: float, y: float, theta: float, theta_i: float, geometry: ImplementGeometry
) -> float:
    """The larger-magnitude edge error, signed.

    Coverage is set by the worse edge: it is the one that decides skip or
    overlap against the adjacent pass.
    """
    left, right = edge_errors(line, x, y, theta, theta_i, geometry)
    return left if abs(left) >= abs(right) else right
