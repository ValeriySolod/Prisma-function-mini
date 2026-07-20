from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from csv_contracts import MONITORING_CSV_COLUMNS, PRISMA_EXPORT_COLUMNS, CsvFormatError
from processor import (
    PrismaImportError,
    PrismaImportStatus,
    import_prisma_export,
    process_csv,
)
from prisma_references import (
    PrismaReference,
    PrismaReferenceCatalog,
    ReferenceAlias,
    ReferenceClassification,
    ReferenceSide,
)

BASE = {
    "Auction ID": "000123456789012345", "Start of Auction": "01.01.2025 09:00",
    "Marketed Capacity": "1000", "Unit Marketed Capacity": "kWh/h",
    "Product Runtime Start": "02.01.2025 00:00", "Product Runtime End": "03.01.2025 00:00",
    "Direction": "Entry", "Network Point Name Entry": "VGS Storage Hub (4290)",
    "Network Point ID Entry": "ENTRY-ID", "Network Point Name Exit": "",
    "Network Point ID Exit": "EXIT-ID", "Network Point Name Exit/Entry": "Bundle point",
    "Network Point ID Exit/Entry": "BUNDLE-ID", "Regulated Tariff Exit TSO": "1,25",
    "Unit Regulated Exit Capacity Tariff": "cent/kWh/h/Runtime",
    "Regulated Tariff Entry TSO": "0.75",
    "Unit Regulated Entry Capacity Tariff": "cent/kWh/h/Runtime", "Surcharge": "0,5",
    "Unit Surcharge": "cent/kWh/h/Runtime",
}


