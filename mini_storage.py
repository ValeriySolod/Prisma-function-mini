"""Transactional cumulative SQLite storage for Prisma Function Mini."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable, Iterable

from mini_domain import (
    CapacityType,
    HistoryRecord,
    NormalizedAuctionRecord,
    ProductType,
    SourceImportRequest,
    ValidationFailure,
    ValidationReason,
)
from runtime_paths import RuntimePaths, runtime_paths


class StorageOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class MiniStorageError(RuntimeError):
    """Base class for stable Mini storage failures."""


class AuctionConflictError(MiniStorageError):
    """A duplicate key was paired with a different immutable payload."""

    def __init__(self, result: "StorageResult") -> None:
        super().__init__("Incoming auction conflicts with an existing duplicate key.")
        self.result = result


@dataclass(frozen=True)
class StorageResult:
    operation_id: str
    outcome: StorageOutcome
    inserted: int
    duplicates: int
    conflicts: int
    validation_failures: int
    started_at: datetime
    completed_at: datetime


@dataclass(frozen=True)
class OperationAudit:
    operation_id: str
    request: SourceImportRequest
    outcome: StorageOutcome
    inserted: int
    duplicates: int
    conflicts: int
    validation_failures: int
    started_at: datetime
    completed_at: datetime
    failures: tuple[ValidationFailure, ...]


class MiniAuctionStorage:
    """Own the Mini schema at the approved runtime database location."""

    def __init__(self, *, paths: RuntimePaths | None = None,
                 environ: dict[str, str] | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        if paths is not None and environ is not None:
            raise ValueError("Pass paths or environ, not both.")
        selected = paths or runtime_paths(environ=environ)
        expected = selected.root / "data" / "prisma_function_mini.db"
        if selected.database != expected:
            raise ValueError("Mini database must use the approved runtime path.")
        selected.database.parent.mkdir(parents=True, exist_ok=True)
        self.paths = selected
        self.database_path = self.paths.database
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _transaction(self):
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def initialize_schema(self) -> None:
        with self._transaction() as connection:
            for statement in (
                """CREATE TABLE IF NOT EXISTS mini_auctions (
                    id INTEGER PRIMARY KEY,
                    auction_id TEXT NOT NULL,
                    network_point_id TEXT NOT NULL,
                    auction_date TEXT NOT NULL,
                    exit_market_or_storage TEXT,
                    entry_market_or_storage TEXT,
                    capacity_type TEXT NOT NULL,
                    network_point TEXT NOT NULL,
                    product_type TEXT NOT NULL,
                    flow_start TEXT NOT NULL,
                    flow_end TEXT NOT NULL,
                    booked_capacity_kwh_h TEXT NOT NULL,
                    duration_hours TEXT NOT NULL,
                    auction_tariff_eur_mwh_h TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    accumulated_at_utc TEXT NOT NULL,
                    UNIQUE(auction_id, network_point_id, capacity_type, flow_start, flow_end)
                )""",
                """CREATE TABLE IF NOT EXISTS mini_operations (
                    operation_id TEXT PRIMARY KEY,
                    requested_start TEXT NOT NULL,
                    requested_end TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    source_size_bytes INTEGER NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('completed', 'failed')),
                    inserted_count INTEGER NOT NULL CHECK(inserted_count >= 0),
                    duplicate_count INTEGER NOT NULL CHECK(duplicate_count >= 0),
                    conflict_count INTEGER NOT NULL CHECK(conflict_count >= 0),
                    validation_failure_count INTEGER NOT NULL CHECK(validation_failure_count >= 0),
                    started_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS mini_operation_failures (
                    operation_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    message TEXT NOT NULL,
                    source_row_number INTEGER,
                    field_name TEXT,
                    PRIMARY KEY(operation_id, position),
                    FOREIGN KEY(operation_id) REFERENCES mini_operations(operation_id)
                        ON DELETE RESTRICT
                )""",
            ):
                connection.execute(statement)

    def store(self, request: SourceImportRequest,
              records: Iterable[NormalizedAuctionRecord], *,
              validation_failures: Iterable[ValidationFailure] = ()) -> StorageResult:
        if not isinstance(request, SourceImportRequest):
            raise TypeError("request must be SourceImportRequest.")
        incoming = tuple(records)
        failures = tuple(validation_failures)
        if any(not isinstance(item, NormalizedAuctionRecord) for item in incoming):
            raise TypeError("records must contain NormalizedAuctionRecord values.")
        if any(not isinstance(item, ValidationFailure) for item in failures):
            raise TypeError("validation_failures must contain ValidationFailure values.")
        started_at = self._utc_now()
        operation_id = uuid.uuid4().hex

        if failures:
            with self._transaction() as connection:
                result = self._audit(connection, operation_id, request, StorageOutcome.FAILED,
                                     0, 0, 0, len(failures), failures, started_at)
            return result

        with self._transaction() as connection:
            inserted: list[NormalizedAuctionRecord] = []
            duplicates = 0
            conflict: ValidationFailure | None = None
            known: dict[tuple[object, ...], NormalizedAuctionRecord] = {}
            for row in connection.execute("SELECT * FROM mini_auctions"):
                record = self._record_from_row(row)
                known[self._key(record)] = record
            for record in incoming:
                key = self._key(record)
                previous = known.get(key)
                if previous is None:
                    known[key] = record
                    inserted.append(record)
                elif previous == record:
                    duplicates += 1
                else:
                    conflict = ValidationFailure(
                        ValidationReason.CONFLICTING_DUPLICATE,
                        "Incoming auction conflicts with an existing duplicate key.",
                    )
                    break

            if conflict is not None:
                result = self._audit(connection, operation_id, request, StorageOutcome.FAILED,
                                     0, duplicates, 1, 0, (conflict,), started_at)
            else:
                accumulated_at = self._utc_now()
                for position, record in enumerate(inserted):
                    self._before_insert(record, position)
                    connection.execute(self._INSERT_AUCTION, self._auction_values(
                        record, request.sha256, accumulated_at
                    ))
                result = self._audit(connection, operation_id, request, StorageOutcome.COMPLETED,
                                     len(inserted), duplicates, 0, 0, (), started_at)

        if conflict is not None:
            raise AuctionConflictError(result)
        return result

    def history(self) -> tuple[HistoryRecord, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute("""
                SELECT * FROM mini_auctions
                ORDER BY flow_start, flow_end, auction_id, network_point_id, capacity_type, id
            """).fetchall()
        return tuple(HistoryRecord(self._record_from_row(row), row["source_sha256"],
                                   self._parse_utc(row["accumulated_at_utc"])) for row in rows)

    def operations(self) -> tuple[OperationAudit, ...]:
        with closing(self._connect()) as connection:
            operations = connection.execute(
                "SELECT * FROM mini_operations ORDER BY started_at_utc, operation_id"
            ).fetchall()
            result = []
            for row in operations:
                failure_rows = connection.execute("""
                    SELECT * FROM mini_operation_failures
                    WHERE operation_id = ? ORDER BY position
                """, (row["operation_id"],)).fetchall()
                failures = tuple(ValidationFailure(
                    ValidationReason(item["reason"]), item["message"],
                    item["source_row_number"], item["field_name"],
                ) for item in failure_rows)
                request = SourceImportRequest(
                    requested_range=self._date_range(row["requested_start"], row["requested_end"]),
                    source_name=row["source_name"], sha256=row["source_sha256"],
                    size_bytes=row["source_size_bytes"],
                )
                result.append(OperationAudit(
                    row["operation_id"], request, StorageOutcome(row["outcome"]),
                    row["inserted_count"], row["duplicate_count"], row["conflict_count"],
                    row["validation_failure_count"], self._parse_utc(row["started_at_utc"]),
                    self._parse_utc(row["completed_at_utc"]), failures,
                ))
        return tuple(result)

    @staticmethod
    def _date_range(start: str, end: str):
        from mini_domain import MiniDateRange
        return MiniDateRange(date.fromisoformat(start), date.fromisoformat(end))

    def _audit(self, connection: sqlite3.Connection, operation_id: str,
               request: SourceImportRequest, outcome: StorageOutcome,
               inserted: int, duplicates: int, conflicts: int,
               validation_failure_count: int,
               failures: tuple[ValidationFailure, ...], started_at: datetime) -> StorageResult:
        completed_at = self._utc_now()
        connection.execute("""
            INSERT INTO mini_operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            operation_id, request.requested_range.start.isoformat(),
            request.requested_range.end.isoformat(), request.source_name, request.sha256,
            request.size_bytes, outcome.value, inserted, duplicates, conflicts,
            validation_failure_count, started_at.isoformat(), completed_at.isoformat(),
        ))
        connection.executemany("""
            INSERT INTO mini_operation_failures
                (operation_id, position, reason, message, source_row_number, field_name)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ((operation_id, position, failure.reason.value, failure.message,
                failure.source_row_number, failure.field_name)
               for position, failure in enumerate(failures)))
        return StorageResult(operation_id, outcome, inserted, duplicates, conflicts,
                             validation_failure_count, started_at, completed_at)

    def _utc_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Storage clock must return a timezone-aware datetime.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _before_insert(record: NormalizedAuctionRecord, position: int) -> None:
        """Test seam called inside the write transaction."""

    @staticmethod
    def _key(record: NormalizedAuctionRecord) -> tuple[object, ...]:
        key = record.duplicate_key
        return (key.auction_id, key.network_point_id, key.capacity_type,
                key.flow_start, key.flow_end)

    _INSERT_AUCTION = """
        INSERT INTO mini_auctions (
            auction_id, network_point_id, auction_date, exit_market_or_storage,
            entry_market_or_storage, capacity_type, network_point, product_type,
            flow_start, flow_end, booked_capacity_kwh_h, duration_hours,
            auction_tariff_eur_mwh_h, source_sha256, accumulated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    @staticmethod
    def _auction_values(record: NormalizedAuctionRecord, source_sha256: str,
                        accumulated_at: datetime) -> tuple[object, ...]:
        return (
            record.auction_id, record.network_point_id, record.auction_date.isoformat(),
            record.exit_market_or_storage, record.entry_market_or_storage,
            record.capacity_type.value, record.network_point, record.product_type.value,
            record.flow_start.isoformat(), record.flow_end.isoformat(),
            str(record.booked_capacity_kwh_h), str(record.duration_hours),
            str(record.auction_tariff_eur_mwh_h), source_sha256, accumulated_at.isoformat(),
        )

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> NormalizedAuctionRecord:
        return NormalizedAuctionRecord(
            auction_id=row["auction_id"], network_point_id=row["network_point_id"],
            auction_date=date.fromisoformat(row["auction_date"]),
            exit_market_or_storage=row["exit_market_or_storage"],
            entry_market_or_storage=row["entry_market_or_storage"],
            capacity_type=CapacityType(row["capacity_type"]), network_point=row["network_point"],
            product_type=ProductType(row["product_type"]),
            flow_start=datetime.fromisoformat(row["flow_start"]),
            flow_end=datetime.fromisoformat(row["flow_end"]),
            booked_capacity_kwh_h=Decimal(row["booked_capacity_kwh_h"]),
            duration_hours=Decimal(row["duration_hours"]),
            auction_tariff_eur_mwh_h=Decimal(row["auction_tariff_eur_mwh_h"]),
        )

    @staticmethod
    def _parse_utc(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise MiniStorageError("Stored audit timestamp is not timezone-aware.")
        return parsed.astimezone(timezone.utc)
