"""Translating implement edge error into skip and overlap (Stage 6).

Edge error in metres is the control-engineering answer. The agronomic
question is different: how much ground between adjacent passes is left
uncovered (skip) or worked twice (overlap).

THE NON-OBVIOUS PART. Adjacent passes are guided by lines spaced one working
width apart, so the NOMINAL positions of pass A's right edge and pass B's
left edge coincide. The gap between them is therefore the difference of their
edge ERRORS -- and for two passes worked under identical conditions the
centreline error cancels:

    skip = e_R(A) - e_L(B) = w (1 - cos theta_i)

A uniform lateral offset shifts the entire field pattern without opening a
single gap. Only differential effects create skip. This is why worst-case
edge error and skip answer different questions, and why RMS edge error
overstates the agronomic cost of a systematic offset. The residual term is
pure under-coverage: a yawed implement presents a projected width of
w cos(theta_i), narrower than its nominal width.

DIRECTION MATTERS. Worked back and forth, pass B is driven the other way, so
its body frame is rotated 180 degrees and the edge abutting pass A is pass
B's RIGHT edge, entering with the opposite sign:

    skip = e_R(A) + e_R(B)

Both conventions are provided because both are real practice: planting is
often worked in one direction, tillage back and forth.

Sign convention: POSITIVE skip is uncovered ground. Negative is overlap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CoverageStats:
    """Skip/overlap between two adjacent passes, in metres and as % of width."""

    working_width: float
    skip: np.ndarray  # signed, per timestep: + uncovered, - overlap
    same_direction: bool

    @property
    def mean_skip(self) -> float:
        return float(np.mean(self.skip))

    @property
    def rms_skip(self) -> float:
        return float(np.sqrt(np.mean(self.skip**2)))

    @property
    def worst_skip(self) -> float:
        """Largest uncovered gap; 0.0 if the passes never leave one."""
        return float(max(np.max(self.skip), 0.0)) + 0.0

    @property
    def worst_overlap(self) -> float:
        """Largest double-worked band, as a positive number."""
        return float(max(-np.min(self.skip), 0.0)) + 0.0

    @property
    def rms_skip_percent(self) -> float:
        """RMS skip as a percentage of working width -- the agronomic unit."""
        return 100.0 * self.rms_skip / self.working_width

    def summary(self) -> str:
        return (
            f"skip RMS {self.rms_skip * 100:.1f} cm "
            f"({self.rms_skip_percent:.2f}% of {self.working_width:.2f} m width), "
            f"worst gap {self.worst_skip * 100:.1f} cm, "
            f"worst overlap {self.worst_overlap * 100:.1f} cm"
        )


def coverage_between_passes(log_a, log_b, working_width: float,
                            same_direction: bool = True) -> CoverageStats:
    """Skip/overlap between two adjacent passes, timestep by timestep.

    `log_a` and `log_b` must be runs of equal length. Passing the same log
    twice is the common case: two passes worked under identical conditions.
    """
    if log_a.edge_right is None or log_b.edge_left is None:
        raise ValueError("both passes must carry an implement")
    if len(log_a.t) != len(log_b.t):
        raise ValueError("passes must be the same length to compare timestep-wise")

    if same_direction:
        skip = log_a.edge_right - log_b.edge_left
    else:
        # Pass B's frame is rotated 180 degrees; its right edge abuts A's.
        skip = log_a.edge_right + log_b.edge_right

    return CoverageStats(
        working_width=working_width, skip=skip, same_direction=same_direction
    )
