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


@dataclass(frozen=True)
class Terrain:
    """Side slope and slip. Defaults are flat ground with no slip."""

    slope_angle: float = 0.0  # rad, magnitude of the side slope
    slope_sign: float = 1.0  # +1 drift to the left of heading, -1 to the right
    slip: float = 0.0  # travel reduction fraction, 0 to <1
    drift_coefficient: Param = DEFAULT_DRIFT_COEFFICIENT

    def __post_init__(self) -> None:
        if not 0.0 <= self.slip < 1.0:
            raise ValueError("slip must lie in [0, 1); s = 1 means no forward travel")
        if abs(self.slope_angle) >= np.pi / 2:
            raise ValueError("slope_angle must be below 90 degrees")
        if self.slope_sign not in (-1.0, 1.0):
            raise ValueError("slope_sign must be +1 (drift left) or -1 (drift right)")

    @property
    def lateral_drift(self) -> float:
        """Signed drift velocity perpendicular to heading, positive to the left."""
        return self.slope_sign * self.drift_coefficient.value * G * np.sin(self.slope_angle)

    @property
    def speed_factor(self) -> float:
        return 1.0 - self.slip

    @property
    def slope_enabled(self) -> bool:
        return self.slope_angle != 0.0

    @property
    def slip_enabled(self) -> bool:
        return self.slip != 0.0

    def params(self) -> dict[str, Param]:
        return {"drift_coefficient": self.drift_coefficient} if self.slope_enabled else {}


FLAT = Terrain()


def load_soils(data_dir: Path | None = None) -> dict[str, Param]:
    """Soil condition name -> slip Param."""
    data_dir = data_dir or DATA_DIR
    raw = yaml.safe_load((data_dir / "soils.yaml").read_text())["soils"]
    return {name: Param(**rec["slip"]) for name, rec in raw.items()}
