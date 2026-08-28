"""Detecting when tracking stops being damped and starts oscillating.

"Oscillation begins" needs an objective definition, not an eyeball on a plot,
because Stage 2 must report the speed at which it happens and Stage 6 sweeps
over it.

The **primary** criterion is whether the response is still oscillating at the
END of a long run: max|e| over the final quarter, compared against a
tolerance. Oscillation "begins" at the lowest speed whose response never
settles.

The logarithmic decrement (below) is retained as a descriptive damping
measure, but it is NOT the criterion, for two reasons discovered by testing
it against long runs:

* Run-length dependence. At k = 0.10, v = 8 m/s the error swings to +/-24 m
  for about 100 s and then settles completely. A decrement fitted over a
  100 s window calls that "growing"; over 400 s it plainly converges. A
  criterion whose verdict flips with the window length cannot be reported.
* Saturation. The rate limit is reached even for a 1 m initial offset, so
  the response is not an exponentially decaying sinusoid at all. The
  decrement's underlying model does not hold while the actuator is
  rate-bound, and a near-zero zeta there is an artefact of fitting the wrong
  curve, not evidence of marginal stability.

Settling is immune to both: it asks the question the stage actually poses --
does the tractor end up on the line or not.

Two other candidates were rejected:

* Whole-run RMS. Over a fixed time window the acquisition transient occupies
  a smaller fraction of the run as speed rises, so RMS falls with speed as a
  pure artefact of the averaging window -- the opposite of the physical
  trend. RMS is still reported, but over the back half only.
* Median ratio of successive peaks. Fragile once the rate limiter makes peak
  spacing irregular; it produced a non-monotonic, and therefore untrustworthy,
  stability boundary.

Where zeta IS reported, it is preferred over a per-second growth rate because
it is dimensionless: a per-second measure confounds "less damped" with
"oscillates faster", and frequency rises with speed here.

Runs used for stability classification must be long enough for transients to
die. MIN_SETTLING_DURATION records the minimum this module will accept
without warning.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Below this damping ratio the response is treated as oscillatory. Not zero:
# a barely-decaying response is not meaningfully stable, and exact zero is
# unreachable in a nonlinear simulation.
ZETA_THRESHOLD = 0.02
MIN_PEAKS = 4

# Tolerance on the settled tail. 2 cm is well inside any agronomically
# meaningful guidance error and far above integration noise.
SETTLE_TOLERANCE = 0.02  # m
TAIL_FRACTION = 0.25

# Below this a slow transient can masquerade as a sustained oscillation.
MIN_SETTLING_DURATION = 250.0  # s

# Once the error decays to machine noise, every floating-point wobble reads as
# a local extremum. Without a floor the decrement is fitted to noise and
# reports a confidently wrong number.
NOISE_RELATIVE = 1e-3
NOISE_ABSOLUTE = 1e-6  # m


def error_extrema(t: np.ndarray, e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Local extrema of the error signal, as (times, values)."""
    d = np.diff(e)
    sign = np.sign(d)
    nonzero = sign != 0
    if not nonzero.any():
        return np.array([]), np.array([])
    idx_nz = np.where(nonzero)[0]
    turns = np.where(np.diff(sign[idx_nz]) != 0)[0]
    idx = idx_nz[turns] + 1
    return t[idx], e[idx]


def _denoise(times: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if not len(values):
        return times, values
    floor = max(NOISE_ABSOLUTE, NOISE_RELATIVE * float(np.max(np.abs(values))))
    keep = np.abs(values) > floor
    return times[keep], values[keep]


@dataclass(frozen=True)
class OscillationMetrics:
    n_peaks: int
    damping_ratio: float  # descriptive only; nan when too few peaks
    decrement: float  # log decrement per full cycle
    settled: bool
    tail_amplitude: float  # max |e| over the final quarter, metres
    rms: float
    duration: float
    peak_times: np.ndarray
    peak_values: np.ndarray

    @property
    def oscillating(self) -> bool:
        """Still swinging at the end of the run. The Stage 2 criterion."""
        return not self.settled

    @property
    def duration_sufficient(self) -> bool:
        return self.duration >= MIN_SETTLING_DURATION

    def classify(self) -> str:
        if self.settled:
            return "settles"
        return f"sustained (tail amplitude {self.tail_amplitude:.2f} m)"


def analyse_oscillation(log, skip_peaks: int = 1, tol: float = SETTLE_TOLERANCE) -> OscillationMetrics:
    """Classify a run: does it settle, and how damped is it while decaying."""
    times, values = _denoise(*error_extrema(log.t, log.cross_track))

    # The first extremum is the line-acquisition transient: present at every
    # speed, and uninformative about stability.
    mags = np.abs(values[skip_peaks:])

    if len(mags) < MIN_PEAKS:
        decrement = float("nan")
        zeta = float("nan")
    else:
        idx = np.arange(len(mags))
        slope = float(np.polyfit(idx, np.log(mags), 1)[0])  # per half cycle
        decrement = -2.0 * slope  # per full cycle
        zeta = float(decrement / np.sqrt(4.0 * np.pi**2 + decrement**2))

    duration = float(log.t[-1])
    tail = np.abs(log.cross_track[log.t >= duration * (1.0 - TAIL_FRACTION)])

    return OscillationMetrics(
        n_peaks=len(values),
        damping_ratio=zeta,
        decrement=decrement,
        settled=bool(tail.max() < tol) if tail.size else False,
        tail_amplitude=float(tail.max()) if tail.size else float("nan"),
        duration=duration,
        # Back half only -- see the module docstring on the RMS artefact.
        rms=log.rms_cross_track(settle_time=duration * 0.5),
        peak_times=times,
        peak_values=values,
    )


def onset_speed(run, speeds: np.ndarray, tolerance: float = 0.05) -> float | None:
    """Lowest speed at which the response oscillates, refined by bisection.

    `run` is a callable speed -> SimLog. Returns None when no speed in the
    supplied range oscillates -- a real answer, which must not be reported as
    a number.
    """
    stable, unstable = None, None
    for v in speeds:
        if analyse_oscillation(run(float(v))).oscillating:
            unstable = float(v)
            break
        stable = float(v)

    if unstable is None:
        return None
    if stable is None:
        return unstable  # already oscillating at the lowest speed tried

    while unstable - stable > tolerance:
        mid = 0.5 * (stable + unstable)
        if analyse_oscillation(run(mid)).oscillating:
            unstable = mid
        else:
            stable = mid
    return unstable
