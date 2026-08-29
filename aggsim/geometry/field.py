"""A worked field: parallel passes, alternating direction, headland turns.

Stages 1 to 6 run a single straight AB line, which is the right place to
start because it isolates the tracking behaviour. It leaves two things out,
and both matter for the project's own claim.

THE TURN. A pass does not begin on the line. It begins wherever the headland
turn left the machine, and the implement arrives later and further out than
the tractor does, because it swings. The acquisition transient that Stage 6
scores is a stand-in for that; here it is the real thing.

THE NEIGHBOUR. Skip and overlap are properties of two passes, and until now
the analysis compared a pass with a copy of itself, which assumes both were
worked identically. Real adjacent passes are worked in opposite directions,
minutes apart, from different entry errors. With a plan they can be compared
to each other instead of to an assumption.

Lines are numbered from zero and spaced by the implement's working width, so
pass n is at lateral offset -n * width. Odd passes run in the opposite
direction, which is how a field is actually worked and which matters on a side
slope: the drift that pushed the machine one way going up pushes it the other
way coming back.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .abline import ABLine


@dataclass(frozen=True)
class FieldPlan:
    """A set of parallel passes over one field."""

    working_width: float  # m, the spacing between lines
    passes: int  # how many to work
    length: float  # m, the worked length of each pass
    headland: float = 12.0  # m beyond each end, where the turn happens

    def __post_init__(self) -> None:
        if self.working_width <= 0:
            raise ValueError("working width must be positive")
        if self.passes < 1:
            raise ValueError("a field needs at least one pass")
        if self.length <= 0:
            raise ValueError("pass length must be positive")
        if self.headland < 0:
            raise ValueError("headland cannot be negative")

    def offset(self, index: int) -> float:
        """Lateral position of a pass, metres left of the first line."""
        return -index * self.working_width

    def forward(self, index: int) -> bool:
        """True when this pass runs in the +x direction."""
        return index % 2 == 0

    def line(self, index: int) -> ABLine:
        """The guidance line for a pass, pointing the way it is driven.

        Direction matters: cross-track error is signed relative to the line's
        own left, so a return pass has its own frame and the sign of the error
        is reported in that frame, not in the first pass's.
        """
        y = self.offset(index)
        if self.forward(index):
            return ABLine((0.0, y), (1.0, y))
        return ABLine((self.length, y), (self.length - 1.0, y))

    def beyond_end(self, index: int, x: float) -> bool:
        """True once the machine has driven clear of this pass's far headland."""
        if self.forward(index):
            return x > self.length + self.headland
        return x < -self.headland

    def finished(self, index: int, x: float) -> bool:
        """True once the machine should turn onto the next pass."""
        if index >= self.passes - 1:
            return False  # nothing left to turn onto
        return self.beyond_end(index, x)

    def entry(self, index: int) -> tuple[float, float, float]:
        """Where a pass starts, as (x, y, heading), if driven cleanly."""
        y = self.offset(index)
        if self.forward(index):
            return -self.headland, y, 0.0
        return self.length + self.headland, y, np.pi

    @property
    def total_width(self) -> float:
        return (self.passes - 1) * self.working_width

    def summary(self) -> dict:
        return {
            "passes": self.passes,
            "working_width": round(self.working_width, 3),
            "length": round(self.length, 1),
            "headland": round(self.headland, 1),
            "total_width": round(self.total_width, 2),
            "worked_area_ha": round(
                self.passes * self.working_width * self.length / 10_000.0, 3
            ),
        }