def write_csv(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "Auction_overview.csv"
    pd.DataFrame(rows).reindex(columns=PRISMA_EXPORT_COLUMNS).fillna("").to_csv(
        path, sep=";", encoding="cp1252", index=False
    )
    return path


def test_detailed_result_classifies_every_row_and_preserves_id(tmp_path: Path) -> None:
    rows = [BASE, {**BASE, "Marketed Capacity": "999"}, {**BASE, "Direction": "sideways"}]
    result = import_prisma_export(write_csv(tmp_path, rows))
    assert (result.total_source_rows, result.imported_count, result.filtered_count, result.rejected_count) == (3, 1, 1, 1)
    assert result.total_source_rows == result.imported_count + result.filtered_count + result.rejected_count
    assert result.rows[0]["auction_id"] == "000123456789012345"
    assert [
        (issue.source_row_number, issue.status, issue.reason_code)
        for issue in result.issues
    ] == [
        (3, PrismaImportStatus.FILTERED, "capacity_below_threshold"),
        (4, PrismaImportStatus.REJECTED, "unsupported_direction"),
    ]
    for issue in result.issues:
        assert issue.message
        assert "000123456789012345" not in issue.message


@pytest.mark.parametrize(("direction", "normalized", "point", "point_id"), [
    ("Entry", "entry", "VGS Storage Hub (4290)", "ENTRY-ID"),
    ("Exit", "exit", "VGS Storage Hub (4290)", "EXIT-ID"),
    ("Exit/Entry", "bundle", "Bundle point", "BUNDLE-ID"),
])
def test_all_directions_select_their_own_network_point(tmp_path: Path, direction: str, normalized: str, point: str, point_id: str) -> None:
    source = {**BASE, "Direction": direction}
    if direction == "Entry":
        source["Network Point Name Exit"] = ""
    elif direction == "Exit":
        source["Network Point Name Exit"] = "VGS Storage Hub (4290)"
        source["Network Point Name Entry"] = ""
    else:
        source["Network Point Name Exit"] = "VGS Storage Hub (4290)"
        source["Network Point Name Entry"] = "VGS Storage Hub (4290)"
    row = process_csv(write_csv(tmp_path, [source]))[0]
    assert (row["direction"], row["network_point"], row["network_point_id"]) == (normalized, point, point_id)


@pytest.mark.parametrize(("direction", "field", "side"), [
    ("Entry", "Network Point ID Entry", "entry"),
    ("Exit", "Network Point ID Exit", "exit"),
    ("Exit/Entry", "Network Point ID Exit/Entry", None),
])
@pytest.mark.parametrize("source_value", ["", " \t "])
def test_blank_selected_network_point_id_is_audited(
    tmp_path: Path, direction: str, field: str, side: str | None, source_value: str
) -> None:
    source = {**BASE, "Direction": direction, field: source_value}
    if direction == "Exit":
        source["Network Point Name Exit"] = "VGS Storage Hub (4290)"
    result = import_prisma_export(write_csv(tmp_path, [source]))
    issue = result.issues[0]
    assert (result.imported_count, result.rejected_count) == (0, 1)
    assert (issue.reason_code, issue.message) == (
        "missing_network_point_id",
        "The selected network-point ID is empty.",
    )
    assert (issue.field_name, issue.side, issue.source_value) == (
        field,
        side,
        source_value,
    )


@pytest.mark.parametrize(("direction", "name_field", "id_field", "code"), [
    (
        "Entry",
        "Network Point Name Entry",
        "Network Point ID Entry",
        "missing_required_entry_reference",
    ),
    (
        "Exit",
        "Network Point Name Exit",
        "Network Point ID Exit",
        "missing_required_exit_reference",
    ),
    (
        "Exit/Entry",
        "Network Point Name Exit/Entry",
        "Network Point ID Exit/Entry",
        "missing_network_point",
    ),
])
def test_blank_selected_name_takes_precedence_over_blank_selected_id(
    tmp_path: Path, direction: str, name_field: str, id_field: str, code: str
) -> None:
    result = import_prisma_export(write_csv(tmp_path, [{
        **BASE,
        "Direction": direction,
        name_field: "",
        id_field: "",
    }]))

    issue = result.issues[0]
    assert issue.reason_code == code
    assert issue.field_name == name_field


def test_selected_network_point_id_preserves_valid_text(tmp_path: Path) -> None:
    row = process_csv(write_csv(tmp_path, [{
        **BASE, "Network Point ID Entry": "  000123-A  "
    }]))[0]
    assert row["network_point_id"] == "000123-A"


@pytest.mark.parametrize(("capacity", "unit", "expected"), [
    ("1000", "kWh/h", 1000.0), ("1", "MWh/h", 1000.0), ("24000", "kWh/d", 1000.0),
])
def test_capacity_conversions_and_exact_threshold(tmp_path: Path, capacity: str, unit: str, expected: float) -> None:
    row = process_csv(write_csv(tmp_path, [{**BASE, "Marketed Capacity": capacity, "Unit Marketed Capacity": unit}]))[0]
    assert row["booked_capacity_kwh_h"] == expected


@pytest.mark.parametrize(("capacity", "unit", "status"), [
    ("999", "kWh/h", PrismaImportStatus.FILTERED),
    ("", "kWh/h", PrismaImportStatus.REJECTED), ("bad", "kWh/h", PrismaImportStatus.REJECTED),
    ("-1", "kWh/h", PrismaImportStatus.REJECTED), ("NaN", "kWh/h", PrismaImportStatus.REJECTED),
    ("Infinity", "kWh/h", PrismaImportStatus.REJECTED), ("1000", "therms", PrismaImportStatus.REJECTED),
])
def test_invalid_capacity_is_explicit(tmp_path: Path, capacity: str, unit: str, status: PrismaImportStatus) -> None:
    result = import_prisma_export(write_csv(tmp_path, [{**BASE, "Marketed Capacity": capacity, "Unit Marketed Capacity": unit}]))
    assert result.rows == [] and result.issues[0].status is status


@pytest.mark.parametrize(("start", "duration", "expected"), [
    (datetime(2025, 1, 1, 10), timedelta(hours=24), "WD"),
    (datetime(2025, 1, 2), timedelta(hours=24), "Day Ahead"),
    (datetime(2025, 1, 2), timedelta(days=31), "Month"),
    (datetime(2025, 1, 2), timedelta(days=31, minutes=1), "Quarter"),
    (datetime(2025, 1, 2), timedelta(days=93), "Quarter"),
    (datetime(2025, 1, 2), timedelta(days=93, minutes=1), "Year"),
])
def test_product_type_boundaries(tmp_path: Path, start: datetime, duration: timedelta, expected: str) -> None:
    row = {**BASE, "Product Runtime Start": start.strftime("%d.%m.%Y %H:%M"), "Product Runtime End": (start + duration).strftime("%d.%m.%Y %H:%M")}
    assert process_csv(write_csv(tmp_path, [row]))[0]["product_type"] == expected


@pytest.mark.parametrize(("field", "value"), [
    ("Product Runtime Start", "1.01.2025 00:00"), ("Product Runtime End", "invalid"),
    ("Product Runtime End", "02.01.2025 00:00"), ("Product Runtime End", "01.01.2025 23:59"),
])
def test_strict_dates_and_positive_runtime(tmp_path: Path, field: str, value: str) -> None:
    result = import_prisma_export(write_csv(tmp_path, [{**BASE, field: value}]))
    assert result.rejected_count == 1


def test_flow_before_auction_calendar_date_is_rejected(tmp_path: Path) -> None:
    row = {
        **BASE,
        "Product Runtime Start": "31.12.2024 23:00",
        "Product Runtime End": "01.01.2025 01:00",
    }
    result = import_prisma_export(write_csv(tmp_path, [row]))
    assert result.issues[0].reason_code == "flow_before_auction_date"
    assert result.issues[0].message == (
        "Product flow starts on a calendar date before the auction date."
    )


@pytest.mark.parametrize(("unit", "factor"), [("cent/kWh/h/Runtime", 10), ("cent/kWh/d/Runtime", 10 / 24)])
def test_tariff_and_surcharge_conversions(tmp_path: Path, unit: str, factor: float) -> None:
    row = {**BASE, "Regulated Tariff Exit TSO": "1", "Unit Regulated Exit Capacity Tariff": unit,
           "Regulated Tariff Entry TSO": "2", "Unit Regulated Entry Capacity Tariff": unit,
           "Surcharge": "3", "Unit Surcharge": unit}
    result = process_csv(write_csv(tmp_path, [row]))[0]
    assert result["tariff_eur_mwh_h"] == pytest.approx(3 * factor)
    assert result["premium_eur_mwh_h"] == pytest.approx(3 * factor)


def test_empty_price_unit_pairs_are_zero(tmp_path: Path) -> None:
    row = {**BASE, "Regulated Tariff Exit TSO": "", "Unit Regulated Exit Capacity Tariff": "",
           "Regulated Tariff Entry TSO": "", "Unit Regulated Entry Capacity Tariff": "",
           "Surcharge": "", "Unit Surcharge": ""}
    result = process_csv(write_csv(tmp_path, [row]))[0]
    assert (result["tariff_eur_mwh_h"], result["premium_eur_mwh_h"]) == (0, 0)


def test_empty_price_with_present_unit_has_auditable_rejection(tmp_path: Path) -> None:
    row = {**BASE, "Surcharge": "", "Unit Surcharge": "cent/kWh/h/Runtime"}
    result = import_prisma_export(write_csv(tmp_path, [row]))
    issue = result.issues[0]
    assert (issue.source_row_number, issue.status, issue.reason_code) == (
        2,
        PrismaImportStatus.REJECTED,
        "empty_surcharge",
    )
    assert issue.message == "Surcharge is empty while its unit is present."


@pytest.mark.parametrize(("value", "unit"), [
    ("1", "pence/kWh/h/Runtime"), ("1", "halér/kWh/h/Runtime"), ("1", ""),
    ("bad", "cent/kWh/h/Runtime"), ("-1", "cent/kWh/h/Runtime"),
    ("NaN", "cent/kWh/h/Runtime"), ("Infinity", "cent/kWh/h/Runtime"),
])
def test_invalid_or_unsupported_price_is_rejected(tmp_path: Path, value: str, unit: str) -> None:
    row = {**BASE, "Surcharge": value, "Unit Surcharge": unit}
    assert import_prisma_export(write_csv(tmp_path, [row])).rejected_count == 1


def test_bad_rows_are_isolated_without_loss(tmp_path: Path) -> None:
    bad = {**BASE, "Auction ID": "bad", "Product Runtime Start": "not a date"}
    result = import_prisma_export(write_csv(tmp_path, [bad, BASE, BASE]))
    assert result.total_source_rows == 3 and result.imported_count == 2 and result.rejected_count == 1


def test_missing_auction_id_has_stable_audit_issue(tmp_path: Path) -> None:
    result = import_prisma_export(write_csv(tmp_path, [{**BASE, "Auction ID": ""}]))
    issue = result.issues[0]
    assert (issue.source_row_number, issue.reason_code, issue.message) == (
        2,
        "missing_auction_id",
        "Auction ID is empty.",
    )


def test_blank_unknown_direction_and_missing_selected_name_are_rejected(tmp_path: Path) -> None:
    rows = [{**BASE, "Direction": ""}, {**BASE, "Direction": "Other"}, {**BASE, "Network Point Name Entry": ""}]
    assert import_prisma_export(write_csv(tmp_path, rows)).rejected_count == 3


def test_header_only_export(tmp_path: Path) -> None:
    result = import_prisma_export(write_csv(tmp_path, []))
    assert (result.rows, result.total_source_rows, result.imported_count, result.filtered_count, result.rejected_count, result.issues) == ([], 0, 0, 0, 0, [])


@pytest.mark.parametrize("field_delta", [-1, 1])
def test_invalid_column_count_is_rejected_and_counted(
    tmp_path: Path, field_delta: int
) -> None:
    path = write_csv(tmp_path, [BASE])
    lines = path.read_text(encoding="cp1252").splitlines()
    fields = next(csv.reader([lines[1]], delimiter=";"))
    if field_delta < 0:
        fields.pop()
    else:
        fields.append("unexpected")
    with path.open("a", encoding="cp1252", newline="") as csv_file:
        csv.writer(csv_file, delimiter=";", lineterminator="\n").writerow(fields)

    result = import_prisma_export(path)
    issue = result.issues[0]
    assert (result.total_source_rows, result.imported_count, result.rejected_count) == (
        2,
        1,
        1,
    )
    assert result.total_source_rows == (
        result.imported_count + result.filtered_count + result.rejected_count
    )
    assert (issue.source_row_number, issue.reason_code) == (3, "invalid_column_count")
    assert f"{len(PRISMA_EXPORT_COLUMNS) + field_delta} fields" in issue.message
    assert f"expected {len(PRISMA_EXPORT_COLUMNS)}" in issue.message


def test_embedded_newline_uses_record_starting_physical_line(tmp_path: Path) -> None:
    path = write_csv(tmp_path, [{**BASE, "Network Point Name Entry": "München\nSouth"}])
    with path.open("a", encoding="cp1252", newline="") as csv_file:
        csv.writer(csv_file, delimiter=";", lineterminator="\n").writerow(["too", "few"])
    catalog = PrismaReferenceCatalog((PrismaReference(
        "München South", ReferenceClassification.MARKET,
        (ReferenceAlias("München\nSouth", ReferenceSide.ENTRY),),
    ),))
    result = import_prisma_export(path, reference_catalog=catalog)
    assert result.rows[0]["network_point"] == "München\nSouth"
    assert result.issues[0].source_row_number == 4


def test_unrecoverable_csv_error_raises_clear_import_error(tmp_path: Path) -> None:
    path = write_csv(tmp_path, [])
    with path.open("a", encoding="cp1252", newline="") as csv_file:
        csv_file.write('"unterminated')
    with pytest.raises(
        PrismaImportError,
        match=r"could not be parsed safely at physical line 2:.*No partial result",
    ):
        import_prisma_export(path)


def test_incomplete_header_is_rejected_at_processor_boundary(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.csv"
    columns = [column for column in PRISMA_EXPORT_COLUMNS if column != "Direction"]
    pd.DataFrame([BASE]).reindex(columns=columns).to_csv(
        path, sep=";", encoding="cp1252", index=False
    )
    with pytest.raises(
        CsvFormatError,
        match="PRISMA Export CSV header is incomplete; missing columns: Direction",
    ):
        import_prisma_export(path)


def test_wrong_csv_contract_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "monitoring.csv"
    path.write_text(",".join(MONITORING_CSV_COLUMNS) + "\n", encoding="utf-8")
    with pytest.raises(CsvFormatError, match="detected monitoring"):
        import_prisma_export(path)


def test_process_csv_compatibility_and_output_keys(tmp_path: Path) -> None:
    result = process_csv(write_csv(tmp_path, [BASE]))
    assert isinstance(result, list) and isinstance(result[0], dict)
    assert set(result[0]) == {"auction_id", "auction_date", "exit_market", "entry_market", "direction", "network_point", "network_point_id", "tso_exit", "tso_entry", "product_type", "flow_start", "flow_end", "booked_capacity_kwh_h", "runtime_hours", "tariff_eur_mwh_h", "premium_eur_mwh_h", "state"}


def test_cp1252_text_iso_dates_and_numeric_prices_are_preserved(tmp_path: Path) -> None:
    catalog = PrismaReferenceCatalog((PrismaReference(
        "München", ReferenceClassification.MARKET,
        (ReferenceAlias("München", ReferenceSide.ENTRY),),
    ),))
    row = import_prisma_export(
        write_csv(tmp_path, [{**BASE, "Network Point Name Entry": "München"}]),
        reference_catalog=catalog,
    ).rows[0]
    assert row["network_point"] == "München"
    assert (row["auction_date"], row["flow_start"], row["flow_end"]) == (
        "2025-01-01T09:00:00",
        "2025-01-02T00:00:00",
        "2025-01-03T00:00:00",
    )
    assert row["tariff_eur_mwh_h"] == 20.0
    assert row["premium_eur_mwh_h"] == 5.0
    assert isinstance(row["tariff_eur_mwh_h"], float)
    assert isinstance(row["premium_eur_mwh_h"], float)
