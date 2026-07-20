"""Authoritative locations and safe migration for application-owned runtime data."""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


APP_DIRECTORY_NAME = "PrismaFunctionMini"
HISTORICAL_APP_DIRECTORY_NAME = "PrismaFunction"
DATABASE_FILENAME = "prisma_function_mini.db"
RESULT_FILENAME = "prisma_function_mini.xlsx"
STATE_FILENAME = "prisma_function_mini_state.json"
LOG_FILENAME = "prisma-function-mini.log"
TEMPORARY_DOWNLOAD_DIRECTORY_NAME = "temporary-downloads"
LOCK_FILENAME = ".migration.lock"
LOCK_STALE_SECONDS = 300.0
LOCK_OWNER_FILENAME = "owner"

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87


class RuntimePathError(RuntimeError):
    """A stable, actionable runtime path or migration failure."""


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    database: Path
    result: Path
    state: Path
    log: Path
    temporary_downloads: Path


@dataclass(frozen=True)
class LockInspection:
    identity: tuple[int, ...]
    owner: str | None


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def windows_local_app_data(environ: dict[str, str] | os._Environ[str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get("LOCALAPPDATA", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_absolute():
            return path
        raise RuntimePathError("LOCALAPPDATA must be an absolute path.")
    profile = env.get("USERPROFILE", "").strip()
    if profile and Path(profile).expanduser().is_absolute():
        return Path(profile).expanduser() / "AppData" / "Local"
    home = Path.home()
    if home.is_absolute():
        return home / "AppData" / "Local"
    raise RuntimePathError(
        "Windows user-data directory is unavailable. Set LOCALAPPDATA to an absolute path."
    )


def runtime_paths(*, environ=None) -> RuntimePaths:
    root = windows_local_app_data(environ) / APP_DIRECTORY_NAME
    return RuntimePaths(
        root=root,
        database=root / "data" / DATABASE_FILENAME,
        result=root / "data" / "result" / RESULT_FILENAME,
        state=root / "state" / STATE_FILENAME,
        log=root / "logs" / LOG_FILENAME,
        temporary_downloads=root / TEMPORARY_DOWNLOAD_DIRECTORY_NAME,
    )


def historical_runtime_root(*, environ=None) -> Path:
    """Return the inherited application's read-only data root.

    Mini never creates, migrates, or modifies this location automatically.
    """
    return windows_local_app_data(environ) / HISTORICAL_APP_DIRECTORY_NAME


def prepare_runtime_directories(*, paths: RuntimePaths | None = None) -> RuntimePaths:
    """Create only Mini-owned runtime directories and return their paths."""
    selected = paths or runtime_paths()
    for directory in (
        selected.database.parent,
        selected.result.parent,
        selected.state.parent,
        selected.log.parent,
        selected.temporary_downloads,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return selected


def legacy_artifacts(*, paths: RuntimePaths | None = None,
                     app_directory: Path | None = None) -> tuple[tuple[Path, Path, str], ...]:
    old_root = (app_directory or application_directory()).resolve()
    paths = paths or runtime_paths()
    return (
        (old_root / "data" / DATABASE_FILENAME, paths.database, "sqlite"),
        (old_root / "data" / "result" / RESULT_FILENAME, paths.result, "file"),
        (old_root / "data" / STATE_FILENAME, paths.state, "file"),
    )


def legacy_log_artifacts(*, paths: RuntimePaths | None = None,
                         temp_directory: Path | None = None) -> tuple[tuple[Path, Path, str], ...]:
    old = (temp_directory or Path(tempfile.gettempdir())) / APP_DIRECTORY_NAME / "logs"
    destination = (paths or runtime_paths()).log.parent
    return tuple((old / name, destination / name, "file") for name in (
        LOG_FILENAME, *(f"{LOG_FILENAME}.{index}" for index in range(1, 4))
    ))


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _verified_copy(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_digest = _digest(source)
    if destination.exists():
        if destination.is_file() and _digest(destination) == source_digest:
            return "identical"
        conflict = _available_conflict_path(destination, source_digest)
        if not conflict.exists():
            _atomic_copy(source, conflict, source_digest)
        return f"conflict:{conflict.name}"
    _atomic_copy(source, destination, source_digest)
    return "migrated"


def _available_conflict_path(destination: Path, digest: str) -> Path:
    base = destination.with_name(f"{destination.name}.legacy-{digest[:12]}")
    candidate = base
    sequence = 1
    while candidate.exists() and (not candidate.is_file() or _digest(candidate) != digest):
        candidate = destination.with_name(f"{base.name}-{sequence}")
        sequence += 1
    return candidate


def _atomic_copy(source: Path, destination: Path, expected_digest: str) -> None:
    descriptor, staged_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".migrating", dir=destination.parent)
    staged = Path(staged_name)
    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as origin:
            shutil.copyfileobj(origin, target)
            target.flush()
            os.fsync(target.fileno())
        if _digest(staged) != expected_digest:
            raise RuntimePathError(f"Migration verification failed for {source.name}.")
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def _sqlite_copy(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_snapshot = _sqlite_snapshot(source, destination.parent)
    destination_snapshot = None
    try:
        source_digest = _sqlite_logical_digest(source_snapshot)
        if not destination.exists():
            os.replace(source_snapshot, destination)
            source_snapshot = None
            return "migrated"
        destination_snapshot = _sqlite_snapshot(destination, destination.parent)
        if _sqlite_logical_digest(destination_snapshot) == source_digest:
            return "identical"
        conflict = _available_sqlite_conflict_path(destination, source_digest)
        if not conflict.exists():
            os.replace(source_snapshot, conflict)
            source_snapshot = None
        return f"conflict:{conflict.name}"
    finally:
        if source_snapshot is not None:
            source_snapshot.unlink(missing_ok=True)
        if destination_snapshot is not None:
            destination_snapshot.unlink(missing_ok=True)


def _available_sqlite_conflict_path(destination: Path, digest: str) -> Path:
    base = destination.with_name(f"{destination.name}.legacy-{digest[:12]}")
    candidate = base
    sequence = 1
    while candidate.exists():
        snapshot = _sqlite_snapshot(candidate, destination.parent)
        try:
            if _sqlite_logical_digest(snapshot) == digest:
                return candidate
        finally:
            snapshot.unlink(missing_ok=True)
        candidate = destination.with_name(f"{base.name}-{sequence}")
        sequence += 1
    return candidate


def _sqlite_snapshot(source: Path, directory: Path) -> Path:
    snapshot = directory / f".{source.name}.{uuid.uuid4().hex}.snapshot"
    _sqlite_backup(source, snapshot)
    return snapshot


def _sqlite_logical_digest(snapshot: Path) -> str:
    value = hashlib.sha256()
    with closing(sqlite3.connect(_sqlite_readonly_uri(snapshot), uri=True)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimePathError(f"SQLite snapshot {snapshot.name} failed integrity verification.")
        for pragma in ("application_id", "user_version"):
            value.update(f"PRAGMA {pragma}={connection.execute(f'PRAGMA {pragma}').fetchone()[0]}\n".encode())
        for statement in connection.iterdump():
            value.update(statement.encode("utf-8"))
            value.update(b"\n")
    return value.hexdigest()


def _sqlite_readonly_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _sqlite_backup(source: Path, destination: Path) -> None:
    staged = destination.with_name(f".{destination.name}.{os.getpid()}.migrating")
    staged.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(_sqlite_readonly_uri(source), uri=True)) as origin:
            with closing(sqlite3.connect(staged)) as target:
                origin.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimePathError(f"Migrated SQLite database {source.name} failed integrity verification.")
        os.replace(staged, destination)
    except (OSError, sqlite3.Error) as exc:
        raise RuntimePathError(f"Could not migrate SQLite database {source.name}: {exc}") from exc
    finally:
        staged.unlink(missing_ok=True)


def _windows_process_is_running(pid: int, *, kernel32=None, get_last_error=None) -> bool:
    """Query a Windows PID without signaling or modifying the process."""
    import ctypes

    api = kernel32 or ctypes.WinDLL("kernel32", use_last_error=True)
    if kernel32 is None:
        from ctypes import wintypes
        api.OpenProcess.restype = wintypes.HANDLE
    last_error = get_last_error or ctypes.get_last_error
    handle = api.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
    )
    if not handle:
        error = last_error()
        if error == ERROR_INVALID_PARAMETER:
            return False
        # Access denied and unknown query failures are conservatively alive.
        return True
    try:
        result = api.WaitForSingleObject(handle, 0)
        if result == WAIT_OBJECT_0:
            return False
        return True
    finally:
        api.CloseHandle(handle)


def _process_is_running(pid: int, *, platform: str | None = None,
                        kernel32=None, get_last_error=None) -> bool:
    selected = os.name if platform is None else platform
    if selected == "nt":
        return _windows_process_is_running(
            pid, kernel32=kernel32, get_last_error=get_last_error
        )
    try:
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError):
        return False
    except (OSError, PermissionError):
        # POSIX permission errors mean the process exists but is inaccessible.
        return True


def _lock_owner_is_running(owner: str) -> bool:
    try:
        pid = int(owner.split(":", 1)[0])
    except ValueError:
        return False
    return _process_is_running(pid)


def _write_lock_owner(lock: Path, owner: str) -> None:
    staged = lock / f".{LOCK_OWNER_FILENAME}.{uuid.uuid4().hex}"
    staged.write_text(owner, encoding="ascii")
    os.replace(staged, lock / LOCK_OWNER_FILENAME)


def _windows_path_identity(path: Path) -> tuple[int, ...]:
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = (
            ("attributes", wintypes.DWORD), ("creation", FILETIME),
            ("access", FILETIME), ("write", FILETIME),
            ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD),
        )

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.restype = wintypes.HANDLE
    handle = api.CreateFileW(
        str(path), 0x0080, 0x00000001 | 0x00000002 | 0x00000004,
        None, 3, 0x02000000, None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise FileNotFoundError(path)
    try:
        information = BY_HANDLE_FILE_INFORMATION()
        if not api.GetFileInformationByHandle(handle, ctypes.byref(information)):
            raise OSError(ctypes.get_last_error(), f"Could not identify lock directory {path}")
        return (information.volume, information.index_high, information.index_low)
    finally:
        api.CloseHandle(handle)


def _windows_quarantine_exact(lock: Path, expected_identity: tuple[int, ...],
                              quarantine: Path) -> bool:
    """Rename the exact opened Windows directory object, not a later path replacement."""
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = (
            ("attributes", wintypes.DWORD), ("creation", FILETIME),
            ("access", FILETIME), ("write", FILETIME),
            ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD),
        )

    class FILE_RENAME_HEADER(ctypes.Structure):
        _fields_ = (
            ("replace", wintypes.BOOL),
            ("root", wintypes.HANDLE),
            ("name_length", wintypes.DWORD),
        )

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.restype = wintypes.HANDLE
    handle = api.CreateFileW(
        str(lock), 0x00010000 | 0x0080,
        0x00000001 | 0x00000002 | 0x00000004,
        None, 3, 0x02000000, None,
    )
    if handle == ctypes.c_void_p(-1).value:
        return False
    try:
        information = BY_HANDLE_FILE_INFORMATION()
        if not api.GetFileInformationByHandle(handle, ctypes.byref(information)):
            return False
        identity = (information.volume, information.index_high, information.index_low)
        if identity != expected_identity:
            return False
        encoded = str(quarantine.resolve()).encode("utf-16-le")
        name_offset = FILE_RENAME_HEADER.name_length.offset + ctypes.sizeof(wintypes.DWORD)
        buffer = ctypes.create_string_buffer(name_offset + len(encoded))
        header = FILE_RENAME_HEADER.from_buffer(buffer)
        header.replace = False
        header.root = None
        header.name_length = len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + name_offset, encoded, len(encoded))
        return bool(api.SetFileInformationByHandle(handle, 3, buffer, len(buffer)))
    finally:
        api.CloseHandle(handle)


def _path_identity(path: Path) -> tuple[int, ...]:
    if os.name == "nt":
        return _windows_path_identity(path)
    stat = path.stat()
    return (stat.st_dev, stat.st_ino)


def _inspect_stale_lock(lock: Path, *, stale_seconds: float) -> LockInspection | None:
    try:
        stat = lock.stat()
        age = time.time() - stat.st_mtime
        identity = _path_identity(lock)
    except FileNotFoundError:
        return None
    if age < stale_seconds:
        return None
    try:
        owner = (lock / LOCK_OWNER_FILENAME).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        owner = None
    if owner is not None and _lock_owner_is_running(owner):
        return None
    return LockInspection(identity, owner)


def _quarantine_inspected_lock(lock: Path, inspection: LockInspection) -> bool:
    """Quarantine only the directory instance represented by ``inspection``."""
    try:
        if _path_identity(lock) != inspection.identity:
            return False
        current_owner = (lock / LOCK_OWNER_FILENAME).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        current_owner = None
    if current_owner != inspection.owner:
        return False
    quarantine = lock.with_name(f"{lock.name}.stale-{uuid.uuid4().hex}")
    try:
        if os.name == "nt":
            if not _windows_quarantine_exact(lock, inspection.identity, quarantine):
                return False
        else:
            # Development-only POSIX fallback: identity and owner are rechecked
            # immediately before the atomic directory rename.
            if _path_identity(lock) != inspection.identity:
                return False
            os.replace(lock, quarantine)
    except (FileNotFoundError, OSError):
        return False
    try:
        for entry in quarantine.iterdir():
            entry.unlink()
        quarantine.rmdir()
    except OSError:
        pass
    return True


def _release_owned_lock(lock: Path, owner: str) -> None:
    try:
        identity = _path_identity(lock)
        current_owner = (lock / LOCK_OWNER_FILENAME).read_text(encoding="ascii").strip()
    except (FileNotFoundError, OSError, UnicodeError):
        return
    if current_owner == owner:
        _quarantine_inspected_lock(lock, LockInspection(identity, owner))


def migrate_legacy_runtime_data(*, paths: RuntimePaths | None = None,
                                logger: logging.Logger | None = None,
                                app_directory: Path | None = None,
                                temp_directory: Path | None = None,
                                lock_timeout: float = 10.0,
                                lock_stale_seconds: float = LOCK_STALE_SECONDS) -> list[tuple[str, str]]:
    """Migrate only confirmed application-owned paths; safe to call repeatedly."""
    log = logger or logging.getLogger("prisma_function_mini")
    paths = paths or runtime_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    lock = paths.root / LOCK_FILENAME
    deadline = time.monotonic() + lock_timeout
    owner = f"{os.getpid()}:{uuid.uuid4().hex}"
    acquired = False
    while not acquired:
        try:
            lock.mkdir()
            _write_lock_owner(lock, owner)
            acquired = True
        except FileExistsError:
            inspection = _inspect_stale_lock(lock, stale_seconds=lock_stale_seconds)
            if inspection is not None and _quarantine_inspected_lock(lock, inspection):
                continue
            if time.monotonic() >= deadline:
                raise RuntimePathError("Runtime-data migration is busy in another PrismaFunctionMini process. Retry shortly.")
            time.sleep(0.05)
        except Exception:
            try:
                if lock.is_dir() and not (lock / LOCK_OWNER_FILENAME).exists():
                    for entry in lock.iterdir():
                        entry.unlink()
                    lock.rmdir()
            except OSError:
                pass
            raise
    results: list[tuple[str, str]] = []
    try:
        artifacts = legacy_artifacts(paths=paths, app_directory=app_directory) + legacy_log_artifacts(
            paths=paths, temp_directory=temp_directory
        )
        allowed_roots = (
            (app_directory or application_directory()).resolve(),
            ((temp_directory or Path(tempfile.gettempdir())) / APP_DIRECTORY_NAME / "logs").resolve(),
        )
        for source, destination, kind in artifacts:
            if source.resolve() == destination.resolve() or not source.exists():
                continue
            resolved_source = source.resolve()
            if not any(resolved_source == root or root in resolved_source.parents for root in allowed_roots):
                raise RuntimePathError(f"Legacy migration path escaped its confirmed root: {source.name}.")
            if not source.is_file():
                log.warning("Migration skipped unreadable artifact: category=%s source=%s", kind, source)
                continue
            outcome = _sqlite_copy(source, destination) if kind == "sqlite" else _verified_copy(source, destination)
            results.append((source.name, outcome))
            log.info("Runtime migration: category=%s source=%s destination=%s outcome=%s", kind, source, destination, outcome)
        return results
    finally:
        _release_owned_lock(lock, owner)
