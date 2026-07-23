"""Atomic publication of the authoritative Prisma Function Mini CSV."""

from __future__ import annotations

import csv
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from mini_domain import MiniOutputRow, OUTPUT_COLUMNS
from mini_storage import MiniAuctionStorage


class MiniCsvError(RuntimeError):
    """The cumulative CSV could not be published safely."""


class MiniCsvPublisher:
    """Render a deterministic CSV snapshot from Mini's SQLite history."""

    def __init__(self, storage: MiniAuctionStorage) -> None:
        if not isinstance(storage, MiniAuctionStorage):
            raise TypeError("storage must be MiniAuctionStorage.")
        approved = storage.paths.root / "data" / "result" / "prisma_function_mini.csv"
        if storage.paths.result != approved:
            raise ValueError("Mini CSV must use the approved runtime path.")
        self.storage = storage
        self.output_path = storage.paths.result

    def publish(self) -> Path:
        rows = tuple(
            MiniOutputRow.from_record(item.auction).values()
            for item in self.storage.history()
        )
        expected = self._content(rows)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.output_path.exists():
            try:
                if self.output_path.read_bytes() == expected and self.validate(
                    self.output_path, rows
                ):
                    return self.output_path
            except OSError:
                pass
        staged: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=f".{self.output_path.stem}-",
                suffix=".csv",
                dir=self.output_path.parent,
            )
            staged = Path(name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(expected)
                handle.flush()
                os.fsync(handle.fileno())
            if not self.validate(staged, rows):
                raise MiniCsvError("The staged CSV failed validation.")
            try:
                os.replace(staged, self.output_path)
            except PermissionError as exc:
                raise MiniCsvError(
                    "The CSV output is open or locked. Close it and retry publication."
                ) from exc
            staged = None
            return self.output_path
        except MiniCsvError:
            raise
        except Exception as exc:
            raise MiniCsvError("The CSV output could not be staged safely.") from exc
        finally:
            if staged is not None:
                try:
                    staged.unlink(missing_ok=True)
                except OSError:
                    pass

    @classmethod
    def _content(cls, rows: Iterable[tuple[object, ...]]) -> bytes:
        import io

        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(OUTPUT_COLUMNS)
        writer.writerows(tuple(cls._serialize(value) for value in row) for row in rows)
        return stream.getvalue().encode("utf-8")

    @staticmethod
    def _serialize(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat(timespec="minutes")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            if value == 0:
                return "0"
            text = format(value, "f")
            return text.rstrip("0").rstrip(".") if "." in text else text
        return str(value)

    @classmethod
    def validate(
        cls, path: Path, expected_rows: Iterable[tuple[object, ...]]
    ) -> bool:
        try:
            data = path.read_bytes()
            if data != cls._content(expected_rows):
                return False
            text = data.decode("utf-8")
            rows = list(csv.reader(text.splitlines(), delimiter=";"))
            return bool(rows) and tuple(rows[0]) == OUTPUT_COLUMNS and all(
                len(row) == len(OUTPUT_COLUMNS) for row in rows
            )
        except (OSError, UnicodeError, csv.Error):
            return False
