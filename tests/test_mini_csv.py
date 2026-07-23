import csv
import os
from datetime import date, datetime
from decimal import Decimal

import pytest

from mini_csv import MiniCsvError, MiniCsvPublisher
from mini_domain import (
    OUTPUT_COLUMNS, CapacityType, MiniDateRange, NormalizedAuctionRecord,
    ProductType, SourceImportRequest,
)
from mini_storage import MiniAuctionStorage
from runtime_paths import RuntimePaths


def paths(root):
    app_root = root / "PrismaFunctionMini"
    return RuntimePaths(
        app_root, app_root / "data" / "prisma_function_mini.db",
        app_root / "data" / "result" / "prisma_function_mini.csv",
        app_root / "state" / "prisma_function_mini_state.json",
        app_root / "logs" / "prisma-function-mini.log",
        app_root / "temporary-downloads",
    )


def request(sha="a" * 64):
    return SourceImportRequest(
        MiniDateRange(date(2026, 7, 1), date(2026, 7, 2)),
        "Auction_overview.csv", sha, 42,
    )


def record(number=1, **changes):
    values = dict(
        auction_id=f"A-{number}", network_point_id=f"NP-{number}",
        auction_date=date(2026, 7, number),
        exit_market_or_storage=None, entry_market_or_storage=None,
        capacity_type=CapacityType.BUNDLE, network_point=f"Punkt € {number}",
        product_type=ProductType.DAY_AHEAD,
        flow_start=datetime(2026, 7, number + 1, 6, 5),
        flow_end=datetime(2026, 7, number + 2, 6, 5),
        booked_capacity_kwh_h=Decimal("1000.5000"),
        duration_hours=Decimal("24"),
        auction_tariff_eur_mwh_h=Decimal("1.2500"),
        auction_premium_eur_mwh_h=None,
    )
    values.update(changes)
    return NormalizedAuctionRecord(**values)


def read_rows(path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle, delimiter=";"))


def test_csv_contract_utf8_semicolon_exact_columns_and_blank_values(tmp_path):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    storage.store(request(), [record()])
    output = MiniCsvPublisher(storage).publish()
    data = output.read_bytes()
    assert "Punkt €".encode("utf-8") in data
    rows = read_rows(output)
    assert tuple(rows[0]) == OUTPUT_COLUMNS
    assert rows[1] == [
        "2026-07-01", "", "", "Bundle", "Punkt € 1", "Day Ahead",
        "2026-07-02T06:05", "2026-07-03T06:05", "1000.5", "24",
        "1.25", "",
    ]
    assert all(len(row) == 12 for row in rows)
    assert b";" in data and b"," not in data


def test_premium_dot_decimal_is_locale_independent(tmp_path, monkeypatch):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    storage.store(
        request(), [record(auction_premium_eur_mwh_h=Decimal("0.12500"))]
    )
    monkeypatch.setattr("locale.localeconv", lambda: {"decimal_point": ","})
    assert read_rows(MiniCsvPublisher(storage).publish())[1][-1] == "0.125"


def test_deterministic_cumulative_order_and_exact_retry_avoid_replacement(tmp_path, monkeypatch):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    publisher = MiniCsvPublisher(storage)
    storage.store(request(), [record(2), record(1)])
    output = publisher.publish()
    first = output.read_bytes()
    first_mtime = output.stat().st_mtime_ns
    storage.store(request(), [record(1), record(2)])
    replaced = []
    monkeypatch.setattr(os, "replace", lambda *_args: replaced.append(True))
    assert publisher.publish().read_bytes() == first
    assert output.stat().st_mtime_ns == first_mtime
    assert replaced == []
    assert [row[4] for row in read_rows(output)[1:]] == ["Punkt € 1", "Punkt € 2"]


def test_locked_replace_preserves_previous_csv_and_cleans_staging(tmp_path, monkeypatch):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    publisher = MiniCsvPublisher(storage)
    storage.store(request(), [record(1)])
    output = publisher.publish()
    previous = output.read_bytes()
    storage.store(request("b" * 64), [record(2)])
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(MiniCsvError, match="open or locked"):
        publisher.publish()
    assert output.read_bytes() == previous
    assert not list(output.parent.glob(f".{output.stem}-*.csv"))


def test_validation_failure_preserves_previous_csv_and_cleans_staging(tmp_path, monkeypatch):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    publisher = MiniCsvPublisher(storage)
    storage.store(request(), [record(1)])
    output = publisher.publish()
    previous = output.read_bytes()
    storage.store(request("b" * 64), [record(2)])
    monkeypatch.setattr(publisher, "validate", lambda *_args: False)
    with pytest.raises(MiniCsvError, match="failed validation"):
        publisher.publish()
    assert output.read_bytes() == previous
    assert not list(output.parent.glob(f".{output.stem}-*.csv"))


def test_empty_history_publishes_header_only_csv(tmp_path):
    output = MiniCsvPublisher(MiniAuctionStorage(paths=paths(tmp_path))).publish()
    assert read_rows(output) == [list(OUTPUT_COLUMNS)]
