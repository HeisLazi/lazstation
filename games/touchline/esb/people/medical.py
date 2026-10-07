"""Exposure-driven medical records for P09 preparation.

Risk values are explicit scenario inputs. This module does not infer medical
facts from football capability or draw outcomes when callers inspect records.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum

from games.touchline.esb.ids import PlayerId, validate_id
from games.touchline.esb.time import WorldDate

MIN_ACUTE_DAYS = 2
MIN_REHABILITATION_DAYS = 7
MIN_RETURN_TO_PLAY_DAYS = 9
MIN_REHABILITATION_CONTACT_DATES = 3
MIN_RETURN_TO_PLAY_CONTACT_DATES = 2


class RehabStage(str, Enum):
    ACUTE = "acute"
    REHABILITATION = "rehabilitation"
    RETURN_TO_PLAY = "return_to_play"
    CLEARED = "cleared"


@dataclass(frozen=True)
class MedicalProfile:
    """An explicit provisional soft-tissue risk input, separate from ability."""

    player_id: PlayerId
    baseline_probability_per_90: float = 0.006
    recurrence_multiplier: float = 1.5
    provenance: str = "p09.provisional-neutral-default-v1"

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="medical profile player ID")
        for label, value in (
            ("baseline probability per 90", self.baseline_probability_per_90),
            ("recurrence multiplier", self.recurrence_multiplier),
        ):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{label} must be finite")
        if not 0.0 <= self.baseline_probability_per_90 <= 0.25:
            raise ValueError("baseline probability per 90 must be in [0, 0.25]")
        if not 1.0 <= self.recurrence_multiplier <= 5.0:
            raise ValueError("recurrence multiplier must be in [1, 5]")
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("medical risk requires explicit provenance")


@dataclass(frozen=True)
class InjuryEpisode:
    """One injury linked to the exposure that produced it."""

    injury_id: str
    player_id: PlayerId
    source_exposure_id: str
    occurred_on: WorldDate
    stage: RehabStage = RehabStage.ACUTE
    stage_started_on: WorldDate | None = None
    rehabilitation_dates: tuple[WorldDate, ...] = ()
    return_to_play_dates: tuple[WorldDate, ...] = ()
    injury_kind: str = "soft_tissue_strain"

    def __post_init__(self) -> None:
        validate_id(self.injury_id, kind="injury ID")
        validate_id(self.player_id, kind="injury player ID")
        validate_id(self.source_exposure_id, kind="injury source exposure ID")
        if not isinstance(self.occurred_on, WorldDate):
            raise TypeError("injury episode requires its exposure date")
        if not isinstance(self.stage, RehabStage):
            raise TypeError("injury episode requires a registered rehab stage")
        if self.stage_started_on is not None and not isinstance(self.stage_started_on, WorldDate):
            raise TypeError("rehabilitation stage date must be a WorldDate")
        if self.stage_started_on is not None and self.stage_started_on < self.occurred_on:
            raise ValueError("rehabilitation cannot start before the injury")
        if self.stage is RehabStage.ACUTE and self.stage_started_on is not None:
            raise ValueError("acute injury stage begins on the exposure date")
        if self.stage is not RehabStage.ACUTE and self.stage_started_on is None:
            raise ValueError("progressed rehab stages require their start date")
        if not isinstance(self.rehabilitation_dates, tuple) or not isinstance(self.return_to_play_dates, tuple):
            raise TypeError("rehabilitation dates must be immutable tuples")
        if len(set(self.rehabilitation_dates)) != len(self.rehabilitation_dates):
            raise ValueError("rehabilitation contacts cannot repeat a date")
        if len(set(self.return_to_play_dates)) != len(self.return_to_play_dates):
            raise ValueError("return-to-play contacts cannot repeat a date")
        if tuple(sorted(self.rehabilitation_dates)) != self.rehabilitation_dates:
            raise ValueError("rehabilitation contacts must retain calendar order")
        if tuple(sorted(self.return_to_play_dates)) != self.return_to_play_dates:
            raise ValueError("return-to-play contacts must retain calendar order")
        if any(day < self.occurred_on for day in self.rehabilitation_dates + self.return_to_play_dates):
            raise ValueError("rehabilitation contacts cannot precede the injury")
        if not isinstance(self.injury_kind, str) or not self.injury_kind.strip():
            raise ValueError("injury kind must be explicit")


def injury_probability(
    profile: MedicalProfile,
    *,
    minutes_played: float,
    exertion: float,
    fatigue: float,
    recurrence: bool,
) -> float:
    """Return the documented exposure risk without consuming randomness.

    Risk is the authored per-90 baseline scaled by minutes, exertion and current
    fatigue. A prior recorded soft-tissue episode applies the profile's explicit
    recurrence multiplier. The provisional result is capped at 25% per match.
    """

    if not isinstance(profile, MedicalProfile):
        raise TypeError("injury probability requires a MedicalProfile")
    if type(minutes_played) not in (int, float) or not math.isfinite(minutes_played) or not 0 <= minutes_played <= 150:
        raise ValueError("played minutes must be finite and in [0, 150]")
    for label, value in (("exertion", exertion), ("fatigue", fatigue)):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{label} must be finite and normalized to [0, 1]")
    if type(recurrence) is not bool:
        raise TypeError("recurrence flag must be explicit")
    if minutes_played == 0 or profile.baseline_probability_per_90 == 0.0:
        return 0.0
    repeat_factor = profile.recurrence_multiplier if recurrence else 1.0
    probability = (
        profile.baseline_probability_per_90
        * (minutes_played / 90.0)
        * (1.0 + float(exertion) + float(fatigue))
        * repeat_factor
    )
    return min(0.25, probability)


def progress_medical_day(
    episodes: tuple[InjuryEpisode, ...], day: WorldDate
) -> tuple[InjuryEpisode, ...]:
    """Advance each episode by at most one stage on one explicit world date."""

    if not isinstance(day, WorldDate):
        raise TypeError("medical progression requires an explicit world date")
    progressed: list[InjuryEpisode] = []
    for episode in episodes:
        if not isinstance(episode, InjuryEpisode):
            raise TypeError("medical history contains an invalid injury episode")
        if episode.stage is RehabStage.CLEARED:
            progressed.append(episode)
            continue
        age_days = (day.day - episode.occurred_on.day).days
        if age_days < 0:
            raise ValueError("medical history cannot progress before an injury")
        next_stage: RehabStage | None = None
        if episode.stage is RehabStage.ACUTE and age_days >= MIN_ACUTE_DAYS:
            next_stage = RehabStage.REHABILITATION
        elif (
            episode.stage is RehabStage.REHABILITATION
            and age_days >= MIN_REHABILITATION_DAYS
            and len(episode.rehabilitation_dates) >= MIN_REHABILITATION_CONTACT_DATES
        ):
            next_stage = RehabStage.RETURN_TO_PLAY
        elif (
            episode.stage is RehabStage.RETURN_TO_PLAY
            and age_days >= MIN_RETURN_TO_PLAY_DAYS
            and len(episode.return_to_play_dates) >= MIN_RETURN_TO_PLAY_CONTACT_DATES
        ):
            next_stage = RehabStage.CLEARED
        progressed.append(
            replace(episode, stage=next_stage, stage_started_on=day)
            if next_stage is not None else episode
        )
    return tuple(progressed)


def add_rehabilitation_contact(
    episode: InjuryEpisode, day: WorldDate, *, return_to_play: bool
) -> InjuryEpisode:
    """Record one qualifying rehab contact; a date contributes at most once."""

    if not isinstance(episode, InjuryEpisode) or not isinstance(day, WorldDate):
        raise TypeError("rehabilitation contact requires an injury and world date")
    if type(return_to_play) is not bool:
        raise TypeError("rehabilitation contact stage must be explicit")
    if return_to_play:
        if episode.stage is not RehabStage.RETURN_TO_PLAY:
            raise ValueError("return-to-play work requires the return-to-play stage")
        if day in episode.return_to_play_dates:
            return episode
        return replace(episode, return_to_play_dates=episode.return_to_play_dates + (day,))
    if episode.stage is not RehabStage.REHABILITATION:
        raise ValueError("rehabilitation work requires the rehabilitation stage")
    if day in episode.rehabilitation_dates:
        return episode
    return replace(episode, rehabilitation_dates=episode.rehabilitation_dates + (day,))


__all__ = [
    "InjuryEpisode",
    "MedicalProfile",
    "MIN_ACUTE_DAYS",
    "MIN_REHABILITATION_CONTACT_DATES",
    "MIN_REHABILITATION_DAYS",
    "MIN_RETURN_TO_PLAY_CONTACT_DATES",
    "MIN_RETURN_TO_PLAY_DAYS",
    "RehabStage",
    "add_rehabilitation_contact",
    "injury_probability",
    "progress_medical_day",
]
