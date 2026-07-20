from __future__ import annotations

import logging
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from runtime_paths import LOG_FILENAME, runtime_paths


LOGGER_NAME = "prisma_function_mini"


def runtime_mode() -> str:
    return "packaged" if getattr(sys, "frozen", False) else "source"


def application_path() -> Path:
    if runtime_mode() == "packaged":
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def package_path() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle).resolve() if bundle else application_path()


def preferred_log_path() -> Path:
    return runtime_paths().log


def fallback_log_path() -> Path:
    """Compatibility alias: normal runtime writes never fall back outside user data."""
    return preferred_log_path()


def _create_handler(path: Path) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    return RotatingFileHandler(
        path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )


def initialize_runtime_logging(log_path: Path | None = None) -> tuple[logging.Logger, Path | None]:
    """Initialize persistent logging; return a null path when no file handler is available."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    resolved_path = None
    if not logger.handlers:
        candidates = (log_path,) if log_path is not None else dict.fromkeys(
            (preferred_log_path(), fallback_log_path())
        )
        for candidate in candidates:
            try:
                handler = _create_handler(candidate)
            except Exception:
                continue
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(threadName)s %(message)s"
            ))
            logger.addHandler(handler)
            resolved_path = candidate.resolve()
            break
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
    else:
        for handler in logger.handlers:
            filename = getattr(handler, "baseFilename", None)
            if filename:
                resolved_path = Path(filename).resolve()
                break

    safe_log(
        logger,
        logging.INFO,
        "Application startup: mode=%s python=%s windows=%s executable=%s "
        "application_path=%s package_path=%s log_file=%s",
        runtime_mode(),
        platform.python_version(),
        platform.platform(),
        Path(sys.executable).resolve(),
        application_path(),
        package_path(),
        resolved_path or "unavailable",
    )
    return logger, resolved_path


def safe_log(logger: logging.Logger, level: int, message: str, *args, **kwargs) -> None:
    """Ensure diagnostics can never interfere with application behavior."""
    try:
        logger.log(level, message, *args, **kwargs)
    except Exception:
        pass
