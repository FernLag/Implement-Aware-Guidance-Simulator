"""Straight AB guidance line, and the geometry pure pursuit needs from it.

An AB line is treated as infinite in both directions, which is how guidance
systems treat it: the operator sets two points and the line extends across
the field.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def wrap_angle(angle: float) -> float:
    """Wrap to [-pi, pi].

    Exactly on the branch cut the sign is float-dependent: an angle that is
    mathematically an odd multiple of pi can land on either +pi or -pi
    depending on the sign of sin() at that representation. The two are the
    same angle, and pure pursuit never operates there -- alpha = pi means the
    goal point is directly behind the vehicle -- so this is documented rather
    than forced to a canonical side.
    """
    return float(np.arctan2(np.sin(angle), np.cos(angle)))


@dataclass(frozen=True)
class ABLine:
    a: tuple[float, float]
    b: tuple[float, float]

    def __post_init__(self) -> None:
        if np.allclose(self.a, self.b):
            raise ValueError("A and B must be distinct points")

    @property
    def direction(self) -> np.ndarray:
        """Unit vector from A towards B."""
        d = np.asarray(self.b, dtype=float) - np.asarray(self.a, dtype=float)
        return d / np.linalg.norm(d)

    @property
    def normal(self) -> np.ndarray:
        """Unit normal, the direction rotated +90 degrees.

        This fixes the sign convention: cross-track error is POSITIVE to the
        LEFT of the line. Stage 4 compares implement edge error against this
        signal, so a flipped sign there would masquerade as a real divergence.
        """
        u = self.direction
        return np.array([-u[1], u[0]])

    @property
    def heading(self) -> float:
        u = self.direction
        return float(np.arctan2(u[1], u[0]))

    def cross_track(self, x: float, y: float) -> float:
        """Signed perpendicular distance from the line, positive to the left."""
        d = np.array([x, y], dtype=float) - np.asarray(self.a, dtype=float)
        return float(np.dot(d, self.normal))

    def projection_parameter(self, x: float, y: float) -> float:
        """Arc-length coordinate of the closest point on the line."""
        d = np.array([x, y], dtype=float) - np.asarray(self.a, dtype=float)
        return float(np.dot(d, self.direction))

    def point_at(self, t: float) -> np.ndarray:
        return np.asarray(self.a, dtype=float) + t * self.direction

    def lookahead_point(self, x: float, y: float, l_d: float) -> np.ndarray:
        """Point on the line at distance `l_d` ahead of (x, y).

        Substituting the line into the circle of radius `l_d` gives

            t^2 + 2 t (d . u) + |d|^2 - l_d^2 = 0,     d = A - p

        whose discriminant reduces exactly to `l_d^2 - e^2`, with `e` the
        cross-track error. So the geometry states its own failure mode: when
        the vehicle is farther off the line than its lookahead distance, no
        intersection exists. That is reachable in normal use -- the Stage 1
        success criterion starts the tractor offset from the line -- so it is
        handled rather than left to produce NaN: aim at the closest point on
        the line, which drives the vehicle back towards it.
        """
        if l_d <= 0:
            raise ValueError("lookahead distance must be positive")

        p = np.array([x, y], dtype=float)
        d = np.asarray(self.a, dtype=float) - p
        u = self.direction

        b_half = float(np.dot(d, u))
        disc = b_half**2 - float(np.dot(d, d)) + l_d**2

        if disc < 0.0:
            # Farther from the line than the lookahead distance.
            return self.point_at(-b_half)
        return self.point_at(-b_half + np.sqrt(disc))
