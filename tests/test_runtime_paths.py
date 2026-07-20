import sqlite3
import threading
import os
import time
from pathlib import Path

import pytest
from unittest.mock import Mock

import runtime_paths


@pytest.fixture
def user_data(tmp_path, monkeypatch):
    local = tmp_path / "Local App Data"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return local


def test_windows_local_app_data_resolution_and_layout(user_data):
    paths = runtime_paths.runtime_paths()
    assert paths.root == user_data / "PrismaFunction"
    assert paths.database == paths.root / "data" / "prisma_monitor.db"
    assert paths.result == paths.root / "data" / "result" / "prisma_auctions.xlsx"
    assert paths.state == paths.root / "state" / "prisma_import_state.json"
    assert paths.log == paths.root / "logs" / "prisma-function.log"
    assert not paths.root.exists()


def test_relative_local_app_data_is_rejected(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "relative")
    with pytest.raises(runtime_paths.RuntimePathError, match="absolute"):
        runtime_paths.runtime_paths()


def test_user_profile_is_deterministic_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    assert runtime_paths.windows_local_app_data() == tmp_path / "profile" / "AppData" / "Local"


def _legacy_tree(root: Path):
    data = root / "data"
    (data / "result").mkdir(parents=True)
    with sqlite3.connect(data / "prisma_monitor.db") as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('preserved')")
    (data / "result" / "prisma_auctions.xlsx").write_bytes(b"workbook")
    (data / "prisma_import_state.json").write_text('{"accepted_sources": []}', encoding="utf-8")


def test_migrates_all_confirmed_categories_and_is_idempotent(tmp_path, user_data):
    legacy = tmp_path / "installed"
    temp = tmp_path / "temp"
    _legacy_tree(legacy)
    old_logs = temp / "PrismaFunction" / "logs"
    old_logs.mkdir(parents=True)
    (old_logs / "prisma-function.log").write_text("legacy log", encoding="utf-8")
    (old_logs / "prisma-function.log.1").write_text("rotated", encoding="utf-8")

    first = runtime_paths.migrate_legacy_runtime_data(app_directory=legacy, temp_directory=temp)
    paths = runtime_paths.runtime_paths()
    assert {name for name, _ in first} == {
        "prisma_monitor.db", "prisma_auctions.xlsx", "prisma_import_state.json",
        "prisma-function.log", "prisma-function.log.1",
    }
    with sqlite3.connect(paths.database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "preserved"
    assert paths.result.read_bytes() == b"workbook"
    assert paths.state.read_text(encoding="utf-8") == '{"accepted_sources": []}'
    assert paths.log.read_text(encoding="utf-8") == "legacy log"
    assert (paths.log.parent / "prisma-function.log.1").read_text(encoding="utf-8") == "rotated"

    second = runtime_paths.migrate_legacy_runtime_data(app_directory=legacy, temp_directory=temp)
    assert second and all(outcome == "identical" for _, outcome in second)


def test_conflict_retains_destination_source_and_named_legacy_copy(tmp_path, user_data):
    legacy = tmp_path / "installed"
    source = legacy / "data" / "result" / "prisma_auctions.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"legacy")
    destination = runtime_paths.runtime_paths().result
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"current")

    outcomes = runtime_paths.migrate_legacy_runtime_data(app_directory=legacy, temp_directory=tmp_path / "none")

    assert destination.read_bytes() == b"current"
    assert source.read_bytes() == b"legacy"
    conflict = next(destination.parent.glob("prisma_auctions.xlsx.legacy-*"))
    assert conflict.read_bytes() == b"legacy"
    assert outcomes[0][1].startswith("conflict:")


def test_failed_atomic_replace_leaves_no_destination_or_staging(tmp_path, user_data, monkeypatch):
    source = tmp_path / "installed" / "data" / "prisma_import_state.json"
    source.parent.mkdir(parents=True)
    source.write_text("state", encoding="utf-8")
    real_replace = runtime_paths.os.replace
    monkeypatch.setattr(runtime_paths.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("interrupted")))
    with pytest.raises(OSError, match="interrupted"):
        runtime_paths.migrate_legacy_runtime_data(app_directory=tmp_path / "installed", temp_directory=tmp_path / "none")
    destination = runtime_paths.runtime_paths().state
    assert not destination.exists()
    assert not list(destination.parent.glob("*.migrating"))
    assert source.read_text(encoding="utf-8") == "state"
    monkeypatch.setattr(runtime_paths.os, "replace", real_replace)


def test_missing_legacy_sources_are_ignored(tmp_path, user_data):
    assert runtime_paths.migrate_legacy_runtime_data(
        app_directory=tmp_path / "missing", temp_directory=tmp_path / "missing-temp"
    ) == []


