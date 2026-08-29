"""Comparing the kinematic model against a physics simulation (Stage 7).

The point of Stage 7 is not to show that the two agree. It is to find where
they stop agreeing, and to say under what conditions the kinematic model may
still be trusted. A validity envelope is a more useful result than a
correlation coefficient, and a good deal more honest.

COMPARING ON DISTANCE, NOT TIME. The two simulations do not travel at the
same speed. The kinematic model is commanded 3 m/s and does 3 m/s; the physics
model is commanded 3 m/s and does slightly less, because its wheels slip. If
the trajectories are compared sample by sample in time, that speed difference
alone shows up as a growing position error which has nothing to do with
tracking. Comparing at equal distance ALONG the line separates the two: the
lateral difference is then a disagreement about where the machine went, not
about how fast it got there. Longitudinal slip is reported separately, because
it is a real difference and worth its own number rather than being smuggled
into the headline one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Trajectory:
    """The minimum needed to compare two runs, from either simulator."""

    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    theta: np.ndarray
    cross_track: np.ndarray
    hitch_angle: np.ndarray | None = None

    def __post_init__(self) -> None:
        n = len(self.t)
        for name in ("x", "y", "theta", "cross_track"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} has a different length from t")
        if n < 2:
            raise ValueError("a trajectory needs at least two samples")

    @classmethod
    def from_log(cls, log) -> Trajectory:
        """A SimLog from Stages 1 to 6."""
        return cls(t=np.asarray(log.t, float), x=np.asarray(log.x, float),
                   y=np.asarray(log.y, float), theta=np.asarray(log.theta, float),
                   cross_track=np.asarray(log.cross_track, float),
                   hitch_angle=(None if log.theta_implement is None
                                else np.asarray(log.theta_implement, float)
                                - np.asarray(log.theta, float)))

    @classmethod
    def from_records(cls, records: list[dict]) -> Trajectory:
        """Whatever the Gazebo runner wrote out, in the same shape."""
        def col(key):
            return np.asarray([r[key] for r in records], dtype=float)
        hitch = None
        if records and "hitch_angle" in records[0]:
            hitch = col("hitch_angle")
        return cls(t=col("t"), x=col("x"), y=col("y"), theta=col("theta"),
                   cross_track=col("cross_track"), hitch_angle=hitch)


@dataclass(frozen=True)
class Divergence:
    """How far apart two simulations of the same configuration ended up."""

    along: np.ndarray  # m along the line, the shared coordinate
    lateral: np.ndarray  # m, physics minus kinematic, positive to the left
    heading: np.ndarray  # rad, wrapped
    hitch: np.ndarray | None
    speed_ratio: float  # physics distance covered / kinematic, over equal time

    @property
    def rms_lateral(self) -> float:
        return float(np.sqrt(np.mean(self.lateral ** 2)))

    @property
    def max_lateral(self) -> float:
        return float(np.max(np.abs(self.lateral)))

    @property
    def rms_heading_deg(self) -> float:
        return float(np.degrees(np.sqrt(np.mean(self.heading ** 2))))

    @property
    def max_hitch_deg(self) -> float | None:
        if self.hitch is None:
            return None
        return float(np.degrees(np.max(np.abs(self.hitch))))

    def within(self, tolerance_m: float) -> bool:
        """True if the kinematic model stayed inside tolerance everywhere."""
        return self.max_lateral <= tolerance_m

    def breakdown_distance(self, tolerance_m: float) -> float | None:
        """Distance along the line at which the two first disagree by more
        than the tolerance, or None if they never do."""
        over = np.flatnonzero(np.abs(self.lateral) > tolerance_m)
        if not over.size:
            return None
        return float(self.along[over[0]])

    def summary(self, tolerance_m: float = 0.10) -> dict:
        return {
            "rms_lateral_m": round(self.rms_lateral, 4),
            "max_lateral_m": round(self.max_lateral, 4),
            "rms_heading_deg": round(self.rms_heading_deg, 4),
            "max_hitch_deg": (None if self.max_hitch_deg is None
                              else round(self.max_hitch_deg, 3)),
            "speed_ratio": round(self.speed_ratio, 4),
            "within_tolerance": self.within(tolerance_m),
            "breakdown_distance_m": (
                None if self.breakdown_distance(tolerance_m) is None
                else round(self.breakdown_distance(tolerance_m), 1)),
            "tolerance_m": tolerance_m,
            "compared_m": round(float(self.along[-1] - self.along[0]), 1),
        }


def _wrap(a: np.ndarray) -> np.ndarray:
    return (a + np.pi) % (2.0 * np.pi) - np.pi


def compare(kinematic: Trajectory, physics: Trajectory,
            samples: int = 400) -> Divergence:
    """Lateral disagreement between two runs, at equal distance along the line.

    Both are resampled onto the stretch of the line they have in common, so
    neither the difference in speed nor the difference in run length is counted
    as a tracking error.
    """
    lo = max(float(kinematic.x.min()), float(physics.x.min()))
    hi = min(float(kinematic.x.max()), float(physics.x.max()))
    if not (hi > lo):
        raise ValueError("the two runs do not overlap along the line")

    along = np.linspace(lo, hi, samples)

    def resample(traj, values):
        order = np.argsort(traj.x)
        return np.interp(along, traj.x[order], np.asarray(values)[order])

    lateral = resample(physics, physics.y) - resample(kinematic, kinematic.y)
    heading = _wrap(resample(physics, np.unwrap(physics.theta))
                    - resample(kinematic, np.unwrap(kinematic.theta)))

    hitch = None
    if kinematic.hitch_angle is not None and physics.hitch_angle is not None:
        hitch = _wrap(resample(physics, physics.hitch_angle)
                      - resample(kinematic, kinematic.hitch_angle))

    # Commanded speed is the same, so distance covered in equal time is the
    # cleanest statement of how much the physics model slipped.
    span = min(float(kinematic.t[-1]), float(physics.t[-1]))

    def travelled(traj):
        keep = traj.t <= span
        dx = np.diff(traj.x[keep])
        dy = np.diff(traj.y[keep])
        return float(np.sum(np.hypot(dx, dy)))

    k_dist = travelled(kinematic)
    ratio = travelled(physics) / k_dist if k_dist > 0 else float("nan")

    return Divergence(along=along, lateral=lateral, heading=heading,
                      hitch=hitch, speed_ratio=ratio)


@dataclass(frozen=True)
class EnvelopePoint:
    """One configuration, and whether the kinematic model survived it."""

    label: str
    speed: float
    slope_deg: float
    implement_mass: float
    divergence: Divergence

    def row(self, tolerance_m: float) -> dict:
        out = {"label": self.label, "speed": self.speed,
               "slope_deg": self.slope_deg,
               "implement_mass_kg": self.implement_mass}
        out.update(self.divergence.summary(tolerance_m))
        return out


def validity_envelope(points: list[EnvelopePoint],
                      tolerance_m: float = 0.10) -> dict:
    """Where the kinematic model stays within tolerance of the physics.

    Reported as the boundary in each variable rather than as a single verdict,
    because "the model is good to 5 m/s on ground up to 10 degrees" is a usable
    statement and "the mean error was 4 cm" is not.
    """
    if not points:
        raise ValueError("an envelope needs at least one configuration")

    inside = [p for p in points if p.divergence.within(tolerance_m)]
    outside = [p for p in points if not p.divergence.within(tolerance_m)]

    def bound(attr, ok):
        values = [getattr(p, attr) for p in ok]
        return None if not values else (min(values), max(values))

    return {
        "tolerance_m": tolerance_m,
        "configurations": len(points),
        "within": len(inside),
        "outside": len(outside),
        "speed_ok": bound("speed", inside),
        "slope_ok": bound("slope_deg", inside),
        "mass_ok": bound("implement_mass", inside),
        "worst": max(points, key=lambda p: p.divergence.max_lateral).label,
        "worst_max_lateral_m": round(
            max(p.divergence.max_lateral for p in points), 4),
        "rows": [p.row(tolerance_m) for p in points],
    }
