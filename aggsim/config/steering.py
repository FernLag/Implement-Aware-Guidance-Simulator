"""Steering actuator configuration.

The controller emits a *commanded* angle; the wheels follow it through a
first-order lag with a slew rate limit:

    delta_dot = clamp((delta_cmd - delta) / tau, -rate_limit, +rate_limit)

These live in a config structure rather than the equipment catalog because
they are not machine specifications -- no manufacturer publishes them, and
they are not attributes of a particular tractor model in the way a wheelbase
is. They carry the same `Param` provenance as catalog entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ..catalog.param import Param

DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class SteeringParams:
    tau: Param
    rate_limit: Param

    def __post_init__(self) -> None:
        if self.tau.value <= 0:
            raise ValueError("tau must be positive; use steering=None for an ideal actuator")
        if self.rate_limit.value <= 0:
            raise ValueError("rate_limit must be positive")

    def params(self) -> dict[str, Param]:
        return {"tau": self.tau, "rate_limit": self.rate_limit}

    def replace(self, *, tau: float | None = None, rate_limit: float | None = None) -> SteeringParams:
        """Vary a parameter for a sweep, preserving provenance as assumed.

        Sweeping is the reason these values are defensible despite being
        assumed, so the swept variant stays flagged.
        """
        def _swap(param: Param, value: float | None) -> Param:
            if value is None:
                return param
            return Param(
                value=value,
                unit=param.unit,
                assumed=True,
                rationale=f"swept value; baseline: {param.rationale}",
            )

        return SteeringParams(
            tau=_swap(self.tau, tau),
            rate_limit=_swap(self.rate_limit, rate_limit),
        )


def load_steering(data_dir: Path | None = None) -> SteeringParams:
    data_dir = data_dir or DATA_DIR
    raw = yaml.safe_load((data_dir / "steering.yaml").read_text())["steering"]
    return SteeringParams(tau=Param(**raw["tau"]), rate_limit=Param(**raw["rate_limit"]))
