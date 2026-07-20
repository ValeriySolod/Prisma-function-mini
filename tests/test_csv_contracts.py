from __future__ import annotations

import csv

import pytest

from csv_contracts import (
    MONITORING_CSV_COLUMNS,
    PRISMA_EXPORT_COLUMNS,
    CsvFormat,
    CsvFormatError,
    detect_csv_format,
    require_csv_format,
)


def write_header(tmp_path, columns, *, delimiter=",", encoding="utf-8"):
    path = tmp_path / "input.csv"
    with path.open("w", encoding=encoding, newline="") as csv_file:
        csv.writer(csv_file, delimiter=delimiter).writerow(columns)
    return path


def test_detects_utf8_monitoring_csv(tmp_path):
    result = detect_csv_format(write_header(tmp_path, MONITORING_CSV_COLUMNS))
    assert result.format is CsvFormat.MONITORING


def test_detects_cp1252_prisma_export_csv(tmp_path):
    path = write_header(
        tmp_path, PRISMA_EXPORT_COLUMNS, delimiter=";", encoding="cp1252"
    )
    assert detect_csv_format(path).format is CsvFormat.PRISMA_EXPORT


@pytest.mark.parametrize(
    ("columns", "delimiter"),
    [(MONITORING_CSV_COLUMNS, ";"), (PRISMA_EXPORT_COLUMNS, ",")],
)
def test_incorrect_delimiter_is_unsupported(tmp_path, columns, delimiter):
    result = detect_csv_format(write_header(tmp_path, columns, delimiter=delimiter))
    assert result.format is CsvFormat.UNSUPPORTED
    assert "Unsupported CSV format" in result.message


@pytest.mark.parametrize(
    ("columns", "delimiter", "duplicate"),
    [
        (MONITORING_CSV_COLUMNS + ("auction_id",), ",", "auction_id"),
        (PRISMA_EXPORT_COLUMNS + ("Auction ID",), ";", "Auction ID"),
    ],
)
def test_duplicate_headers_are_rejected(tmp_path, columns, delimiter, duplicate):
    result = detect_csv_format(write_header(tmp_path, columns, delimiter=delimiter))
    assert result.format is CsvFormat.UNSUPPORTED
    assert result.message == f"CSV header contains duplicate column: {duplicate}."


def test_partial_monitoring_header_is_not_detected(tmp_path):
    result = detect_csv_format(write_header(tmp_path, MONITORING_CSV_COLUMNS[:-1]))
    assert result.format is CsvFormat.UNSUPPORTED
    assert "Monitoring CSV header is incomplete; missing columns: enabled." == result.message


def test_partial_prisma_header_is_not_detected(tmp_path):
    result = detect_csv_format(
        write_header(tmp_path, PRISMA_EXPORT_COLUMNS[:-1], delimiter=";")
    )
    assert result.format is CsvFormat.UNSUPPORTED
    assert "PRISMA Export CSV header is incomplete; missing columns: State." == result.message


def test_unknown_csv_format_has_specific_error(tmp_path):
    result = detect_csv_format(write_header(tmp_path, ("name", "value")))
    assert result.format is CsvFormat.UNSUPPORTED
    assert result.message.startswith("Unsupported CSV format.")


def test_empty_file_is_unsupported(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    result = detect_csv_format(path)
    assert result == type(result)(CsvFormat.UNSUPPORTED, "CSV file is empty.")


def test_header_only_file_can_be_detected(tmp_path):
    path = write_header(tmp_path, MONITORING_CSV_COLUMNS)
    assert detect_csv_format(path).format is CsvFormat.MONITORING


@pytest.mark.parametrize(
    ("columns", "delimiter", "encoding"),
    [
        (MONITORING_CSV_COLUMNS, ",", "utf-8-sig"),
        (PRISMA_EXPORT_COLUMNS, ";", "utf-8-sig"),
    ],
)
def test_bom_is_not_part_of_either_confirmed_contract(
    tmp_path, columns, delimiter, encoding
):
    result = detect_csv_format(
        write_header(tmp_path, columns, delimiter=delimiter, encoding=encoding)
    )
    assert result.format is CsvFormat.UNSUPPORTED


def test_valid_contract_of_wrong_kind_is_not_silently_routed(tmp_path):
    path = write_header(tmp_path, MONITORING_CSV_COLUMNS)
    with pytest.raises(
        CsvFormatError, match="Expected prisma_export, but detected monitoring"
    ):
        require_csv_format(path, CsvFormat.PRISMA_EXPORT)


def test_ambiguity_is_structurally_impossible_for_current_exact_headers():
    assert MONITORING_CSV_COLUMNS != PRISMA_EXPORT_COLUMNS
    assert set(MONITORING_CSV_COLUMNS).isdisjoint(PRISMA_EXPORT_COLUMNS)