def test_stale_interrupted_migration_lock_is_recovered(tmp_path, user_data):
    paths = runtime_paths.runtime_paths()
    lock = paths.root / runtime_paths.LOCK_FILENAME
    lock.mkdir(parents=True)
    old = time.time() - 600
    os.utime(lock, (old, old))
    assert runtime_paths.migrate_legacy_runtime_data(
        app_directory=tmp_path / "missing", temp_directory=tmp_path / "missing-temp",
        lock_stale_seconds=300,
    ) == []
    assert not lock.exists()


@pytest.mark.parametrize(
    ("handle", "error", "wait_result", "expected"),
    (
        (101, 0, runtime_paths.WAIT_TIMEOUT, True),
        (102, 0, runtime_paths.WAIT_OBJECT_0, False),
        (0, runtime_paths.ERROR_ACCESS_DENIED, None, True),
        (0, runtime_paths.ERROR_INVALID_PARAMETER, None, False),
    ),
    ids=("alive", "exited", "inaccessible", "missing"),
)
def test_windows_pid_query_is_read_only_and_never_calls_os_kill(
        monkeypatch, handle, error, wait_result, expected):
    api = Mock()
    api.OpenProcess.return_value = handle
    api.WaitForSingleObject.return_value = wait_result
    kill = Mock(side_effect=AssertionError("os.kill must not be used on Windows"))
    monkeypatch.setattr(runtime_paths.os, "kill", kill)

    assert runtime_paths._process_is_running(
        4321, platform="nt", kernel32=api, get_last_error=lambda: error
    ) is expected

    kill.assert_not_called()
    api.OpenProcess.assert_called_once_with(
        runtime_paths.PROCESS_QUERY_LIMITED_INFORMATION | runtime_paths.SYNCHRONIZE,
        False, 4321,
    )
    if handle:
        api.CloseHandle.assert_called_once_with(handle)
    else:
        api.WaitForSingleObject.assert_not_called()
        api.CloseHandle.assert_not_called()


def test_replacement_between_stale_inspection_and_quarantine_is_preserved(tmp_path, user_data):
    paths = runtime_paths.runtime_paths()
    lock = paths.root / runtime_paths.LOCK_FILENAME
    lock.mkdir(parents=True)
    old = time.time() - 600
    os.utime(lock, (old, old))
    inspection = runtime_paths._inspect_stale_lock(lock, stale_seconds=300)
    assert inspection is not None

    displaced = paths.root / ".old-stale-lock"
    os.replace(lock, displaced)
    lock.mkdir()
    replacement_owner = f"{os.getpid()}:active-replacement"
    (lock / runtime_paths.LOCK_OWNER_FILENAME).write_text(replacement_owner, encoding="ascii")

    assert not runtime_paths._quarantine_inspected_lock(lock, inspection)
    assert lock.is_dir()
    assert (lock / runtime_paths.LOCK_OWNER_FILENAME).read_text(encoding="ascii") == replacement_owner

    (lock / runtime_paths.LOCK_OWNER_FILENAME).unlink()
    lock.rmdir()
    displaced.rmdir()


