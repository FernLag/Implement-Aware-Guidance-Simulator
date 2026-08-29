"""Typed equipment records.

Field selection is driven strictly by what later stages consume:

    wheelbase           Stage 1 bicycle model, theta_dot = (v/L)*tan(delta)
    max_steer_angle     Stage 1 saturation, Stage 2 slew clamp
    drawbar_power       Stage 0 pairing validity (draft capability)
    mass, tire_*        Stage 7 URDF link masses; unused in Stages 1-6
    working_width       Stage 4 edge error (+/- w/2); Stage 6 sweep variable
    hitch_distance      Stage 4 trailed hitch-angle kinematics
    implement_wheelbase Stage 4 trailed hitch-angle kinematics

Nothing is stored "because it was on the spec sheet". Tire sizes are the one
deliberate exception: they are inert for Stages 1-6 but cheap to record now
and awkward to re-source later for the Stage 7 URDF.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .param import Param

ImplementType = Literal["mounted", "trailed"]

# How the machine changes direction. The Stage 1 kinematic bicycle model
# represents front-wheel steering only: an articulated machine pivots about a
# frame joint between two bodies, which is a different model entirely (and one
# whose yaw response depends on the mass split, not on a steer angle).
# Catalogue them, but refuse to simulate them until that model exists.
SteeringType = Literal["wheel_steer", "articulated"]


@dataclass(frozen=True)
class Tractor:
    id: str
    manufacturer: str
    model: str
    years: str
    wheelbase: Param
    mass: Param
    engine_power: Param
    drawbar_power: Param
    max_steer_angle: Param
    tire_front: str | None = None
    tire_rear: str | None = None
    steering_type: SteeringType = "wheel_steer"
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.steering_type not in ("wheel_steer", "articulated"):
            raise ValueError(
                f"{self.id}: unknown steering_type {self.steering_type!r}"
            )

    @property
    def name(self) -> str:
        return f"{self.manufacturer} {self.model}"

    def params(self) -> dict[str, Param]:
        return {
            "wheelbase": self.wheelbase,
            "mass": self.mass,
            "engine_power": self.engine_power,
            "drawbar_power": self.drawbar_power,
            "max_steer_angle": self.max_steer_angle,
        }


@dataclass(frozen=True)
class Implement:
    id: str
    manufacturer: str
    model: str
    type: ImplementType
    working_width: Param
    mass: Param
    # Trailed geometry. Both are None for mounted implements, which ride with
    # the tractor and therefore have no hitch degree of freedom.
    hitch_distance: Param | None = None
    implement_wheelbase: Param | None = None
    # Tillage draft classification, used by the Stage 0 pairing check.
    draft_class: str | None = None
    # Spacing between the rows the implement plants or tends, where the
    # manufacturer publishes it. Absent for everything that does not work in
    # rows -- a disk harrow has no row spacing -- and never inferred for an
    # implement whose maker does not state one.
    row_spacing: Param | None = None
    working_depth: Param | None = None
    draft_power_per_width: Param | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.type == "trailed":
            if self.hitch_distance is None or self.implement_wheelbase is None:
                raise ValueError(
                    f"{self.id}: trailed implement requires both "
                    "hitch_distance and implement_wheelbase (Stage 4 needs "
                    "them to integrate hitch angle)."
                )
        elif self.type == "mounted":
            if self.hitch_distance is not None or self.implement_wheelbase is not None:
                raise ValueError(
                    f"{self.id}: mounted implement must not define hitch "
                    "geometry; it has no hitch degree of freedom."
                )
        else:
            raise ValueError(f"{self.id}: unknown implement type {self.type!r}")

    @property
    def name(self) -> str:
        return f"{self.manufacturer} {self.model}"

    @property
    def half_width(self) -> float:
        """Distance from implement centerline to working edge, metres."""
        return self.working_width.value / 2.0

    def params(self) -> dict[str, Param]:
        out: dict[str, Param] = {
            "working_width": self.working_width,
            "mass": self.mass,
        }
        for key in (
            "hitch_distance",
            "implement_wheelbase",
            "working_depth",
            "draft_power_per_width",
        ):
            val = getattr(self, key)
            if val is not None:
                out[key] = val
        return out
