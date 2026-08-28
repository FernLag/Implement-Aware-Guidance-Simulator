"""Physical validity of a tractor/implement pairing.

The demand side uses a published draft-power-per-unit-width figure rather
than the ASABE D497 draft model. D497 is the right model -- it resolves soil
texture, speed and depth, which a single kW/m figure folds into one number --
but its A/B/C coefficient table is only available inside the paywalled
standard. Reproducing those coefficients from memory would put invented
numbers at the centre of the feasibility check, which is exactly the failure
this project cannot afford. The per-width figure is coarser but every value
is either published or flagged.

Swapping in D497 later changes only `required_power`; the interface here is
built to survive that substitution.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import Implement, Tractor


@dataclass(frozen=True)
class PairingCheck:
    tractor: Tractor
    implement: Implement
    required_power: float  # W
    available_power: float  # W
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons

    @property
    def utilisation(self) -> float:
        """Fraction of drawbar power the implement demands."""
        return self.required_power / self.available_power

    def __str__(self) -> str:
        verdict = "OK" if self.ok else "REJECTED"
        head = (
            f"{verdict}: {self.tractor.name} + {self.implement.name} "
            f"({self.required_power / 1000:.1f} kW required, "
            f"{self.available_power / 1000:.1f} kW drawbar, "
            f"{self.utilisation:.0%} utilisation)"
        )
        return "\n".join([head] + [f"  - {r}" for r in self.reasons])


def required_draft_power(implement: Implement) -> float:
    """Drawbar power the implement demands, in W.

    Requires a `draft_power_per_width` parameter on the implement record.
    """
    per_width = getattr(implement, "draft_power_per_width", None)
    if per_width is None:
        raise ValueError(
            f"{implement.id}: no draft_power_per_width parameter; cannot "
            "assess pairing feasibility."
        )
    return per_width.value * implement.working_width.value


def check_pairing(tractor: Tractor, implement: Implement) -> PairingCheck:
    """Reject physically impossible pairings.

    Currently one criterion: the implement must not demand more drawbar power
    than the tractor produces. Mounted-implement lift capacity is a second
    real constraint but is not checked, because three-point lift capacity is
    not sourced for the tractors in this catalog -- an unchecked constraint is
    preferable to one enforced with invented limits.
    """
    required = required_draft_power(implement)
    available = tractor.drawbar_power.value

    reasons = []
    if required > available:
        reasons.append(
            f"implement demands {required / 1000:.1f} kW but tractor delivers "
            f"only {available / 1000:.1f} kW at the drawbar"
        )

    return PairingCheck(
        tractor=tractor,
        implement=implement,
        required_power=required,
        available_power=available,
        reasons=reasons,
    )
