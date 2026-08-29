"""Request validation.

Every field is bounded. Unknown fields are rejected outright rather than
ignored, so a typo or an injected key fails loudly instead of silently
selecting a default. Bounds are physical where possible: a negative speed or
a 90 degree side slope is not a hostile input so much as a meaningless one,
and both are refused in the same place.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FieldRef(BaseModel):
    """A real location whose ground the simulation should run on."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    heading_deg: float = Field(default=90.0, ge=0.0, lt=360.0)


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tractor: str = Field(min_length=1, max_length=64)
    implement: str | None = Field(default=None, max_length=64)
    controller: Literal["pure_pursuit", "stanley"] = "pure_pursuit"

    speed: float = Field(default=3.0, ge=0.5, le=15.0)
    duration: float = Field(default=60.0, ge=5.0, le=300.0)
    initial_offset: float = Field(default=3.0, ge=-10.0, le=10.0)

    lookahead_gain: float = Field(default=0.5, ge=0.0, le=3.0)
    lookahead_min: float = Field(default=3.0, gt=0.0, le=20.0)
    stanley_gain: float = Field(default=2.0, gt=0.0, le=50.0)

    slope_deg: float = Field(default=0.0, ge=0.0, le=25.0)
    slope_sign: Literal[-1, 1] = 1
    slip: float = Field(default=0.0, ge=0.0, le=0.5)
    implement_drift_ratio: float = Field(default=1.0, ge=0.0, le=3.0)

    actuator: bool = True

    # Field work rather than one endless line. With passes > 1 the machine
    # works parallel passes spaced one working width apart, turning on the
    # headland between them, which is where the implement error that matters
    # for coverage actually comes from. `duration` is then computed from the
    # work to be done and the value sent is ignored.
    passes: int = Field(default=1, ge=1, le=10)
    pass_length: float = Field(default=200.0, ge=40.0, le=800.0)
    headland: float = Field(default=12.0, ge=4.0, le=40.0)

    # When given, the side slope comes from real elevation along this line and
    # `slope_deg` is ignored. The ground then changes under the machine as it
    # drives, which a single slope number cannot represent.
    field: FieldRef | None = None

    @field_validator("tractor", "implement")
    @classmethod
    def identifier_charset(cls, value: str | None) -> str | None:
        """Catalog ids only. Keeps arbitrary text out of lookup paths."""
        if value is None:
            return None
        if not all(c.isalnum() or c in "_-." for c in value):
            raise ValueError("identifier may contain only letters, digits, _ - and .")
        return value


class FieldRequest(BaseModel):
    """A real location to read ground slope from."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    heading_deg: float = Field(default=90.0, ge=0.0, lt=360.0)
    # How far across the field the plane is fitted. Too small and it reads
    # surface roughness; too large and it averages the field away.
    extent_m: float = Field(default=60.0, ge=10.0, le=400.0)
