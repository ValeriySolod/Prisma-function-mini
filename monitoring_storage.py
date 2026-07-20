from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from monitoring import MonitoringResult


class MonitoringStorageError(RuntimeError):
    """Raised when monitoring history cannot be stored or read safely."""


@dataclass(frozen=True)
class PersistedMonitoringCheck:
    check_id: str
    auction_id: str
    checked_at: datetime
    previous_status: str
    current_status: str
    status_changed: bool
    result: str
    error_message: str


@dataclass(frozen=True)
class PersistedStatusTransition:
    transition_id: str
    check_id: str
    auction_id: str
    detected_at: datetime
    previous_status: str
    current_status: str


class MonitoringStorage:
    """Durable, UI-independent storage for live monitoring observations."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._create_schema()
        except MonitoringStorageError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise MonitoringStorageError("Monitoring persistence could not be initialized.") from error

    @staticmethod
    def _add_note(primary: BaseException, detail: str) -> None:
        try:
            add_note = getattr(primary, "add_note", None)
            if callable(add_note):
                add_note(detail)
        except BaseException:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            primary = MonitoringStorageError("SQLite foreign key enforcement could not be enabled.")
            try:
                connection.close()
            except BaseException as close_error:
                self._add_note(primary, f"Connection close also failed: {close_error!r}")
            raise primary
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        except BaseException as primary:
            try:
                connection.close()
            except BaseException as close_error:
                self._add_note(primary, f"Connection close also failed: {close_error!r}")
            raise
        else:
            try:
                connection.close()
            except sqlite3.Error as error:
                raise MonitoringStorageError("Monitoring database connection could not be closed.") from error

    @staticmethod
    @contextmanager
    def _transaction(connection: sqlite3.Connection):
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield
            connection.commit()
        except BaseException as primary:
            try:
                connection.rollback()
            except BaseException as rollback_error:
                MonitoringStorage._add_note(primary, f"Transaction rollback also failed: {rollback_error!r}")
            raise

    def _create_schema(self) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS monitoring_checks (
                check_id TEXT PRIMARY KEY, auction_id TEXT NOT NULL, checked_at TEXT NOT NULL,
                previous_status TEXT NOT NULL, current_status TEXT NOT NULL,
                status_changed INTEGER NOT NULL CHECK(status_changed IN (0, 1)),
                result TEXT NOT NULL CHECK(result IN ('Success', 'Changed', 'Error')),
                error_message TEXT NOT NULL,
                CHECK((result = 'Changed') = status_changed),
                CHECK((result = 'Error' AND error_message <> '' AND status_changed = 0)
                   OR (result <> 'Error' AND error_message = '')),
                CHECK(length(trim(auction_id)) > 0),
                CHECK(length(trim(previous_status)) > 0),
                CHECK(length(trim(current_status)) > 0)
            )""",
            """CREATE TABLE IF NOT EXISTS monitoring_status_transitions (
                transition_id TEXT PRIMARY KEY, check_id TEXT NOT NULL UNIQUE,
                auction_id TEXT NOT NULL, detected_at TEXT NOT NULL,
                previous_status TEXT NOT NULL, current_status TEXT NOT NULL,
                CHECK(previous_status <> current_status),
                CHECK(length(trim(auction_id)) > 0),
                CHECK(length(trim(previous_status)) > 0),
                CHECK(length(trim(current_status)) > 0),
                FOREIGN KEY(check_id) REFERENCES monitoring_checks(check_id) ON DELETE RESTRICT
            )""",
            """CREATE TABLE IF NOT EXISTS monitoring_latest_status (
                auction_id TEXT PRIMARY KEY, current_status TEXT NOT NULL,
                checked_at TEXT NOT NULL, check_id TEXT NOT NULL UNIQUE,
                CHECK(length(trim(auction_id)) > 0),
                CHECK(length(trim(current_status)) > 0),
                FOREIGN KEY(check_id) REFERENCES monitoring_checks(check_id) ON DELETE RESTRICT
            )""",
            """CREATE INDEX IF NOT EXISTS idx_monitoring_checks_auction_time
               ON monitoring_checks(auction_id, checked_at, check_id)""",
            """CREATE INDEX IF NOT EXISTS idx_monitoring_checks_time
               ON monitoring_checks(checked_at, check_id)""",
            """CREATE INDEX IF NOT EXISTS idx_monitoring_transitions_auction_time
               ON monitoring_status_transitions(auction_id, detected_at, transition_id)""",
            """CREATE INDEX IF NOT EXISTS idx_monitoring_transitions_time
               ON monitoring_status_transitions(detected_at, transition_id)""",
        )
        with self._connection() as connection, self._transaction(connection):
            for statement in statements:
                connection.execute(statement)

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise MonitoringStorageError("Monitoring timestamps must include timezone information.")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _validate_observation(result: MonitoringResult) -> None:
        if not result.auction_id or not result.auction_id.strip():
            raise MonitoringStorageError("Monitoring auction_id must not be blank.")
        if not result.previous_status or not result.previous_status.strip():
            raise MonitoringStorageError("Monitoring baseline status must not be blank.")
        if result.result not in {"Success", "Changed", "Error", "Skipped"}:
            raise MonitoringStorageError("Unsupported monitoring result.")
        if result.result in {"Success", "Changed"}:
            if not result.current_status or not result.current_status.strip():
                raise MonitoringStorageError("Monitoring current status must not be blank.")
            if result.error_message:
                raise MonitoringStorageError(
                    "Successful monitoring observations cannot contain an error message."
                )
        elif result.result == "Error":
            if not result.error_message or not result.error_message.strip():
                raise MonitoringStorageError(
                    "Error monitoring observations require an error message."
                )
            if result.status_changed:
                raise MonitoringStorageError(
                    "Error monitoring observations cannot report a status change."
                )
        else:
            if result.status_changed or result.error_message:
                raise MonitoringStorageError(
                    "Skipped monitoring observations cannot report a change or error."
                )

    def persist(self, result: MonitoringResult) -> MonitoringResult | None:
        self._validate_observation(result)
        checked_at = self._timestamp(result.checked_at)
        if result.result == "Skipped":
            return None
        canonical_checked_at = result.checked_at.astimezone(timezone.utc)
        check_id = str(uuid.uuid4())
        try:
            with self._connection() as connection, self._transaction(connection):
                latest = connection.execute(
                    """SELECT current_status FROM monitoring_latest_status
                       WHERE auction_id = ?""",
                    (result.auction_id,),
                ).fetchone()
                effective_previous = (
                    latest["current_status"] if latest is not None
                    else result.previous_status
                )
                if result.result == "Error":
                    canonical = MonitoringResult(
                        result.auction_id, canonical_checked_at, effective_previous,
                        effective_previous, False, "Error", result.error_message,
                    )
                else:
                    changed = effective_previous != result.current_status
                    canonical = MonitoringResult(
                        result.auction_id, canonical_checked_at, effective_previous,
                        result.current_status, changed,
                        "Changed" if changed else "Success", "",
                    )
                connection.execute("INSERT INTO monitoring_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (check_id, canonical.auction_id, checked_at,
                     canonical.previous_status, canonical.current_status,
                     int(canonical.status_changed), canonical.result,
                     canonical.error_message))
                if canonical.result == "Changed":
                    connection.execute("INSERT INTO monitoring_status_transitions VALUES (?, ?, ?, ?, ?, ?)",
                        (str(uuid.uuid4()), check_id, canonical.auction_id, checked_at,
                         canonical.previous_status, canonical.current_status))
                if canonical.result != "Error":
                    connection.execute("""INSERT INTO monitoring_latest_status
                        (auction_id, current_status, checked_at, check_id) VALUES (?, ?, ?, ?)
                        ON CONFLICT(auction_id) DO UPDATE SET current_status=excluded.current_status,
                        checked_at=excluded.checked_at, check_id=excluded.check_id""",
                        (canonical.auction_id, canonical.current_status,
                         checked_at, check_id))
        except MonitoringStorageError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise MonitoringStorageError("Monitoring result could not be persisted.") from error
        return canonical

    def latest_status(self, auction_id: str) -> str | None:
        return self.latest_statuses((auction_id,)).get(auction_id)

    def latest_statuses(self, auction_ids: Iterable[str]) -> dict[str, str]:
        identifiers = tuple(dict.fromkeys(auction_ids))
        if not identifiers:
            return {}
        placeholders = ",".join("?" for _ in identifiers)
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    f"SELECT auction_id, current_status FROM monitoring_latest_status WHERE auction_id IN ({placeholders}) ORDER BY auction_id",
                    identifiers).fetchall()
        except (OSError, sqlite3.Error) as error:
            raise MonitoringStorageError("Latest monitoring status could not be read.") from error
        return {row["auction_id"]: row["current_status"] for row in rows}

    def check_history(self, auction_id: str | None = None) -> tuple[PersistedMonitoringCheck, ...]:
        where, parameters = ((" WHERE auction_id = ?", (auction_id,)) if auction_id is not None else ("", ()))
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM monitoring_checks" + where +
                    " ORDER BY checked_at, rowid", parameters
                ).fetchall()
        except (OSError, sqlite3.Error) as error:
            raise MonitoringStorageError("Monitoring check history could not be read.") from error
        return tuple(PersistedMonitoringCheck(row["check_id"], row["auction_id"],
            self._parse_timestamp(row["checked_at"]), row["previous_status"],
            row["current_status"], bool(row["status_changed"]), row["result"],
            row["error_message"]) for row in rows)

    def transition_history(self, auction_id: str | None = None) -> tuple[PersistedStatusTransition, ...]:
        where, parameters = ((" WHERE auction_id = ?", (auction_id,)) if auction_id is not None else ("", ()))
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM monitoring_status_transitions" + where +
                    " ORDER BY detected_at, rowid", parameters
                ).fetchall()
        except (OSError, sqlite3.Error) as error:
            raise MonitoringStorageError("Monitoring transition history could not be read.") from error
        return tuple(PersistedStatusTransition(row["transition_id"], row["check_id"],
            row["auction_id"], self._parse_timestamp(row["detected_at"]),
            row["previous_status"], row["current_status"]) for row in rows)
