"""Terrain effects: side slope and wheel slip (Stage 3).

The two effects are independently toggleable, because attributing a change in
behaviour to one of them requires being able to run the other alone.

SIDE SLOPE. The brief specifies a lateral drift velocity proportional to
g*sin(phi). Note the dimensions: g*sin(phi) is an ACCELERATION, so the
constant of proportionality carries units of seconds:

    v_drift = c_slope * g * sin(phi)

Physically c_slope stands in for the quasi-static balance between the
down-slope gravity component and lateral tyre resistance -- a full model would
resolve tyre cornering stiffness and normal load. It is unpublished, hence
assumed and swept.

IMPLEMENT SIDE-DRAFT. The implement sits on the same slope and drifts too,
but not necessarily at the same rate: soil-engaging tools resist lateral
motion far more strongly than tyres do. `implement_drift_ratio` carries that
difference.

This parameter is not cosmetic. Setting it to 1.0 makes zero hitch angle an
EXACT equilibrium of the trailed kinematics -- v_d cos(0) - v_d = 0 -- so the
implement aligns perfectly with the tractor and side-draft produces no
steady-state divergence at all. In other words the brief's second divergence
mechanism is inert unless the two bodies drift differently. The steady-state
hitch angle follows from linearising the hitch equation:

    theta_hitch ~= v_d (r - 1) / v_eff

which is zero at r = 1 and grows with the mismatch.

WHEEL SLIP. Forward velocity is scaled by (1 - s). The yaw equation uses that
same reduced velocity, which is what "reduce steering effectiveness
proportionally" amounts to: turning follows actual travel, not wheel rotation.
An independent steering-effectiveness factor would be a defensible
alternative; it is a one-line change in `terrain_velocity`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from ..catalog.param import Param

DATA_DIR = Path(__file__).parent / "data"

G = 9.80665  # m/s^2, standard gravity (BIPM SI definition)

# Proportionality between down-slope gravitational acceleration and the
# resulting lateral drift velocity. Assumed; swept in the Stage 3 outputs.
DEFAULT_DRIFT_COEFFICIENT = Param(
    value=0.10,
    unit="s",
    assumed=True,
    rationale=(
        "No published value relates side-slope angle to lateral drift rate "
        "for an agricultural tractor. 0.10 s gives 0.17 m/s of drift on a "
        "10 degree slope, which produces steady-state offsets of order 0.25 m "
        "-- the right magnitude to matter agronomically without dominating "
        "the simulation. The Stage 3 outputs sweep it; no conclusion may "
        "depend on the default."
    ),
)


DEFAULT_IMPLEMENT_DRIFT_RATIO = Param(
    value=1.0,
    unit="dimensionless",
    assumed=True,
    rationale=(
        "Ratio of the implement's lateral drift rate to the tractor's. No "
        "published value exists. 1.0 is the NEUTRAL choice, not the physical "
        "one: it makes zero hitch angle an exact equilibrium, so side-draft "
        "contributes no steady-state divergence and the brief's second "
        "mechanism is inert. A soil-engaging implement should resist lateral "
        "motion more than tyres do, implying a ratio below 1, but the value "
        "is unmeasured. Stage 4 reports both cases; Stage 6 must sweep it."
    ),
)


@dataclass(frozen=True)
class SlopeProfile:
    """Side slope as a function of distance along the guidance line.

    Real ground is not a plane. A single slope number answers "what would this
    machine do on a uniform hillside", which is a useful question but not the
    same as "what does it do in this field". A profile carries the signed side
    slope, positive meaning the ground falls to the left of travel, sampled at
    known distances and interpolated between them.

    Outside the sampled range the end values are held rather than extrapolated,
    because extrapolating a hillside past the data is inventing terrain.
    """

    positions: np.ndarray  # m along the line, ascending
    side_slope: np.ndarray  # rad, signed
    source: str = "unspecified"

    def __post_init__(self) -> None:
        if len(self.positions) != len(self.side_slope):
            raise ValueError("positions and side_slope must be the same length")
        if len(self.positions) < 2:
            raise ValueError("a profile needs at least two samples")
        if not np.all(np.diff(self.positions) > 0):
            raise ValueError("positions must increase")

    def at(self, x: float) -> float:
        return float(np.interp(x, self.positions, self.side_slope))

    @property
    def span(self) -> tuple[float, float]:
        return float(self.positions[0]), float(self.positions[-1])

    def summary(self) -> dict:
        deg = np.degrees(self.side_slope)
        return {
            "samples": int(len(self.positions)),
            "length_m": round(float(self.positions[-1] - self.positions[0]), 1),
            "min_deg": round(float(deg.min()), 3),
            "max_deg": round(float(deg.max()), 3),
            "mean_abs_deg": round(float(np.abs(deg).mean()), 3),
            "source": self.source,
        }


@dataclass(frozen=True)
class Terrain:
    """Side slope and slip. Defaults are flat ground with no slip."""

    slope_angle: float = 0.0  # rad, magnitude of the side slope
    slope_sign: float = 1.0  # +1 drift to the left of heading, -1 to the right
    slip: float = 0.0  # travel reduction fraction, 0 to <1
    drift_coefficient: Param = DEFAULT_DRIFT_COEFFICIENT
    implement_drift_ratio: Param = DEFAULT_IMPLEMENT_DRIFT_RATIO
    # When present, the ground varies along the pass and slope_angle is unused.
    profile: SlopeProfile | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.slip < 1.0:
            raise ValueError("slip must lie in [0, 1); s = 1 means no forward travel")
        if abs(self.slope_angle) >= np.pi / 2:
            raise ValueError("slope_angle must be below 90 degrees")
        if self.slope_sign not in (-1.0, 1.0):
            raise ValueError("slope_sign must be +1 (drift left) or -1 (drift right)")

    @property
    def lateral_drift(self) -> float:
        """Signed drift velocity perpendicular to heading, positive to the left.

        The uniform-hillside value. With a profile in place the position
        dependent `drift_at` is what the model uses.
        """
        return self.slope_sign * self.drift_coefficient.value * G * np.sin(self.slope_angle)

    def drift_at(self, x: float) -> float:
        """Drift where the machine actually is."""
        if self.profile is None:
            return self.lateral_drift
        return self.drift_coefficient.value * G * np.sin(self.profile.at(x))

    def implement_drift_at(self, x: float) -> float:
        return self.implement_drift_ratio.value * self.drift_at(x)

    @property
    def implement_drift(self) -> float:
        """Signed drift velocity of the implement, positive to its left."""
        return self.implement_drift_ratio.value * self.lateral_drift

    @property
    def speed_factor(self) -> float:
        return 1.0 - self.slip

    @property
    def slope_enabled(self) -> bool:
        return self.slope_angle != 0.0 or self.profile is not None

    @property
    def slip_enabled(self) -> bool:
        return self.slip != 0.0

    def params(self) -> dict[str, Param]:
        if not self.slope_enabled:
            return {}
        return {
            "drift_coefficient": self.drift_coefficient,
            "implement_drift_ratio": self.implement_drift_ratio,
        }


FLAT = Terrain()


def load_soils(data_dir: Path | None = None) -> dict[str, Param]:
    """Soil condition name -> slip Param."""
    data_dir = data_dir or DATA_DIR
    raw = yaml.safe_load((data_dir / "soils.yaml").read_text())["soils"]
    return {name: Param(**rec["slip"]) for name, rec in raw.items()}
