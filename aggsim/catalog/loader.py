"""Load YAML equipment data into typed, provenance-checked objects.

Provenance is enforced at construction (see `Param`), so a catalog entry with
an unsourced, unflagged number fails at load time rather than silently
reaching the simulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .param import Param
from .schema import Implement, Tractor

DATA_DIR = Path(__file__).parent / "data"


def _param(record: dict, key: str, *, required: bool = True) -> Param | None:
    raw = record.get(key)
    if raw is None:
        if required:
            raise ValueError(f"{record.get('id', '?')}: missing parameter {key!r}")
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            f"{record.get('id', '?')}: parameter {key!r} must be a mapping with "
            "value/unit and either source or assumed+rationale, not a bare number."
        )
    try:
        return Param(**raw)
    except TypeError as exc:
        raise ValueError(f"{record.get('id', '?')}: bad fields in {key!r}: {exc}") from exc
    except ValueError as exc:
        raise ValueError(f"{record.get('id', '?')}: {key!r}: {exc}") from exc


def _tractor(record: dict) -> Tractor:
    _reject_unknown(record, _TRACTOR_KEYS, "tractor")
    return Tractor(
        id=record["id"],
        manufacturer=record["manufacturer"],
        model=record["model"],
        years=record.get("years", "unknown"),
        wheelbase=_param(record, "wheelbase"),
        mass=_param(record, "mass"),
        engine_power=_param(record, "engine_power"),
        drawbar_power=_param(record, "drawbar_power"),
        max_steer_angle=_param(record, "max_steer_angle"),
        tire_front=record.get("tire_front"),
        tire_rear=record.get("tire_rear"),
        steering_type=record.get("steering_type", "wheel_steer"),
        notes=record.get("notes"),
    )


_IMPLEMENT_KEYS = {
    "id", "manufacturer", "model", "type", "working_width", "mass",
    "hitch_distance", "implement_wheelbase", "draft_class", "working_depth",
    "draft_power_per_width", "row_spacing", "notes",
}
_TRACTOR_KEYS = {
    "id", "manufacturer", "model", "years", "wheelbase", "mass",
    "engine_power", "drawbar_power", "max_steer_angle", "tire_front",
    "tire_rear", "steering_type", "notes",
}


def _reject_unknown(record: dict, allowed: set[str], what: str) -> None:
    """A key the loader does not understand is a silent data loss.

    Catalog entries are hand-written, so a typo in a field name would
    otherwise drop that parameter without a word -- including, in the worst
    case, a provenance field.
    """
    unknown = set(record) - allowed
    if unknown:
        raise ValueError(
            f"{record.get('id', '?')}: unknown {what} field(s) "
            f"{sorted(unknown)}; check for a typo."
        )


def _implement(record: dict) -> Implement:
    _reject_unknown(record, _IMPLEMENT_KEYS, "implement")
    return Implement(
        id=record["id"],
        manufacturer=record["manufacturer"],
        model=record["model"],
        type=record["type"],
        working_width=_param(record, "working_width"),
        mass=_param(record, "mass"),
        hitch_distance=_param(record, "hitch_distance", required=False),
        implement_wheelbase=_param(record, "implement_wheelbase", required=False),
        draft_class=record.get("draft_class"),
        row_spacing=_param(record, "row_spacing", required=False),
        working_depth=_param(record, "working_depth", required=False),
        draft_power_per_width=_param(record, "draft_power_per_width", required=False),
        notes=record.get("notes"),
    )


@dataclass(frozen=True)
class Catalog:
    tractors: dict[str, Tractor]
    implements: dict[str, Implement]

    def tractor(self, key: str) -> Tractor:
        try:
            return self.tractors[key]
        except KeyError:
            raise KeyError(
                f"unknown tractor {key!r}; available: {sorted(self.tractors)}"
            ) from None

    def implement(self, key: str) -> Implement:
        try:
            return self.implements[key]
        except KeyError:
            raise KeyError(
                f"unknown implement {key!r}; available: {sorted(self.implements)}"
            ) from None

    def assumed_params(self) -> list[tuple[str, str, Param]]:
        """Every assumed parameter in the catalog, as (entry, field, param)."""
        out = []
        for entry in list(self.tractors.values()) + list(self.implements.values()):
            for field, param in entry.params().items():
                if param.assumed:
                    out.append((entry.name, field, param))
        return out

    def assumption_report(self) -> str:
        """Human-readable list of every assumed value.

        The project rule is that assumptions are flagged in program output
        rather than silently baked in, so any entry point that runs a
        simulation should print this.
        """
        rows = self.assumed_params()
        if not rows:
            return "No assumed parameters in catalog."
        lines = [f"ASSUMED PARAMETERS ({len(rows)}) -- not sourced, treat as inputs:"]
        for name, field, param in rows:
            lines.append(f"  {name} :: {field} = {param.value:g} {param.unit}")
            lines.append(f"      {param.rationale.strip()}")
        return "\n".join(lines)


def load_catalog(data_dir: Path | None = None) -> Catalog:
    data_dir = data_dir or DATA_DIR
    tractors_raw = yaml.safe_load((data_dir / "tractors.yaml").read_text())["tractors"]
    implements_raw = yaml.safe_load((data_dir / "implements.yaml").read_text())["implements"]

    tractors = {}
    for rec in tractors_raw:
        t = _tractor(rec)
        if t.id in tractors:
            raise ValueError(f"duplicate tractor id {t.id!r}")
        tractors[t.id] = t

    implements = {}
    for rec in implements_raw:
        i = _implement(rec)
        if i.id in implements:
            raise ValueError(f"duplicate implement id {i.id!r}")
        implements[i.id] = i

    return Catalog(tractors=tractors, implements=implements)
