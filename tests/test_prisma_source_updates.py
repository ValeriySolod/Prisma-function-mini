from dataclasses import FrozenInstanceError
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from csv_contracts import PRISMA_EXPORT_COLUMNS
from prisma_source_updates import (
    AcceptedPrismaSource,
    PrismaSourceState,
    PrismaSourceUpdateResult,
    SourceUpdateReason,
    SourceUpdateStatus,
    evaluate_prisma_source_update,
    is_daily_source_update_due,
)


DAY = date(2026, 7, 17)
NOW = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)


def write_export(path: Path, body: bytes = b"") -> Path:
    path.write_bytes(";".join(PRISMA_EXPORT_COLUMNS).encode("cp1252") + b"\r\n" + body)
    return path


def counts(total=0, imported=0, filtered=0, rejected=0):
    return SimpleNamespace(
        total_source_rows=total,
        imported_count=imported,
        filtered_count=filtered,
        rejected_count=rejected,
    )


def evaluate(path, *, day=DAY, state=None, importer=lambda path: counts()):
    return evaluate_prisma_source_update(
        path, source_date=day, evaluated_at=NOW, prior_state=state, importer=importer
    )


def test_first_and_newer_sources_apply(tmp_path):
    first = evaluate(write_export(tmp_path / "first.csv"))
    write_export(tmp_path / "second.csv", b"different")
    # Use an evaluation date that permits the newer source.
    second = evaluate_prisma_source_update(
        tmp_path / "second.csv", source_date=DAY + timedelta(days=1),
        evaluated_at=NOW + timedelta(days=1), prior_state=first.accepted_state,
        importer=lambda path: counts(2, 1, 1, 0),
    )
    assert first.status is SourceUpdateStatus.APPLIED
    assert second.status is SourceUpdateStatus.APPLIED
    assert second.accepted_state.latest_source_date == DAY + timedelta(days=1)
    assert (second.total_count, second.imported_count, second.filtered_count, second.rejected_count) == (2, 1, 1, 0)


def test_exact_retry_is_unchanged_without_import(tmp_path):
    path = write_export(tmp_path / "daily.csv")
    first = evaluate(path)
    calls = 0

    def forbidden(path):
        nonlocal calls
        calls += 1
        raise AssertionError

    retry = evaluate(path, state=first.accepted_state, importer=forbidden)
    assert retry.status is SourceUpdateStatus.UNCHANGED
    assert retry.reason is SourceUpdateReason.IDENTICAL_SOURCE
    assert retry.accepted_state is first.accepted_state
    assert calls == 0


def test_conflict_stale_and_future_are_rejected_without_import(tmp_path):
    first_path = write_export(tmp_path / "first.csv")
    first = evaluate(first_path)
    changed = write_export(tmp_path / "changed.csv", b"changed")
    forbidden = lambda path: pytest.fail("importer must not run")
    conflict = evaluate(changed, state=first.accepted_state, importer=forbidden)
    stale = evaluate(changed, day=DAY - timedelta(days=1), state=first.accepted_state, importer=forbidden)
    future = evaluate_prisma_source_update(
        changed, source_date=DAY + timedelta(days=1), evaluated_at=NOW,
        prior_state=first.accepted_state, importer=forbidden,
    )
    assert conflict.reason is SourceUpdateReason.CONFLICTING_SOURCE
    assert stale.reason is SourceUpdateReason.STALE_SOURCE_DATE
    assert future.reason is SourceUpdateReason.FUTURE_SOURCE_DATE
    assert all(item.status is SourceUpdateStatus.REJECTED for item in (conflict, stale, future))


def test_fatal_validation_failure_leaves_state_unchanged(tmp_path):
    path = write_export(tmp_path / "bad.csv")
    state = PrismaSourceState()

    def fail(path):
        raise RuntimeError("private row and path details")

    result = evaluate(path, state=state, importer=fail)
    assert result.reason is SourceUpdateReason.INVALID_SOURCE
    assert result.accepted_state is state
    assert result.total_count is None
    assert "private" not in result.message


def test_source_changed_during_import_is_rejected_without_counts(tmp_path):
    path = write_export(tmp_path / "changing.csv")
    state = PrismaSourceState()

    def change_source(import_path):
        Path(import_path).write_bytes(b"changed while importing")
        return counts(1, 1, 0, 0)

    result = evaluate(path, state=state, importer=change_source)
    assert result.status is SourceUpdateStatus.REJECTED
    assert result.reason is SourceUpdateReason.INVALID_SOURCE
    assert result.accepted_state is state
    assert (result.total_count, result.imported_count, result.filtered_count, result.rejected_count) == (None, None, None, None)


def test_source_disappearing_during_import_is_rejected_without_counts(tmp_path):
    path = write_export(tmp_path / "vanishing.csv")
    state = PrismaSourceState()

    def remove_source(import_path):
        Path(import_path).unlink()
        return counts(1, 1, 0, 0)

    result = evaluate(path, state=state, importer=remove_source)
    assert result.reason is SourceUpdateReason.INVALID_SOURCE
    assert result.accepted_state is state
    assert result.total_count is result.imported_count is result.filtered_count is result.rejected_count is None


def test_row_outcomes_and_header_only_are_valid_lifecycle_results(tmp_path):
    outcomes = evaluate(
        write_export(tmp_path / "outcomes.csv"),
        importer=lambda path: counts(5, 2, 1, 2),
    )
    header_only = evaluate_prisma_source_update(
        write_export(tmp_path / "empty.csv"), source_date=DAY + timedelta(days=1),
        evaluated_at=NOW + timedelta(days=1), prior_state=outcomes.accepted_state,
    )
    assert outcomes.status is SourceUpdateStatus.APPLIED
    assert (outcomes.imported_count, outcomes.filtered_count, outcomes.rejected_count) == (2, 1, 2)
    assert header_only.status is SourceUpdateStatus.APPLIED
    assert header_only.total_count == header_only.imported_count == 0


