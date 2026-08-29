"""Dual-objective gain search (Stage 6).

For one configuration -- a tractor, an implement, a speed, a slope, a slip --
find the lookahead gain that minimises each objective separately:

    k_tractor    minimises RMS tractor cross-track error
    k_implement  minimises RMS worst-case implement edge error
    k_skip       minimises RMS skip between adjacent passes

and report how far apart they land.

WHY THE SCORING WINDOW INCLUDES A TRANSIENT. Stage 5 established that at
steady state on a constant slope the two error metrics differ by an additive
constant, so their minima would coincide by construction. Scoring pure steady
state could therefore only ever return a null result -- not because the
hypothesis is false, but because the scenario cannot express it. Each run
starts offset from the line, which is what happens at the end of every
headland turn, so the score covers both the correction and the settled
period.

ENDPOINT MINIMA ARE NOT OPTIMA. With a small acquisition offset the RMS of
both objectives falls monotonically as the lookahead shortens -- on a slope
because the steady-state offset is proportional to L_d (Stage 3), and on flat
ground because a gentle correction never overshoots. The minimum then sits on
the low edge of whatever range was searched, both objectives report the same
edge value, and the divergence reads as a spurious zero. `TuningResult.interior`
flags this so such configurations are reported as unconstrained, not as
agreement.

SUB-GRID RESOLUTION. A preliminary check found the two optima separated by
one to two steps of a 0.05 grid, which is not enough resolution to claim a
separation. `optimal_gain` therefore refines the discrete minimum with a
parabolic fit through its neighbours, so a reported divergence is not an
artefact of grid spacing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .coverage import coverage_between_passes


def optimal_gain(gains: np.ndarray, scores: np.ndarray,
                 valid: np.ndarray | None = None) -> float:
    """Minimising gain, refined below grid spacing by a parabolic fit.

    Returns the grid minimum unchanged when it sits on an endpoint, or when
    the fitted vertex falls outside the bracketing interval (which means the
    three points are not well described by a parabola).
    """
    if valid is not None:
        # A run where the hitch reached its stop is not a candidate optimum:
        # its error figures describe a machine folded into itself. Masking with
        # infinity keeps the index alignment that the parabolic refinement below
        # depends on.
        scores = np.where(valid, scores, np.inf)

    i = int(np.argmin(scores))
    if i == 0 or i == len(gains) - 1:
        return float(gains[i])
    if valid is not None and not (valid[i - 1] and valid[i + 1]):
        # Refining against a neighbour that is not a real measurement would
        # move the answer using a number that means nothing.
        return float(gains[i])

    x0, x1, x2 = gains[i - 1], gains[i], gains[i + 1]
    y0, y1, y2 = scores[i - 1], scores[i], scores[i + 1]

    denom = y0 - 2.0 * y1 + y2
    if denom <= 0:  # not convex here; trust the grid
        return float(x1)

    step = x1 - x0  # the grid is uniform
    vertex = x1 + 0.5 * step * (y0 - y2) / denom
    if not (x0 <= vertex <= x2):
        return float(x1)
    return float(vertex)


@dataclass(frozen=True)
class TuningResult:
    gains: np.ndarray
    rms_tractor: np.ndarray
    rms_edge: np.ndarray
    rms_skip: np.ndarray
    k_tractor: float
    k_implement: float
    k_skip: float
    working_width: float
    tractor_interior: bool = True
    implement_interior: bool = True
    # Gains at which the hitch reached its stop. Those runs describe a machine
    # folded into itself, so a configuration with any of them is not a clean
    # optimisation problem and is reported rather than averaged in.
    jackknifed_runs: int = 0
    valid: np.ndarray | None = None

    @property
    def optimum_is_clean(self) -> bool:
        """True when neither optimum sits next to an invalid run."""
        if self.valid is None:
            return True
        for k in (self.k_tractor, self.k_implement):
            i = int(np.argmin(np.abs(self.gains - k)))
            lo, hi = max(0, i - 1), min(len(self.valid) - 1, i + 1)
            if not self.valid[lo:hi + 1].all():
                return False
        return True

    @property
    def interior(self) -> bool:
        """True when both minima lie strictly inside the searched range.

        A minimum sitting on an endpoint is NOT an optimum -- it says only
        that the objective is still falling where the search stopped. Reading
        a divergence off two endpoint minima gives a spurious zero, so
        configurations that fail this check must be reported as
        unconstrained rather than as agreement.
        """
        return self.tractor_interior and self.implement_interior

    @property
    def divergence(self) -> float:
        """k_implement - k_tractor. Positive: the implement wants more lookahead."""
        return self.k_implement - self.k_tractor

    @property
    def relative_divergence(self) -> float:
        return self.divergence / self.k_tractor

    def _masked(self, scores: np.ndarray) -> np.ndarray:
        return scores if self.valid is None else np.where(self.valid, scores, np.inf)

    def edge_penalty_at_tractor_optimum(self) -> float:
        """How much worse the implement is when tuned for the tractor.

        The cost of optimising the wrong objective, as a fraction.
        """
        best = float(np.min(self._masked(self.rms_edge)))
        at_k_t = float(np.interp(self.k_tractor, self.gains, self.rms_edge))
        return (at_k_t - best) / best

    def tractor_improves_while_implement_worsens(self) -> bool:
        """True if some gain range tightens the tractor while whipping the
        implement -- the aggressive-tuning question posed by the brief."""
        d_tractor = np.gradient(self.rms_tractor, self.gains)
        d_edge = np.gradient(self.rms_edge, self.gains)
        return bool(np.any((d_tractor < 0) & (d_edge > 0)))


def scan_gains(
    run: Callable[[float], object],
    gains: np.ndarray,
    working_width: float,
    settle_time: float = 0.0,
) -> TuningResult:
    """Score every gain against all three objectives.

    `run` maps a lookahead gain to a SimLog carrying an implement.
    """
    rms_t, rms_e, rms_s, valid = [], [], [], []
    for k in gains:
        log = run(float(k))
        valid.append(not getattr(log, "jackknifed", False))
        rms_t.append(log.rms_cross_track(settle_time))
        rms_e.append(log.rms_worst_edge(settle_time))
        cov = coverage_between_passes(log, log, working_width, same_direction=True)
        rms_s.append(cov.rms_skip)

    rms_t = np.asarray(rms_t)
    rms_e = np.asarray(rms_e)
    rms_s = np.asarray(rms_s)
    valid = np.asarray(valid, dtype=bool)

    def _interior(scores: np.ndarray) -> bool:
        i = int(np.argmin(np.where(valid, scores, np.inf)))
        return 0 < i < len(scores) - 1

    return TuningResult(
        gains=np.asarray(gains),
        rms_tractor=rms_t,
        rms_edge=rms_e,
        rms_skip=rms_s,
        k_tractor=optimal_gain(gains, rms_t, valid),
        k_implement=optimal_gain(gains, rms_e, valid),
        k_skip=optimal_gain(gains, rms_s, valid),
        working_width=working_width,
        tractor_interior=_interior(rms_t),
        implement_interior=_interior(rms_e),
        jackknifed_runs=int((~valid).sum()),
        valid=valid,
    )
