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