def test_digest_uses_exact_bytes_and_metadata_has_basename_only(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    path = write_export(nested / "one.csv", b"\x80\r\n")
    result = evaluate(path)
    assert result.sha256 == sha256(path.read_bytes()).hexdigest()
    assert result.source_name == "one.csv"
    assert str(nested) not in repr(result)
    changed = write_export(nested / "two.csv", b"\x80\n")
    assert sha256(changed.read_bytes()).hexdigest() != result.sha256


def test_invalid_public_inputs_and_inconsistent_state(tmp_path):
    path = write_export(tmp_path / "valid.csv")
    with pytest.raises(TypeError, match="exactly datetime.date"):
        evaluate_prisma_source_update(path, source_date=NOW, evaluated_at=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_prisma_source_update(path, source_date=DAY, evaluated_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="regular file") as missing:
        evaluate_prisma_source_update(tmp_path / "secret" / "missing.csv", source_date=DAY, evaluated_at=NOW)
    assert str(tmp_path) not in str(missing.value)
    with pytest.raises(ValueError, match="regular file"):
        evaluate_prisma_source_update(tmp_path, source_date=DAY, evaluated_at=NOW)
    accepted = AcceptedPrismaSource(DAY, "one.csv", "0" * 64)
    with pytest.raises(ValueError, match="unique source dates"):
        PrismaSourceState((accepted, accepted))


def test_state_and_result_are_immutable_and_repeated_evaluation_is_deterministic(tmp_path):
    path = write_export(tmp_path / "daily.csv")
    first = evaluate(path)
    second = evaluate(path)
    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.status = SourceUpdateStatus.REJECTED
    with pytest.raises(FrozenInstanceError):
        first.accepted_state.accepted_sources = ()


def make_result(**overrides):
    values = dict(
        source_date=DAY,
        source_name="daily.csv",
        sha256="a" * 64,
        evaluated_at=NOW,
        status=SourceUpdateStatus.APPLIED,
        reason=SourceUpdateReason.APPLIED,
        message="The PRISMA source was validated and accepted.",
        accepted_state=PrismaSourceState((AcceptedPrismaSource(DAY, "daily.csv", "a" * 64),)),
        total_count=0,
        imported_count=0,
        filtered_count=0,
        rejected_count=0,
    )
    values.update(overrides)
    return PrismaSourceUpdateResult(**values)


@pytest.mark.parametrize("field,value,match", [
    ("source_name", "folder/daily.csv", "basename"),
    ("sha256", "A" * 64, "lowercase hexadecimal"),
    ("evaluated_at", NOW.replace(tzinfo=None), "timezone-aware"),
])
def test_result_rejects_invalid_identity_fields(field, value, match):
    with pytest.raises(ValueError, match=match):
        make_result(**{field: value})


def test_result_rejects_invalid_status_reason_pair():
    with pytest.raises(ValueError, match="status and reason"):
        make_result(reason=SourceUpdateReason.INVALID_SOURCE)


@pytest.mark.parametrize("changes,match", [
    ({"rejected_count": None}, "all present"),
    ({"rejected_count": -1}, "non-negative"),
    ({"total_count": 1}, "inconsistent"),
])
def test_result_rejects_invalid_counts(changes, match):
    with pytest.raises(ValueError, match=match):
        make_result(**changes)


def test_result_rejects_inconsistent_applied_and_unchanged_state():
    empty = PrismaSourceState()
    with pytest.raises(ValueError, match="matching accepted source"):
        make_result(accepted_state=empty)
    with pytest.raises(ValueError, match="matching accepted"):
        make_result(
            status=SourceUpdateStatus.UNCHANGED,
            reason=SourceUpdateReason.IDENTICAL_SOURCE,
            message="This exact PRISMA source was already accepted.",
            accepted_state=empty,
            total_count=None, imported_count=None, filtered_count=None, rejected_count=None,
        )


def test_daily_due_policy_before_after_acceptance_and_offsets():
    schedule = time(9, 30)
    plus_two = timezone(timedelta(hours=2))
    before = datetime(2026, 7, 17, 9, 29, tzinfo=plus_two)
    after = datetime(2026, 7, 17, 9, 30, tzinfo=plus_two)
    assert not is_daily_source_update_due(DAY, evaluated_at=before, scheduled_local_time=schedule)
    assert is_daily_source_update_due(DAY, evaluated_at=after, scheduled_local_time=schedule)
    accepted = PrismaSourceState((AcceptedPrismaSource(DAY, "daily.csv", "a" * 64),))
    assert not is_daily_source_update_due(
        DAY, evaluated_at=after, scheduled_local_time=schedule, accepted_state=accepted
    )
    later_accepted = PrismaSourceState((AcceptedPrismaSource(DAY + timedelta(days=1), "later.csv", "b" * 64),))
    assert not is_daily_source_update_due(
        DAY, evaluated_at=after, scheduled_local_time=schedule, accepted_state=later_accepted
    )
    minus_five = timezone(timedelta(hours=-5))
    assert is_daily_source_update_due(
        DAY, evaluated_at=datetime(2026, 7, 17, 10, tzinfo=minus_five),
        scheduled_local_time=schedule,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        is_daily_source_update_due(DAY, evaluated_at=after.replace(tzinfo=None), scheduled_local_time=schedule)
