"""Experience-based tactical unit familiarity for P09."""

from __future__ import annotations

import math
from dataclasses import dataclass

from games.touchline.esb.ids import PlayerId, validate_id
from games.touchline.esb.people import PlayerProfile


@dataclass(frozen=True)
class LearningReceipt:
    source_id: str
    meaningful_repetitions: int
    familiarity_gain: float

    def __post_init__(self) -> None:
        validate_id(self.source_id, kind="learning source ID")
        if type(self.meaningful_repetitions) is not int or self.meaningful_repetitions <= 0:
            raise ValueError("learning receipt requires positive meaningful repetitions")
        if (
            type(self.familiarity_gain) not in (int, float)
            or not math.isfinite(self.familiarity_gain)
            or not 0.0 <= self.familiarity_gain <= 0.05
        ):
            raise ValueError("familiarity gain must be finite and in [0, 0.05]")


@dataclass(frozen=True)
class UnitFamiliarity:
    player_id: PlayerId
    unit_id: str
    familiarity: float = 0.0
    receipts: tuple[LearningReceipt, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="unit familiarity player ID")
        validate_id(self.unit_id, kind="tactical unit ID")
        if (
            type(self.familiarity) not in (int, float)
            or not math.isfinite(self.familiarity)
            or not 0.0 <= self.familiarity <= 1.0
        ):
            raise ValueError("unit familiarity must be finite and normalized to [0, 1]")
        if not isinstance(self.receipts, tuple) or any(
            not isinstance(receipt, LearningReceipt) for receipt in self.receipts
        ):
            raise TypeError("unit familiarity receipts must be immutable records")
        source_ids = [receipt.source_id for receipt in self.receipts]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("unit familiarity cannot count one source twice")


def learning_adaptability(profile: PlayerProfile) -> float:
    """Read the explicit adaptability capability, or use the neutral midpoint."""

    if not isinstance(profile, PlayerProfile):
        raise TypeError("learning adaptability requires a PlayerProfile")
    return next(
        (float(item.normalized_value) for item in profile.capabilities.capabilities
         if item.name == "adaptability"),
        0.5,
    )


def record_unit_experience(
    current: UnitFamiliarity | None,
    profile: PlayerProfile,
    *,
    unit_id: str,
    source_id: str,
    meaningful_repetitions: int,
) -> UnitFamiliarity:
    """Add one source once; adaptability changes learning rate only.

    The provisional model grants 0.1 percentage points per meaningful
    repetition at neutral adaptability (0.5), scaled by ``0.5 + adaptability``
    and capped at five percentage points from one source. It never changes
    technical capability.
    """

    if not isinstance(profile, PlayerProfile):
        raise TypeError("unit learning requires a PlayerProfile")
    validate_id(unit_id, kind="tactical unit ID")
    validate_id(source_id, kind="learning source ID")
    if type(meaningful_repetitions) is not int or meaningful_repetitions <= 0:
        raise ValueError("unit learning requires positive meaningful repetitions")
    if current is not None and (
        not isinstance(current, UnitFamiliarity)
        or current.player_id != profile.player_id
        or current.unit_id != unit_id
    ):
        raise ValueError("existing familiarity must match the player and unit")

    if current is not None:
        existing = next((receipt for receipt in current.receipts if receipt.source_id == source_id), None)
        if existing is not None:
            if existing.meaningful_repetitions != meaningful_repetitions:
                raise ValueError("learning source ID was reused with different repetitions")
            return current

    adaptability = learning_adaptability(profile)
    gain = min(0.05, round(meaningful_repetitions * 0.001 * (0.5 + adaptability), 8))
    prior = current or UnitFamiliarity(profile.player_id, unit_id)
    receipt = LearningReceipt(source_id, meaningful_repetitions, gain)
    return UnitFamiliarity(
        player_id=prior.player_id,
        unit_id=prior.unit_id,
        familiarity=min(1.0, prior.familiarity + gain),
        receipts=prior.receipts + (receipt,),
    )


__all__ = [
    "LearningReceipt",
    "UnitFamiliarity",
    "learning_adaptability",
    "record_unit_experience",
]
