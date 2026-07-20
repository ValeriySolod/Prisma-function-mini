"""Recoverable orchestration for user-supplied PRISMA Export CSV files.

SQLite is authoritative for source lifecycle. Legacy JSON is read only when the
ledger is empty. A pending ledger row precedes auction mutation; auction changes,
summary metadata, and the data_committed transition share one transaction. Excel
is staged, validated and atomically published before the accepted transition.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from csv_contracts import CsvFormat, detect_csv_format
from prisma_source_updates import AcceptedPrismaSource, PrismaSourceState, SourceUpdateStatus, evaluate_prisma_source_update
from processor import PrismaImportIssue, PrismaImportResult, import_prisma_export
from storage import AuctionStorage, AuctionStorageError


class PrismaWorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class PrismaWorkflowResult:
    processed: int | None
    inserted: int | None
    updated: int | None
    unchanged: int | None
    filtered: int | None
    rejected: int | None
    issues: tuple[PrismaImportIssue, ...]
    output_path: Path
    source_status: SourceUpdateStatus
    message: str
    audit_issue_count: int | None = None

    def summary(self) -> str:
        value = lambda item: "unavailable" if item is None else str(item)
        audit = self.audit_issue_count if self.audit_issue_count is not None else len(self.issues)
        return (
            f"{self.message} Processed: {value(self.processed)}; inserted: {value(self.inserted)}; "
            f"updated: {value(self.updated)}; unchanged: {value(self.unchanged)}; "
            f"filtered: {value(self.filtered)}; rejected: {value(self.rejected)}; "
            f"audit issues: {value(audit)}. Output: {self.output_path}"
        )


def _legacy_state(path: Path) -> PrismaSourceState:
    if not path.exists():
        return PrismaSourceState()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return PrismaSourceState(tuple(AcceptedPrismaSource(
            date.fromisoformat(item["source_date"]), item["source_name"], item["sha256"]
        ) for item in payload["accepted_sources"]))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise PrismaWorkflowError("The legacy PRISMA import state could not be read safely.") from exc


def _state(storage: AuctionStorage, legacy_path: Path) -> PrismaSourceState:
    rows = storage.operations()
    if not rows:
        legacy = _legacy_state(legacy_path)
        for accepted in legacy.accepted_sources:
            storage.import_legacy_operation(
                f"legacy-{accepted.source_date.isoformat()}-{accepted.sha256[:12]}",
                accepted.source_date.isoformat(), accepted.source_name, accepted.sha256,
            )
        rows = storage.operations()
    accepted = tuple(AcceptedPrismaSource(
        date.fromisoformat(row["source_date"]), row["source_name"], row["sha256"]
    ) for row in rows if row["status"] == "accepted")
    return PrismaSourceState(accepted)


def _result_from_operation(row, output_path: Path, status: SourceUpdateStatus, message: str) -> PrismaWorkflowResult:
    summary = json.loads(row["summary_json"] or "{}")
    get = lambda key: int(summary[key]) if key in summary else None
    return PrismaWorkflowResult(get("processed"), get("inserted"), get("updated"), get("unchanged"),
        get("filtered"), get("rejected"), (), output_path, status, message, get("audit_issues"))


def run_prisma_import_workflow(source_path: str | Path, *, source_date: date, evaluated_at: datetime,
        database_path: Path, state_path: Path, output_path: Path) -> PrismaWorkflowResult:
    detection = detect_csv_format(source_path)
    if detection.format is CsvFormat.MONITORING:
        raise PrismaWorkflowError(
            "Monitoring CSV cannot be imported as detailed PRISMA results. "
            "Use Load Monitoring CSV for live monitoring."
        )
    if detection.format is CsvFormat.AMBIGUOUS:
        raise PrismaWorkflowError("The CSV contract is ambiguous and cannot be imported safely.")
    if detection.format is not CsvFormat.PRISMA_EXPORT:
        raise PrismaWorkflowError(detection.message)

    storage = AuctionStorage(database_path)
    unresolved = storage.unresolved_operations()
    if any(row["source_date"] != source_date.isoformat() for row in unresolved):
        raise PrismaWorkflowError(
            "Another PRISMA source operation is unresolved. Retry that source before importing a new date."
        )
    captured: list[PrismaImportResult] = []
    def importer(path):
        result = import_prisma_export(path); captured.append(result); return result
    update = evaluate_prisma_source_update(source_path, source_date=source_date, evaluated_at=evaluated_at,
        prior_state=_state(storage, state_path), importer=importer)
    if update.status is SourceUpdateStatus.REJECTED:
        raise PrismaWorkflowError(update.message)
    try:
        operation = storage.begin_operation(source_date.isoformat(), update.source_name, update.sha256)
        if operation["status"] == "accepted":
            if not storage.validate_excel(output_path):
                storage.export_excel(output_path)
            return _result_from_operation(operation, output_path, SourceUpdateStatus.UNCHANGED,
                "Exact retry: the accepted PRISMA source and cumulative output are valid.")
        if operation["status"] == "pending":
            imported = captured[0] if captured else import_prisma_export(source_path)
            summary = {"total_source_rows": imported.total_source_rows,
                       "filtered": imported.filtered_count, "rejected": imported.rejected_count,
                       "audit_issues": len(imported.issues)}
            storage.apply_operation(operation["operation_id"], imported.rows, summary)
            operation = storage.operation_for_date(source_date.isoformat())
        storage.export_excel(output_path)
        storage.finalize_operation(operation["operation_id"])
        final = storage.operation_for_date(source_date.isoformat())
        result = _result_from_operation(final, output_path, update.status,
            "The PRISMA source was validated, published, and accepted.")
        return PrismaWorkflowResult(
            result.processed, result.inserted, result.updated, result.unchanged,
            result.filtered, result.rejected,
            tuple(captured[0].issues) if captured else (), output_path,
            result.source_status, result.message, result.audit_issue_count,
        )
    except (AuctionStorageError, sqlite3.Error, OSError) as exc:
        raise PrismaWorkflowError(str(exc)) from exc
