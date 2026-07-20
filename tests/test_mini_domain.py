from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mini_domain import (
    OUTPUT_COLUMNS,
    WORKSHEET_NAME,
    AuctionDuplicateKey,
    CapacityType,
    HistoryRecord,
    ImportResult,
    MiniDateRange,
    MiniOutputRow,
    NormalizedAuctionRecord,
    ProcessingResult,
    ProcessingStatus,
    ProductType,
    SourceImportRequest,
    ValidationFailure,
    ValidationReason,
    classify_duplicates,
    normalize_capacity,
    normalize_product,
    normalize_tariff,
)


SHA = "a" * 64


def record(**changes) -> NormalizedAuctionRecord:
    values = {
        "auction_id": " A-1 ",
        "network_point_id": " NP-1 ",
        "auction_date": date(2026, 7, 20),
        "exit_market_or_storage": " Exit Market ",
        "entry_market_or_storage": " Entry Storage ",
        "capacity_type": CapacityType.BUNDLE,
        "network_point": " Test   Point ",
        "product_type": ProductType.DAY_AHEAD,
        "flow_start": datetime(2026, 7, 21, 6, 0),
        "flow_end": datetime(2026, 7, 22, 6, 0),
        "booked_capacity_kwh_h": "1000.00",
        "duration_hours": "24.0",
        "auction_tariff_eur_mwh_h": "1.2500",
    }
    values.update(changes)
    return NormalizedAuctionRecord(**values)


def test_date_range_is_inclusive_immutable_and_validated():
    same_day = MiniDateRange(date(2026, 7, 20), date(2026, 7, 20))
    assert same_day.start == same_day.end
    with pytest.raises(FrozenInstanceError):
        same_day.start = date(2026, 7, 19)
    with pytest.raises(ValueError, match="on or after"):
        MiniDateRange(date(2026, 7, 21), date(2026, 7, 20))
    with pytest.raises(TypeError, match="exactly"):
        MiniDateRange(datetime(2026, 7, 20), date(2026, 7, 20))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source_name": "folder/file.csv"}, "basename"),
        ({"sha256": "A" * 64}, "lowercase"),
        ({"size_bytes": 0}, "positive"),
        ({"requested_range": "bad"}, "MiniDateRange"),
    ],
)
def test_source_import_request_contract(changes, message):
    values = dict(
        requested_range=MiniDateRange(date(2026, 7, 1), date(2026, 7, 2)),
        source_name="Auction_overview.csv", sha256=SHA, size_bytes=42,
    )
    values.update(changes)
    with pytest.raises((TypeError, ValueError), match=message):
        SourceImportRequest(**values)


def test_normalized_record_normalizes_text_decimals_and_builds_stable_key():
    item = record()
    assert (item.auction_id, item.network_point_id, item.network_point) == ("A-1", "NP-1", "Test Point")
    assert (item.booked_capacity_kwh_h, item.duration_hours, item.auction_tariff_eur_mwh_h) == (
        Decimal("1E+3"), Decimal("24"), Decimal("1.25")
    )
    assert item.duplicate_key == AuctionDuplicateKey(
        "A-1", "NP-1", CapacityType.BUNDLE,
        datetime(2026, 7, 21, 6), datetime(2026, 7, 22, 6),
    )
    assert not hasattr(item.duplicate_key, "network_point")


@pytest.mark.parametrize("field", ["auction_id", "network_point_id", "network_point"])
def test_required_identity_and_display_text_reject_blank(field):
    with pytest.raises(ValueError, match="blank"):
        record(**{field: "  "})


@pytest.mark.parametrize(
    ("capacity_type", "exit_value", "entry_value"),
    [
        (CapacityType.ENTRY, None, "Entry"),
        (CapacityType.EXIT, "Exit", None),
        (CapacityType.BUNDLE, "Exit", "Entry"),
    ],
)
def test_capacity_type_requires_only_authoritative_sides(capacity_type, exit_value, entry_value):
    item = record(capacity_type=capacity_type, exit_market_or_storage=exit_value,
                  entry_market_or_storage=entry_value)
    assert item.capacity_type is capacity_type


@pytest.mark.parametrize(
    "changes",
    [
        {"capacity_type": CapacityType.ENTRY, "entry_market_or_storage": None},
        {"capacity_type": CapacityType.EXIT, "exit_market_or_storage": None},
        {"capacity_type": CapacityType.BUNDLE, "exit_market_or_storage": None},
        {"capacity_type": CapacityType.BUNDLE, "entry_market_or_storage": None},
    ],
)
def test_missing_required_authoritative_side_fails_closed(changes):
    with pytest.raises(ValueError, match="authoritative"):
        record(**changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"flow_start": datetime(2026, 7, 21, 6, tzinfo=timezone.utc)}, "timezone-naive"),
        ({"flow_start": datetime(2026, 7, 21, 6, 0, 1)}, "minute precision"),
        ({"flow_end": datetime(2026, 7, 21, 6)}, "later"),
        ({"auction_date": date(2026, 7, 22)}, "after"),
        ({"duration_hours": 23}, "exact"),
        ({"booked_capacity_kwh_h": "999.999"}, "at least 1000"),
        ({"auction_tariff_eur_mwh_h": "NaN"}, "finite"),
        ({"capacity_type": "Bundle"}, "CapacityType"),
        ({"product_type": "Day Ahead"}, "ProductType"),
    ],
)
def test_normalized_record_validation_constraints(changes, message):
    with pytest.raises((TypeError, ValueError), match=message):
        record(**changes)


