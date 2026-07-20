"""Validate the checked-in PyInstaller onedir output without launching the GUI."""

from __future__ import annotations

import argparse
from pathlib import Path


REQUIRED_PATHS = (
    "PrismaFunctionMini.exe",
    "_internal/PySide6/Qt6Core.dll",
    "_internal/PySide6/Qt6Gui.dll",
    "_internal/PySide6/Qt6Widgets.dll",
    "_internal/PySide6/plugins/platforms/qwindows.dll",
    "_internal/playwright/driver/node.exe",
    "_internal/playwright/driver/package/package.json",
)
FORBIDDEN_SUFFIXES = (".py", ".pyc", ".log", ".csv")
FORBIDDEN_PARTS = {
    ".venv", "tests", "__pycache__", ".pytest_cache", "temporary-downloads"
}
RUNTIME_OUTPUT_NAMES = {
    "prisma_function_mini.xlsx",
    "prisma_function_mini_state.json",
}
SQLITE_RUNTIME_NAMES = {
    "prisma_function_mini.db",
    "prisma_function_mini.db-shm",
    "prisma_function_mini.db-wal",
}


def _is_writable_runtime_file(name: str) -> bool:
    lowered = name.lower()
    if lowered in RUNTIME_OUTPUT_NAMES or lowered in SQLITE_RUNTIME_NAMES:
        return True
    if lowered == "prisma-function-mini.log":
        return True
    prefix = "prisma-function-mini.log."
    return lowered.startswith(prefix) and lowered[len(prefix):].isdigit()


def validate_distribution(distribution: Path) -> list[str]:
    """Return stable, English validation errors for a PyInstaller distribution."""
    distribution = distribution.resolve()
    errors = [
        f"Missing required package file: {relative}"
        for relative in REQUIRED_PATHS
        if not (distribution / Path(relative)).is_file()
    ]
    if not distribution.is_dir():
        return [f"Missing distribution directory: {distribution}"]
    if not any((distribution / "_internal").glob("python3*.dll")):
        errors.append("Missing required package file: _internal/python3*.dll")

    for path in sorted(item for item in distribution.rglob("*") if item.is_file()):
        relative = path.relative_to(distribution)
        lowered_parts = {part.lower() for part in relative.parts}
        if lowered_parts & FORBIDDEN_PARTS:
            errors.append(f"Developer-only path in package: {relative.as_posix()}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"Forbidden file type in package: {relative.as_posix()}")
        if _is_writable_runtime_file(path.name):
            errors.append(f"Writable runtime file in package: {relative.as_posix()}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the PrismaFunctionMini onedir package.")
    parser.add_argument(
        "distribution",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parent / "dist" / "PrismaFunctionMini",
    )
    arguments = parser.parse_args()
    errors = validate_distribution(arguments.distribution)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Package validation passed: {arguments.distribution.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
