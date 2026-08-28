"""Physical parameters that carry their own provenance.

Every physical number that reaches the simulation is wrapped in a `Param`.
A bare float cannot record where it came from, so a catalog of bare floats
makes the project's provenance rule unenforceable -- it degrades into a
discipline someone has to remember. Wrapping the value makes it structural:
a `Param` cannot be constructed at all unless it is either traceable to a
real source or explicitly flagged as an assumption with a stated rationale.

The two states are mutually exclusive on purpose. A parameter that carries
both a source and an `assumed` flag is ambiguous about which one the reader
should trust, so construction rejects it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    """A physical value plus the evidence for it.

    Attributes:
        value: Magnitude, always in the SI unit named by `unit`.
        unit: SI unit symbol ('m', 'kg', 'W', 'rad', ...).
        source: URL or document citation. Required unless `assumed`.
        assumed: True when no real source exists for this value.
        rationale: Why this assumed value is defensible. Required if `assumed`.
        note: Optional audit trail, e.g. the figure as printed at the source
            before unit conversion. Converting 120.1 in to 3.051 m is a
            transformation of the evidence, so the original figure is kept
            here to keep the conversion checkable.
    """

    value: float
    unit: str
    source: str | None = None
    assumed: bool = False
    rationale: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.assumed:
            if self.source:
                raise ValueError(
                    "Param is marked assumed but also carries a source; "
                    "a value is either sourced or assumed, not both."
                )
            if not self.rationale:
                raise ValueError(
                    "Assumed Param requires a rationale explaining why the "
                    "value is defensible."
                )
        else:
            if not self.source:
                raise ValueError(
                    "Param requires either a source or assumed=True with a "
                    "rationale. Unsourced values must not enter the catalog."
                )
            if self.rationale:
                raise ValueError(
                    "rationale is only meaningful on an assumed Param."
                )

    def describe(self) -> str:
        """One-line human-readable provenance, for assumption reports."""
        head = f"{self.value:g} {self.unit}"
        if self.assumed:
            return f"{head}  [ASSUMED: {self.rationale}]"
        return f"{head}  [source: {self.source}]"
