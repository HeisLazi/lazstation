"""A deterministic catalog over one existing archive database per season.

The per-season ``WorldArchiveStore`` schema remains authoritative and
unchanged. The series catalog is an explicit SQLite composition layer; merely
importing this module never opens a file.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterator

from games.touchline.esb.ids import PlayerId, validate_id
from games.touchline.esb.world.archive import (
    PlayerCareerSummary,
    PlayerMatchSummary,
    SimulationProgress,
    WorldArchiveStore,
)
from games.touchline.esb.world.season import WorldSeasonSchedule


CATALOG_SCHEMA_VERSION = 1
_CATALOG_NAME = "archive-series.sqlite3"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArchiveSeriesMetrics:
    world_id: str
    seed: int
    seasons: int
    complete_seasons: int
    scheduled_fixtures: int
    archived_matches: int
    detailed_matches: int
    retained_events: int
    total_recorded_events: int
    player_rows: int
    unique_players: int
    database_bytes: int
    summary_bytes: int
    catalog_database_bytes: int
    on_disk_bytes: int


class WorldArchiveSeries:
    """Single-writer world archive catalog, with explicitly opened storage."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.catalog_path = self.root / _CATALOG_NAME
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> WorldArchiveSeries:
        if self._connection is not None:
            raise RuntimeError("archive series is already open")
        self.root.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.catalog_path, timeout=30, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("open the archive series with a context manager first")
        return self._connection

    def initialize(self, world_id: str, seed: int) -> None:
        """Create or validate the catalog identity under an explicit open."""
        validate_id(world_id, kind="archive-series world ID")
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError("archive-series root seed must be a non-negative signed 64-bit integer")
        tables = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if not tables:
            self.connection.executescript("BEGIN IMMEDIATE;\n" + _CATALOG_SCHEMA)
            try:
                self.connection.executemany(
                    "INSERT INTO catalog_meta(key, value) VALUES (?, ?)",
                    (("schema_version", str(CATALOG_SCHEMA_VERSION)),
                     ("world_id", world_id), ("seed", str(seed))),
                )
                self.connection.execute("COMMIT")
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise
        metadata = {row["key"]: row["value"] for row in self.connection.execute(
            "SELECT key, value FROM catalog_meta"
        )}
        expected = {
            "schema_version": str(CATALOG_SCHEMA_VERSION),
            "world_id": world_id,
            "seed": str(seed),
        }
        if metadata != expected:
            raise ValueError("archive series belongs to a different world, seed or catalog schema")

    def _identity(self) -> tuple[str, int]:
        metadata = {row["key"]: row["value"] for row in self.connection.execute(
            "SELECT key, value FROM catalog_meta"
        )}
        if metadata.get("schema_version") != str(CATALOG_SCHEMA_VERSION):
            raise RuntimeError("initialize this archive series before use")
        try:
            seed = int(metadata["seed"])
            world_id = metadata["world_id"]
        except (KeyError, ValueError) as exc:
            raise ValueError("archive-series catalog identity is malformed") from exc
        return world_id, seed

    @staticmethod
    def _season_path(season_id: str) -> str:
        digest = hashlib.sha256(season_id.encode("utf-8")).hexdigest()
        return f"seasons/{digest}.sqlite3"

    def _schedule_row(self, schedule: WorldSeasonSchedule) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM seasons WHERE season_id = ?", (schedule.season_id,),
        ).fetchone()

    def _decode_catalog_row(
        self, row: sqlite3.Row, world_id: str, seed: int,
    ) -> WorldSeasonSchedule:
        schedule_json = row["schedule_json"]
        if _sha256(schedule_json) != row["schedule_sha256"]:
            raise ValueError("archive-series schedule snapshot failed its integrity check")
        schedule = WorldSeasonSchedule.from_json(schedule_json)
        if (schedule.season_id != row["season_id"]
                or schedule.world_id != world_id or schedule.seed != seed):
            raise ValueError("archive-series schedule differs from its catalog identity")
        dates = [item.scheduled_on.day for item in schedule.ordered_fixtures]
        if (row["minimum_on"] != min(dates).isoformat()
                or row["maximum_on"] != max(dates).isoformat()):
            raise ValueError("archive-series date index differs from its immutable schedule")
        expected_path = self._season_path(schedule.season_id)
        if (row["archive_path"] != expected_path
                or row["path_sha256"] != _sha256(expected_path)):
            raise ValueError("archive-series season path failed its identity check")
        return schedule

    def _validate_catalog_index(self) -> tuple[tuple[sqlite3.Row, WorldSeasonSchedule], ...]:
        """Reconcile denormalized dates and globally unique match identities."""
        world_id, seed = self._identity()
        rows = self.connection.execute("SELECT * FROM seasons").fetchall()
        decoded = [(row, self._decode_catalog_row(row, world_id, seed)) for row in rows]
        decoded.sort(key=lambda pair: (
            min(item.scheduled_on.day for item in pair[1].ordered_fixtures),
            pair[1].season_id,
        ))
        previous_max: date | None = None
        fixture_ids: set[str] = set()
        match_ids: set[str] = set()
        for index, (row, schedule) in enumerate(decoded):
            dates = [item.scheduled_on.day for item in schedule.ordered_fixtures]
            minimum_on, maximum_on = min(dates), max(dates)
            if previous_max is not None and minimum_on <= previous_max:
                raise ValueError("archive-series catalog contains overlapping or unordered seasons")
            previous_max = maximum_on
            current_fixtures = {item.fixture_id for item in schedule.fixtures}
            current_matches = {str(item.match_id) for item in schedule.fixtures}
            if fixture_ids.intersection(current_fixtures):
                raise ValueError("fixture IDs must be unique across archive-series seasons")
            if match_ids.intersection(current_matches):
                raise ValueError("match IDs must be unique across archive-series seasons")
            fixture_ids.update(current_fixtures)
            match_ids.update(current_matches)
            if row["status"] == "pending" and index != len(decoded) - 1:
                raise ValueError("only the latest archive-series season may remain pending")
        return tuple(decoded)

    def simulate(
        self,
        schedule: WorldSeasonSchedule,
        *,
        maximum_fixtures: int | None = None,
    ) -> SimulationProgress:
        """Append/resume a season using the established single-season simulator."""
        if not isinstance(schedule, WorldSeasonSchedule):
            raise TypeError("archive series requires an immutable world season schedule")
        if type(maximum_fixtures) is not int and maximum_fixtures is not None:
            raise TypeError("maximum fixture count must be an integer or None")
        if maximum_fixtures is not None and maximum_fixtures < 0:
            raise ValueError("maximum fixture count cannot be negative")
        world_id, seed = self._identity()
        if schedule.world_id != world_id or schedule.seed != seed:
            raise ValueError("season schedule differs from archive-series world or root seed")
        indexed = self._validate_catalog_index()
        schedule_json = schedule.to_json()
        schedule_hash = _sha256(schedule_json)
        path = self._season_path(schedule.season_id)
        path_hash = _sha256(path)
        dates = [item.scheduled_on.day for item in schedule.ordered_fixtures]
        minimum_on, maximum_on = min(dates), max(dates)
        existing = self._schedule_row(schedule)
        if existing is None:
            if indexed:
                latest_row, latest_schedule = indexed[-1]
                if latest_row["status"] != "complete":
                    raise ValueError("complete the pending season before starting another season")
                with self._open_season_archive(latest_row["season_id"]) as latest_archive:
                    archived_count = int(latest_archive.connection.execute(
                        "SELECT COUNT(*) FROM archived_matches"
                    ).fetchone()[0])
                if archived_count != len(latest_schedule.fixtures):
                    raise ValueError(
                        "complete the pending season before starting another season; "
                        "catalog status does not match its archived fixtures"
                    )
                latest_max = max(item.scheduled_on.day for item in latest_schedule.ordered_fixtures)
                if minimum_on <= latest_max:
                    raise ValueError("archive-series seasons must be chronological and non-overlapping")
                existing_fixture_ids = {
                    item.fixture_id
                    for _, prior in indexed
                    for item in prior.fixtures
                }
                existing_match_ids = {
                    str(item.match_id)
                    for _, prior in indexed
                    for item in prior.fixtures
                }
                if existing_fixture_ids.intersection(item.fixture_id for item in schedule.fixtures):
                    raise ValueError("fixture IDs must be unique across archive-series seasons")
                if existing_match_ids.intersection(str(item.match_id) for item in schedule.fixtures):
                    raise ValueError("match IDs must be unique across archive-series seasons")
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                self.connection.execute(
                    "INSERT INTO seasons(season_id, schedule_sha256, schedule_json, minimum_on, "
                    "maximum_on, archive_path, path_sha256, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
                    (schedule.season_id, schedule_hash, schedule_json, minimum_on.isoformat(),
                     maximum_on.isoformat(), path, path_hash),
                )
                self.connection.execute("COMMIT")
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise
            existing = self._schedule_row(schedule)
        else:
            if (existing["schedule_sha256"] != schedule_hash
                    or existing["schedule_json"] != schedule_json
                    or existing["archive_path"] != path
                    or existing["path_sha256"] != path_hash):
                raise ValueError("season ID retry conflicts with its immutable schedule or archive path")

        archive_path = self.root / existing["archive_path"]
        with WorldArchiveStore(archive_path) as archive:
            progress = archive.simulate(schedule, maximum_fixtures=maximum_fixtures)
            season_metrics = archive.metrics()
        status = "complete" if progress.pending == 0 else "pending"
        self.connection.execute(
            "UPDATE seasons SET status = ?, metrics_json = ? WHERE season_id = ?",
            (status, _metrics_json(season_metrics), schedule.season_id),
        )
        return progress

    def _season_schedule(self, season_id: str) -> tuple[WorldSeasonSchedule, Path]:
        validate_id(season_id, kind="archive-series season ID")
        row = self.connection.execute(
            "SELECT * FROM seasons WHERE season_id = ?", (season_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown archive-series season: {season_id}")
        world_id, seed = self._identity()
        schedule = self._decode_catalog_row(row, world_id, seed)
        path = self.root / row["archive_path"]
        if not path.is_file():
            raise FileNotFoundError(f"archive-series season database is missing: {season_id}")
        return schedule, path

    @contextmanager
    def _open_season_archive(self, season_id: str) -> Iterator[WorldArchiveStore]:
        schedule, path = self._season_schedule(season_id)
        catalog_row = self.connection.execute(
            "SELECT status, metrics_json FROM seasons WHERE season_id = ?", (season_id,),
        ).fetchone()
        with WorldArchiveStore(path) as archive:
            archive.initialize(schedule)
            before = archive.metrics()
            if (catalog_row["metrics_json"] is not None
                    and catalog_row["metrics_json"] != _metrics_json(before)):
                raise ValueError("archive-series season metrics differ from the stored catalog projection")
            if (catalog_row["status"] == "complete"
                    and before.archived_matches != len(schedule.fixtures)):
                raise ValueError("completed archive-series season is missing archived fixtures")
            try:
                yield archive
            finally:
                after = archive.metrics()
                self.connection.execute(
                    "UPDATE seasons SET metrics_json = ? WHERE season_id = ?",
                    (_metrics_json(after), season_id),
                )

    @contextmanager
    def season_archive(self, season_id: str) -> Iterator[WorldArchiveStore]:
        """Open one season after validating catalog ordering and identities."""
        self._validate_catalog_index()
        with self._open_season_archive(season_id) as archive:
            yield archive

    def seasons(self) -> tuple[tuple[str, str, int, int], ...]:
        """Return season ID, completion state, scheduled count and archived count."""
        rows = self._validate_catalog_index()
        result = []
        for row, schedule in rows:
            with self._open_season_archive(row["season_id"]) as archive:
                archived = int(archive.connection.execute(
                    "SELECT COUNT(*) FROM archived_matches"
                ).fetchone()[0])
            result.append((row["season_id"], row["status"], len(schedule.fixtures), archived))
        return tuple(result)

    def player_match_history(
        self, player_id: PlayerId | str, *, competition_id: str | None = None,
    ) -> tuple[PlayerMatchSummary, ...]:
        validate_id(player_id, kind="archive-series player ID")
        if competition_id is not None:
            validate_id(competition_id, kind="archive-series competition ID")
        history = []
        for season_id, _, _, _ in self.seasons():
            with self._open_season_archive(season_id) as archive:
                history.extend(archive.player_match_history(player_id, competition_id=competition_id))
        return tuple(sorted(history, key=lambda item: (
            item.scheduled_on.day, item.match_id,
        )))

    def player_career_summary(
        self, player_id: PlayerId | str, *, competition_id: str | None = None,
    ) -> PlayerCareerSummary:
        history = self.player_match_history(player_id, competition_id=competition_id)
        totals: dict[str, int] = {}
        for match in history:
            for key, value in match.statistics:
                totals[key] = totals.get(key, 0) + value
        return PlayerCareerSummary(
            PlayerId(str(player_id)),
            len(history),
            sum(item.minutes_played > 0 for item in history),
            sum(item.minutes_played for item in history),
            tuple(sorted(totals.items())),
        )

    def metrics(self) -> ArchiveSeriesMetrics:
        world_id, seed = self._identity()
        scheduled = archived = detailed = retained = total_events = player_rows = 0
        summary_bytes = database_bytes = on_disk_bytes = 0
        players: set[str] = set()
        rows = self._validate_catalog_index()
        complete = 0
        for row, schedule in rows:
            scheduled += len(schedule.fixtures)
            complete += row["status"] == "complete"
            with self._open_season_archive(row["season_id"]) as archive:
                season = archive.metrics()
                archived += season.archived_matches
                detailed += season.detailed_matches
                retained += season.retained_events
                total_events += season.total_recorded_events
                player_rows += season.player_rows
                summary_bytes += season.summary_bytes
                database_bytes += season.database_bytes
                players.update(item[0] for item in archive.connection.execute(
                    "SELECT DISTINCT player_id FROM player_match_lines"
                ).fetchall())
            on_disk_bytes += (self.root / self._season_path(row["season_id"])).stat().st_size
        catalog_database_bytes = self.connection.execute("PRAGMA page_count").fetchone()[0] * self.connection.execute(
            "PRAGMA page_size"
        ).fetchone()[0]
        on_disk_bytes += self.catalog_path.stat().st_size
        return ArchiveSeriesMetrics(
            world_id, seed, len(rows), complete, scheduled, archived, detailed,
            retained, total_events, player_rows, len(players), database_bytes,
            summary_bytes, catalog_database_bytes, on_disk_bytes,
        )


_CATALOG_SCHEMA = """
CREATE TABLE catalog_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE seasons(
    season_id TEXT PRIMARY KEY,
    schedule_sha256 TEXT NOT NULL,
    schedule_json TEXT NOT NULL,
    minimum_on TEXT NOT NULL,
    maximum_on TEXT NOT NULL,
    archive_path TEXT NOT NULL UNIQUE,
    path_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'complete')),
    metrics_json TEXT
);
"""


def _metrics_json(metrics: object) -> str:
    return json.dumps(asdict(metrics), allow_nan=False, sort_keys=True, separators=(",", ":"))


__all__ = ["ArchiveSeriesMetrics", "WorldArchiveSeries"]