def test_partially_initialized_lock_is_never_treated_as_stale(tmp_path, user_data, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = runtime_paths._write_lock_owner

    def paused(lock, owner):
        entered.set()
        assert release.wait(2)
        original(lock, owner)

    monkeypatch.setattr(runtime_paths, "_write_lock_owner", paused)
    first_errors = []
    first = threading.Thread(target=lambda: _capture_migration_error(
        first_errors, tmp_path, lock_timeout=2
    ))
    first.start()
    assert entered.wait(2)
    with pytest.raises(runtime_paths.RuntimePathError, match="busy"):
        runtime_paths.migrate_legacy_runtime_data(
            app_directory=tmp_path / "missing", temp_directory=tmp_path / "missing-temp",
            lock_timeout=0.1, lock_stale_seconds=300,
        )
    assert (runtime_paths.runtime_paths().root / runtime_paths.LOCK_FILENAME).is_dir()
    release.set()
    first.join(2)
    assert not first_errors


def _capture_migration_error(errors, tmp_path, *, lock_timeout):
    try:
        runtime_paths.migrate_legacy_runtime_data(
            app_directory=tmp_path / "missing", temp_directory=tmp_path / "missing-temp",
            lock_timeout=lock_timeout,
        )
    except Exception as exc:
        errors.append(exc)


def test_concurrent_migration_attempts_are_serialized(tmp_path, user_data):
    legacy = tmp_path / "installed"
    _legacy_tree(legacy)
    errors = []
    results = []
    barrier = threading.Barrier(2)

    def run():
        try:
            barrier.wait()
            results.append(runtime_paths.migrate_legacy_runtime_data(
                app_directory=legacy, temp_directory=tmp_path / "none", lock_timeout=2
            ))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert not errors
    assert len(results) == 2
    with sqlite3.connect(runtime_paths.runtime_paths().database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_owner_release_does_not_remove_replacement_lock(tmp_path, user_data, monkeypatch):
    paths = runtime_paths.runtime_paths()
    displaced = paths.root / ".displaced-lock"

    def replace_during_migration(**kwargs):
        lock = paths.root / runtime_paths.LOCK_FILENAME
        os.replace(lock, displaced)
        lock.mkdir()
        (lock / runtime_paths.LOCK_OWNER_FILENAME).write_text(
            f"{os.getpid()}:replacement", encoding="ascii"
        )
        return ()

    monkeypatch.setattr(runtime_paths, "legacy_artifacts", replace_during_migration)
    assert runtime_paths.migrate_legacy_runtime_data(
        paths=paths, app_directory=tmp_path / "missing", temp_directory=tmp_path / "none"
    ) == []

    replacement = paths.root / runtime_paths.LOCK_FILENAME
    assert replacement.is_dir()
    assert "replacement" in (replacement / runtime_paths.LOCK_OWNER_FILENAME).read_text(encoding="ascii")
    (replacement / runtime_paths.LOCK_OWNER_FILENAME).unlink()
    replacement.rmdir()
    (displaced / runtime_paths.LOCK_OWNER_FILENAME).unlink()
    displaced.rmdir()


def test_live_wal_source_special_path_migrates_committed_wal_and_repeats_identically(tmp_path, user_data):
    legacy = tmp_path / "installed # 50% space"
    database = legacy / "data" / "prisma_monitor.db"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("INSERT INTO sample VALUES ('committed-in-wal')")
        connection.commit()
        assert database.with_name(f"{database.name}-wal").stat().st_size > 0

        first = runtime_paths.migrate_legacy_runtime_data(
            app_directory=legacy, temp_directory=tmp_path / "none"
        )
        with sqlite3.connect(runtime_paths.runtime_paths().database) as migrated:
            assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert migrated.execute("SELECT value FROM sample").fetchone()[0] == "committed-in-wal"
        second = runtime_paths.migrate_legacy_runtime_data(
            app_directory=legacy, temp_directory=tmp_path / "none"
        )
        assert first[0][1] == "migrated"
        assert second[0][1] == "identical"
    finally:
        connection.close()


def test_logically_identical_sqlite_with_different_wal_representation_is_identical(tmp_path, user_data):
    legacy = tmp_path / "installed"
    source = legacy / "data" / "prisma_monitor.db"
    source.parent.mkdir(parents=True)
    destination = runtime_paths.runtime_paths().database
    destination.parent.mkdir(parents=True)
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('same')")
    with sqlite3.connect(destination) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('same')")
        connection.commit()
        connection.execute("VACUUM")

    outcomes = runtime_paths.migrate_legacy_runtime_data(
        app_directory=legacy, temp_directory=tmp_path / "none"
    )

    assert outcomes == [("prisma_monitor.db", "identical")]
    assert not list(destination.parent.glob("prisma_monitor.db.legacy-*"))


def test_conflicting_sqlite_preserves_both_databases(tmp_path, user_data):
    legacy = tmp_path / "installed"
    source = legacy / "data" / "prisma_monitor.db"
    source.parent.mkdir(parents=True)
    destination = runtime_paths.runtime_paths().database
    destination.parent.mkdir(parents=True)
    for path, value in ((source, "legacy"), (destination, "current")):
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE sample(value TEXT)")
            connection.execute("INSERT INTO sample VALUES (?)", (value,))

    outcomes = runtime_paths.migrate_legacy_runtime_data(
        app_directory=legacy, temp_directory=tmp_path / "none"
    )

    conflict = next(destination.parent.glob("prisma_monitor.db.legacy-*"))
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "current"
    with sqlite3.connect(conflict) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "legacy"
    with sqlite3.connect(source) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "legacy"
    assert outcomes[0][1].startswith("conflict:")


def test_sqlite_readonly_uri_percent_encodes_query_and_fragment_characters(tmp_path):
    uri = runtime_paths._sqlite_readonly_uri(tmp_path / "space # percent% question?.db")
    assert "space%20%23%20percent%25%20question%3F.db?mode=ro" in uri


def test_source_and_frozen_application_locations_do_not_affect_defaults(tmp_path, user_data, monkeypatch):
    source_paths = runtime_paths.runtime_paths()
    monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_paths.sys, "executable", str(tmp_path / "Program Files" / "PrismaFunction.exe"))
    assert runtime_paths.runtime_paths() == source_paths
