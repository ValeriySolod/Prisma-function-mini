import csv

import pytest

from auction_csv import CSV_COLUMNS, AuctionCsvRecord, CsvValidationError, load_auction_csv


VALID_ROW = ["A-001", "https://example.com/a", "12", "Item", "Open", "Scheduled", "60", "true"]


def write_csv(tmp_path, rows, header=CSV_COLUMNS):
    path = tmp_path / "auctions.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        if header is not None:
            writer.writerow(header)
        writer.writerows(rows)
    return path


def assert_error(path, message):
    with pytest.raises(CsvValidationError, match=f"^{message.replace('.', '[.]')}$"):
        load_auction_csv(path)


def test_loads_one_typed_record(tmp_path):
    record = load_auction_csv(write_csv(tmp_path, [VALID_ROW]))[0]
    assert record == AuctionCsvRecord("A-001", "https://example.com/a", "12", "Item", "Open", "Scheduled", 60, True)
    assert type(record.check_interval_seconds) is int
    assert type(record.enabled) is bool


def test_loads_multiple_records(tmp_path):
    second = ["A-002", "http://example.com/b", "13", "Other", "Completed", "Open", "120", "false"]
    assert len(load_auction_csv(write_csv(tmp_path, [VALID_ROW, second]))) == 2


def test_missing_file(tmp_path):
    assert_error(tmp_path / "missing.csv", "CSV file does not exist.")


def test_wrong_extension_is_rejected(tmp_path):
    path = tmp_path / "auctions.txt"
    path.write_text("content", encoding="utf-8")
    assert_error(path, "Selected file must have a .csv extension.")


def test_uppercase_csv_extension_is_allowed(tmp_path):
    original = write_csv(tmp_path, [VALID_ROW])
    path = original.with_suffix(".CSV")
    original.rename(path)
    assert len(load_auction_csv(path)) == 1


def test_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    assert_error(path, "CSV file is empty.")


def test_missing_header(tmp_path):
    assert_error(write_csv(tmp_path, [], header=[""]), "CSV header is missing.")


@pytest.mark.parametrize("missing", CSV_COLUMNS)
def test_missing_required_columns(tmp_path, missing):
    header = [column for column in CSV_COLUMNS if column != missing]
    assert_error(write_csv(tmp_path, [VALID_ROW[:-1]], header), f"Missing required column: {missing}.")


def test_unexpected_column(tmp_path):
    assert_error(write_csv(tmp_path, [VALID_ROW + ["x"]], CSV_COLUMNS + ("extra_column",)), "Unexpected column: extra_column.")


def test_invalid_column_order(tmp_path):
    header = list(CSV_COLUMNS)
    header[0], header[1] = header[1], header[0]
    assert_error(write_csv(tmp_path, [VALID_ROW], header), "CSV columns are in an invalid order.")


def test_duplicate_column(tmp_path):
    header = list(CSV_COLUMNS)
    header[-1] = "auction_id"
    assert_error(write_csv(tmp_path, [VALID_ROW], header), "Duplicate column: auction_id.")


def test_no_data_rows(tmp_path):
    assert_error(write_csv(tmp_path, []), "CSV contains no data rows.")


@pytest.mark.parametrize("index,field", list(enumerate(CSV_COLUMNS)))
def test_empty_required_field(tmp_path, index, field):
    row = VALID_ROW.copy()
    row[index] = "  "
    assert_error(write_csv(tmp_path, [row]), f"Required field {field} is empty in row 2.")


def test_duplicate_id_reports_physical_row(tmp_path):
    assert_error(write_csv(tmp_path, [VALID_ROW, [*VALID_ROW]]), "Duplicate auction_id in row 3: A-001.")


@pytest.mark.parametrize("url", ["example.com", "ftp://example.com", "https:///path"])
def test_invalid_urls(tmp_path, url):
    row = VALID_ROW.copy(); row[1] = url
    assert_error(write_csv(tmp_path, [row]), "Invalid URL in row 2.")


@pytest.mark.parametrize("interval", ["0", "-1", "1.5", "text", "true"])
def test_invalid_intervals(tmp_path, interval):
    row = VALID_ROW.copy(); row[6] = interval
    assert_error(write_csv(tmp_path, [row]), "Invalid check_interval_seconds in row 2.")


@pytest.mark.parametrize("enabled", ["True", "FALSE", "1", "yes"])
def test_invalid_booleans(tmp_path, enabled):
    row = VALID_ROW.copy(); row[7] = enabled
    assert_error(write_csv(tmp_path, [row]), "Invalid enabled value in row 2.")


@pytest.mark.parametrize("index,field", [(4, "expected_status"), (5, "last_known_status")])
def test_invalid_statuses(tmp_path, index, field):
    row = VALID_ROW.copy(); row[index] = "Finished"
    assert_error(write_csv(tmp_path, [row]), f"Invalid {field} in row 2.")


def test_invalid_utf8(tmp_path):
    path = tmp_path / "bad.csv"; path.write_bytes(b"\xff\xfe")
    assert_error(path, "CSV file is not valid UTF-8.")


def test_wrong_field_count_is_malformed(tmp_path):
    assert_error(write_csv(tmp_path, [VALID_ROW[:-1]]), "Malformed CSV data in row 2.")


def test_broken_quoting_is_malformed(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(",".join(CSV_COLUMNS) + "\n\"unterminated", encoding="utf-8")
    assert_error(path, "Malformed CSV data in row 2.")


def test_values_are_stripped(tmp_path):
    row = [f"  {value}  " for value in VALID_ROW]
    record = load_auction_csv(write_csv(tmp_path, [row]))[0]
    assert record.auction_id == "A-001" and record.enabled is True


def test_error_returns_no_partial_result(tmp_path):
    invalid = VALID_ROW.copy(); invalid[0] = "A-002"; invalid[7] = "yes"
    with pytest.raises(CsvValidationError):
        load_auction_csv(write_csv(tmp_path, [VALID_ROW, invalid]))