def test_authoritative_output_contract_order_types_and_no_identity_columns():
    assert WORKSHEET_NAME == "Auctions"
    assert OUTPUT_COLUMNS == (
        "Auction Date", "Exit Market / Storage", "Entry Market / Storage",
        "Capacity Type", "Network Point", "Product Type", "Flow Start",
        "Flow End", "Booked Capacity (kWh/h)", "Duration (hours)",
        "Auction Tariff (EUR/MWh/h)",
    )
    output = MiniOutputRow.from_record(record())
    assert len(output.values()) == len(OUTPUT_COLUMNS) == 11
    assert output.values() == (
        date(2026, 7, 20), "Exit Market", "Entry Storage", "Bundle",
        "Test Point", "Day Ahead", datetime(2026, 7, 21, 6),
        datetime(2026, 7, 22, 6), Decimal("1E+3"), Decimal("24"), Decimal("1.25"),
    )


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("1000", "kWh/h", Decimal("1E+3")),
        ("1", "MWh/h", Decimal("1E+3")),
        ("24000", "kWh/d", Decimal("1E+3")),
    ],
)
def test_supported_capacity_normalization(value, unit, expected):
    assert normalize_capacity(value, unit) == expected


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("1.25", "EUR/MWh/h", Decimal("1.25")),
        ("1", "cent/kWh/h/Runtime", Decimal("1E+1")),
        ("24", "cent/kWh/d/Runtime", Decimal("1E+1")),
    ],
)
def test_supported_tariff_normalization(value, unit, expected):
    assert normalize_tariff(value, unit) == expected


@pytest.mark.parametrize("normalizer", [normalize_capacity, normalize_tariff])
def test_unit_normalizers_reject_unsupported_nonfinite_and_negative(normalizer):
    with pytest.raises(ValueError, match="Unsupported"):
        normalizer("1", "therms")
    with pytest.raises(ValueError, match="finite"):
        normalizer("Infinity", next(iter({"kWh/h"} if normalizer is normalize_capacity else {"EUR/MWh/h"})))
    with pytest.raises(ValueError, match="finite"):
        normalizer("-1", next(iter({"kWh/h"} if normalizer is normalize_capacity else {"EUR/MWh/h"})))


@pytest.mark.parametrize(
    ("source", "expected"),
    [("WD", ProductType.WITHIN_DAY), ("Within Day", ProductType.WITHIN_DAY),
     ("Day Ahead", ProductType.DAY_AHEAD), ("Month", ProductType.MONTH),
     ("Quarter", ProductType.QUARTER), ("Year", ProductType.YEAR)],
)
def test_product_normalization_is_explicit(source, expected):
    assert normalize_product(source) is expected


def test_product_normalization_does_not_use_fuzzy_matching():
    with pytest.raises(ValueError, match="Unsupported"):
        normalize_product("monthly")


def test_duplicate_classification_preserves_history_and_handles_batch_repeats():
    historical = record()
    new_record = record(auction_id="A-2")
    new, duplicates = classify_duplicates([historical], [historical, new_record, new_record])
    assert new == (new_record,)
    assert duplicates == (historical, new_record)


def test_same_key_with_changed_payload_fails_closed():
    existing = record()
    conflict = record(auction_tariff_eur_mwh_h="2")
    with pytest.raises(ValueError, match="conflicts"):
        classify_duplicates([existing], [conflict])


def test_key_changes_only_for_one_of_five_stable_identity_fields():
    original = record()
    assert record(network_point="Renamed display").duplicate_key == original.duplicate_key
    assert record(auction_tariff_eur_mwh_h="2").duplicate_key == original.duplicate_key
    for changed in (
        record(auction_id="A-2"), record(network_point_id="NP-2"),
        record(capacity_type=CapacityType.ENTRY, exit_market_or_storage=None),
        record(flow_start=datetime(2026, 7, 21, 5), duration_hours=25),
        record(flow_end=datetime(2026, 7, 22, 7), duration_hours=25),
    ):
        assert changed.duplicate_key != original.duplicate_key


def test_history_record_preserves_record_source_and_utc_audit_time():
    auction = record()
    item = HistoryRecord(auction, SHA, datetime(2026, 7, 20, 14, tzinfo=timezone(timedelta(hours=2))))
    assert item.auction is auction
    assert item.duplicate_key == auction.duplicate_key
    assert item.accumulated_at == datetime(2026, 7, 20, 12, tzinfo=timezone.utc)


def test_validation_failure_has_stable_reason_and_source_context():
    failure = ValidationFailure(ValidationReason.INVALID_VALUE, " Bad value ", 2, " Capacity ")
    assert (failure.reason.value, failure.message, failure.source_row_number, failure.field_name) == (
        "invalid_value", "Bad value", 2, "Capacity"
    )
    with pytest.raises(ValueError, match="2 or greater"):
        ValidationFailure(ValidationReason.INVALID_VALUE, "bad", 1)


def test_processing_and_import_results_validate_counts_failures_and_utc():
    failure = ValidationFailure(ValidationReason.INVALID_SOURCE_ROW, "row rejected", 2)
    processing = ProcessingResult(ProcessingStatus.COMPLETED, 4, 1, 1, 1, 1, (failure,))
    request = SourceImportRequest(MiniDateRange(date(2026, 7, 1), date(2026, 7, 2)), "a.csv", SHA, 1)
    result = ImportResult(request, datetime(2026, 7, 20, 15, tzinfo=timezone(timedelta(hours=3))), processing)
    assert result.evaluated_at == datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="must equal"):
        ProcessingResult(ProcessingStatus.COMPLETED, 2, 1, 0, 0, 0)
    with pytest.raises(ValueError, match="at least one"):
        ProcessingResult(ProcessingStatus.FAILED, 0, 0, 0, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        ImportResult(request, datetime(2026, 7, 20, 12), processing)
