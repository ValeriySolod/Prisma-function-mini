import logging
from pathlib import Path

import runtime_logging
import runtime_paths


def reset_logger():
    logger = logging.getLogger(runtime_logging.LOGGER_NAME)
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    return logger


def test_log_initialization_in_source_mode(tmp_path, monkeypatch):
    reset_logger()
    target = tmp_path / "Local App Data" / "PrismaFunction" / "logs" / "prisma-function.log"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    monkeypatch.delattr(runtime_logging.sys, "frozen", raising=False)
    monkeypatch.delattr(runtime_logging.sys, "_MEIPASS", raising=False)

    logger, path = runtime_logging.initialize_runtime_logging()
    for handler in logger.handlers:
        handler.flush()

    assert path == target.resolve()
    text = target.read_text(encoding="utf-8")
    assert "mode=source" in text
    assert "python=" in text and "windows=" in text
    assert "executable=" in text and "application_path=" in text
    assert f"log_file={target.resolve()}" in text
    reset_logger()


def test_log_initialization_in_simulated_packaged_mode(tmp_path, monkeypatch):
    reset_logger()
    executable = tmp_path / "Program Files" / "Prisma Function" / "PrismaFunction.exe"
    bundle = executable.parent / "_internal"
    monkeypatch.setattr(runtime_logging.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_logging.sys, "executable", str(executable))
    monkeypatch.setattr(runtime_logging.sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user data"))

    logger, path = runtime_logging.initialize_runtime_logging()
    for handler in logger.handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")

    assert "mode=packaged" in text
    assert f"application_path={executable.parent.resolve()}" in text
    assert f"package_path={bundle.resolve()}" in text
    reset_logger()


def test_log_initialization_does_not_fall_back_outside_user_data(tmp_path, monkeypatch):
    reset_logger()
    preferred = tmp_path / "blocked" / "prisma-function.log"
    real_create = runtime_logging._create_handler
    monkeypatch.setattr(runtime_logging, "preferred_log_path", lambda: preferred)
    monkeypatch.setattr(runtime_logging, "fallback_log_path", lambda: preferred)

    def create(path):
        raise PermissionError("blocked")

    monkeypatch.setattr(runtime_logging, "_create_handler", create)
    logger, path = runtime_logging.initialize_runtime_logging()

    assert path is None
    assert any(isinstance(handler, logging.NullHandler) for handler in logger.handlers)
    reset_logger()


def test_total_logging_failure_uses_null_handler(monkeypatch):
    logger = reset_logger()
    monkeypatch.setattr(
        runtime_logging, "_create_handler", lambda path: (_ for _ in ()).throw(OSError())
    )

    configured, path = runtime_logging.initialize_runtime_logging()

    assert configured is logger
    assert path is None
    assert any(isinstance(handler, logging.NullHandler) for handler in logger.handlers)
    reset_logger()


def test_bootstrap_log_remains_active_and_legacy_current_log_becomes_conflict(tmp_path, monkeypatch):
    reset_logger()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    paths = runtime_paths.runtime_paths()
    legacy_logs = tmp_path / "temp" / "PrismaFunction" / "logs"
    legacy_logs.mkdir(parents=True)
    legacy = legacy_logs / runtime_paths.LOG_FILENAME
    legacy.write_text("legacy current log", encoding="utf-8")

    logger, path = runtime_logging.initialize_runtime_logging(paths.log)
    runtime_paths.migrate_legacy_runtime_data(
        paths=paths, logger=logger,
        app_directory=tmp_path / "missing", temp_directory=tmp_path / "temp",
    )
    for handler in logger.handlers:
        handler.flush()

    assert path == paths.log.resolve()
    assert "Application startup" in paths.log.read_text(encoding="utf-8")
    conflict = next(paths.log.parent.glob("prisma-function.log.legacy-*"))
    assert conflict.read_text(encoding="utf-8") == "legacy current log"
    assert legacy.read_text(encoding="utf-8") == "legacy current log"
    reset_logger()
