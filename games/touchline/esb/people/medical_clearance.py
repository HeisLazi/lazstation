"""Privacy-limited transfer medical outcomes derived from P09 injury history."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from games.touchline.esb.ids import derive_id, validate_id
from games.touchline.esb.people.medical import InjuryEpisode, RehabStage
from games.touchline.esb.time import WorldDate


class MedicalOutcome(str, Enum):
    CLEARED = "cleared"
    NOT_CLEARED = "not_cleared"


@dataclass(frozen=True)
class TransferMedicalAssessment:
    assessment_id: str
    player_id: str
    assessor_id: str
    assessed_on: WorldDate
    expires_on: WorldDate
    outcome: MedicalOutcome
    evidence_fingerprint: str

    def __post_init__(self) -> None:
        validate_id(self.assessment_id, kind="medical assessment ID")
        validate_id(self.player_id, kind="assessed player ID")
        validate_id(self.assessor_id, kind="medical assessor ID")
        if not isinstance(self.assessed_on, WorldDate) or not isinstance(self.expires_on, WorldDate):
            raise TypeError("transfer medical assessment requires explicit dates")
        if self.expires_on <= self.assessed_on:
            raise ValueError("medical assessment expiry must follow its date")
        if not isinstance(self.outcome, MedicalOutcome):
            raise TypeError("medical assessment requires a registered outcome")
        if (not isinstance(self.evidence_fingerprint, str) or len(self.evidence_fingerprint) != 64
                or any(char not in "0123456789abcdef" for char in self.evidence_fingerprint)):
            raise ValueError("medical assessment requires a lowercase SHA-256 evidence fingerprint")
        expected_id = derive_id(
            "medical-assessment", "p15c-transfer-medical-v2", self.player_id,
            self.assessor_id, self.assessed_on.isoformat, self.expires_on.isoformat,
            self.outcome.value, self.evidence_fingerprint,
        )
        if self.assessment_id != expected_id:
            raise ValueError("medical assessment ID does not match its dated evidence outcome")

    def valid_on(self, on: WorldDate) -> bool:
        if not isinstance(on, WorldDate):
            raise TypeError("medical validity check requires a WorldDate")
        return self.assessed_on <= on < self.expires_on


def assess_transfer_medical(
    player_id: str,
    assessor_id: str,
    episodes: tuple[InjuryEpisode, ...],
    on: WorldDate,
    *,
    validity_days: int = 14,
) -> TransferMedicalAssessment:
    """Derive a bounded clearance result; the assessment exposes no diagnosis."""

    validate_id(player_id, kind="assessed player ID")
    validate_id(assessor_id, kind="medical assessor ID")
    if not isinstance(on, WorldDate):
        raise TypeError("transfer medical check requires a WorldDate")
    if not isinstance(episodes, tuple) or any(not isinstance(item, InjuryEpisode) for item in episodes):
        raise TypeError("medical history must be an immutable InjuryEpisode tuple")
    if type(validity_days) is not int or validity_days <= 0:
        raise ValueError("medical assessment validity must be positive days")
    if any(item.player_id != player_id for item in episodes):
        raise ValueError("medical history cannot include another player's injury")
    if len({item.injury_id for item in episodes}) != len(episodes):
        raise ValueError("medical history cannot repeat an injury episode")
    if any(item.occurred_on > on for item in episodes):
        raise ValueError("medical assessment cannot include future injuries")
    if any(item.stage_started_on is not None and item.stage_started_on > on for item in episodes):
        raise ValueError("medical assessment cannot use a future rehabilitation state")
    evidence = [
        [item.injury_id, item.occurred_on.isoformat, item.stage.value,
         item.stage_started_on.isoformat if item.stage_started_on else None]
        for item in sorted(episodes, key=lambda row: row.injury_id)
    ]
    fingerprint = hashlib.sha256(
        json.dumps(evidence, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    outcome = (MedicalOutcome.CLEARED
               if all(item.stage is RehabStage.CLEARED for item in episodes)
               else MedicalOutcome.NOT_CLEARED)
    expires_on = WorldDate(on.day + timedelta(days=validity_days))
    return TransferMedicalAssessment(
        derive_id("medical-assessment", "p15c-transfer-medical-v2", player_id,
                  assessor_id, on.isoformat, expires_on.isoformat,
                  outcome.value, fingerprint),
        player_id, assessor_id, on, expires_on,
        outcome, fingerprint,
    )


__all__ = ["MedicalOutcome", "TransferMedicalAssessment", "assess_transfer_medical"]
