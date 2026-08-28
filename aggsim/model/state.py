"""Vehicle state, referenced to the rear axle midpoint.

The rear-axle reference is what makes the kinematic bicycle equations exact
rather than approximate: under the no-slip assumption the rear wheel has no
lateral velocity, so the velocity vector lies exactly along the heading.
A front-axle or CG reference would need an extra term.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class State:
    """Rear-axle pose. Position in metres, heading in radians."""

    x: float
    y: float
    theta: float

    def as_array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.theta], dtype=float)

    @classmethod
    def from_array(cls, vec: np.ndarray) -> State:
        return cls(float(vec[0]), float(vec[1]), float(vec[2]))
