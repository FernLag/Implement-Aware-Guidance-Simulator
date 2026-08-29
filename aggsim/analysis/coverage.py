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

    # This compares timestep against timestep, which only means anything if each
    # log is a single pass. A multi-pass log includes the headland turns, where
    # the implement is metres off a line it is not yet following; comparing that
    # against itself yields a large, entirely meaningless number. Use
    # `coverage_across_passes` for a multi-pass run.
    for log in (log_a, log_b):
        if getattr(log, "pass_index", None) is not None:
            worked = int(np.max(log.pass_index)) + 1
            if worked > 1:
                raise ValueError(
                    f"log covers {worked} passes including headland turns; "
                    "use coverage_across_passes() for a multi-pass run, or pass "
                    "a single pass via log.pass_slice(i)"
                )

    if same_direction:
        skip = log_a.edge_right - log_b.edge_left
    else:
        # Pass B's frame is rotated 180 degrees; its right edge abuts A's.
        skip = log_a.edge_right + log_b.edge_right

    return CoverageStats(
        working_width=working_width, skip=skip, same_direction=same_direction
    )


@dataclass(frozen=True)
class PassCoverage:
    """Skip and overlap between two passes that were actually driven."""

    lower: int
    upper: int
    along: np.ndarray  # m along the field
    skip: np.ndarray  # signed, + uncovered, - overlap
    working_width: float

    @property
    def rms_skip(self) -> float:
        return float(np.sqrt(np.mean(self.skip**2)))

    @property
    def mean_skip(self) -> float:
        return float(np.mean(self.skip))

    @property
    def worst_skip(self) -> float:
        return float(max(np.max(self.skip), 0.0)) + 0.0

    @property
    def worst_overlap(self) -> float:
        return float(max(-np.min(self.skip), 0.0)) + 0.0

    @property
    def uncovered_fraction(self) -> float:
        """Share of the compared length with any gap at all, however small.

        Read this together with `gap_area_per_100m`. When the two edges track
        each other closely they cross back and forth, so this sits near 50%
        while the gaps themselves are millimetres wide and the area lost is
        negligible. A high fraction alone is not evidence of a coverage problem;
        a high area is.
        """
        return float(np.mean(self.skip > 0.0))

    @property
    def gap_area_per_100m(self) -> float:
        """Uncovered ground in m^2 per 100 m of boundary.

        Mean gap width counting only where a gap exists (overlap does not
        backfill a skip elsewhere), times 100 m of travel.
        """
        return float(np.mean(np.maximum(self.skip, 0.0))) * 100.0

    def summary(self) -> dict:
        return {
            "between": [self.lower, self.upper],
            "compared_m": round(float(self.along[-1] - self.along[0]), 1),
            "mean_skip_cm": round(self.mean_skip * 100, 2),
            "rms_skip_cm": round(self.rms_skip * 100, 2),
            "worst_gap_cm": round(self.worst_skip * 100, 2),
            "worst_overlap_cm": round(self.worst_overlap * 100, 2),
            "uncovered_percent": round(self.uncovered_fraction * 100, 1),
            "gap_area_m2_per_100m": round(self.gap_area_per_100m, 3),
            "percent_of_width": round(100 * self.rms_skip / self.working_width, 3),
        }


def coverage_across_passes(log, plan, lower: int, samples: int = 240) -> PassCoverage:
    """Compare two passes the machine actually drove, edge against edge.

    `coverage_between_passes` answers what happens when two passes are worked
    identically, which is a useful bound and an assumption. This answers what
    happened between these two, driven in opposite directions, minutes apart,
    each entering from its own headland turn with its own error.

    The two passes are sampled at different times and travel opposite ways, so
    both edges are resampled onto a shared along-field coordinate before being
    compared. Only the overlapping stretch is used: the ends, where one pass
    was still turning, are not a fair comparison.
    """
    if log.edge_left_xy is None:
        raise ValueError("run carried no implement")
    if log.pass_index is None:
        raise ValueError("run had no field plan")

    upper = lower + 1
    a, b = log.pass_slice(lower), log.pass_slice(upper)

    # WHICH EDGE FACES WHICH NEIGHBOUR DEPENDS ON DIRECTION.
    #
    # The boundary between pass n and pass n+1 lies at y = -(n + 0.5) * width.
    # A forward pass reaches that boundary with its RIGHT edge; a return pass,
    # driving the other way, reaches it with its LEFT edge. So the two sides of
    # one boundary do not follow the same rule, and applying one rule to both
    # picks an edge a whole working width away.
    def edge_towards(sl, index, boundary_is_below):
        forward = plan.forward(index)
        use_right = forward if boundary_is_below else not forward
        xy = log.edge_right_xy[sl] if use_right else log.edge_left_xy[sl]
        x, y = xy[:, 0], xy[:, 1]
        order = np.argsort(x)
        return x[order], y[order]

    # For `lower` the boundary is on its downhill-numbered side; for `upper` it
    # is on the other one.
    ax, ay = edge_towards(a, lower, True)
    bx, by = edge_towards(b, upper, False)

    lo = max(ax.min(), bx.min(), 0.0)
    hi = min(ax.max(), bx.max(), plan.length)
    if not (hi > lo):
        raise ValueError("the two passes do not overlap along the field")

    along = np.linspace(lo, hi, samples)
    ya = np.interp(along, ax, ay)
    yb = np.interp(along, bx, by)

    # Pass `upper` lies at more negative y. Uncovered ground is where the lower
    # pass's edge stopped short of where the upper pass's edge reached.
    skip = ya - yb

    return PassCoverage(lower=lower, upper=upper, along=along, skip=skip,
                        working_width=plan.working_width)
