from pathlib import Path

from validate_package import REQUIRED_PATHS, validate_distribution


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "PrismaFunction.spec"
BUILD_SCRIPT = ROOT / "build.bat"
REQUIREMENTS = ROOT / "requirements.txt"
VERSION = ROOT / "version.py"
VERSION_RESOURCE = ROOT / "PrismaFunction.version"
RELEASE_SCRIPT = ROOT / "release.ps1"
RELEASE_WRAPPER = ROOT / "release.bat"


def test_spec_configures_windows_gui_application():
    assert SPEC.is_file()
    content = SPEC.read_text(encoding="utf-8")

    assert '["app.py"]' in content
    assert 'name="PrismaFunction"' in content
    assert "console=False" in content
    assert 'collect_submodules("playwright")' in content
    assert 'collect_data_files("playwright")' in content
    assert "COLLECT(" in content
    assert 'version="PrismaFunction.version"' in content
    assert 'excludes=["pytest", "_pytest", "setuptools"]' in content


def test_distribution_validator_accepts_complete_runtime(tmp_path):
    for relative in REQUIRED_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")
    (tmp_path / "_internal" / "python314.dll").write_bytes(b"runtime")

    assert validate_distribution(tmp_path) == []


def test_distribution_validator_rejects_missing_developer_and_runtime_files(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("", encoding="utf-8")
    (tmp_path / "prisma_monitor.db").write_bytes(b"")

    errors = validate_distribution(tmp_path)

    assert errors[: len(REQUIRED_PATHS)] == [
        f"Missing required package file: {relative}" for relative in REQUIRED_PATHS
    ]
    assert "Missing required package file: _internal/python3*.dll" in errors
    assert "Writable runtime file in package: prisma_monitor.db" in errors
    assert "Developer-only path in package: tests/test_app.py" in errors
    assert "Forbidden file type in package: tests/test_app.py" in errors


def test_distribution_validator_rejects_sqlite_sidecars_and_rotated_logs(tmp_path):
    runtime_files = (
        "data/prisma_monitor.db",
        "data/prisma_monitor.db-shm",
        "data/prisma_monitor.db-wal",
        "logs/prisma-function.log",
        "logs/prisma-function.log.1",
        "logs/prisma-function.log.2",
        "logs/prisma-function.log.3",
    )
    for relative in runtime_files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime output")

    errors = validate_distribution(tmp_path)

    runtime_errors = [
        error for error in errors if error.startswith("Writable runtime file in package:")
    ]
    assert runtime_errors == [
        f"Writable runtime file in package: {relative}" for relative in runtime_files
    ]


def test_distribution_validator_accepts_similarly_named_dependencies(tmp_path):
    for relative in REQUIRED_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")
    (tmp_path / "_internal" / "python314.dll").write_bytes(b"runtime")
    (tmp_path / "_internal" / "prisma_monitor.dbapi.dll").write_bytes(b"runtime")
    (tmp_path / "_internal" / "prisma-function.log.config").write_bytes(b"runtime")

    assert validate_distribution(tmp_path) == []


def test_authoritative_stable_version_matches_executable_metadata():
    namespace = {}
    exec(VERSION.read_text(encoding="utf-8"), namespace)
    assert namespace["__version__"] == "1.0.0"
    metadata = VERSION_RESOURCE.read_text(encoding="utf-8")
    assert 'StringStruct("FileVersion", "1.0.0")' in metadata
    assert 'StringStruct("ProductVersion", "1.0.0")' in metadata
    assert "filevers=(1, 0, 0, 0)" in metadata


def test_pyinstaller_is_a_pinned_dependency():
    requirements = REQUIREMENTS.read_text(encoding="utf-8").splitlines()

    assert any(line.lower().startswith("pyinstaller==") for line in requirements)


def test_build_script_invokes_pyinstaller_with_spec():
    content = BUILD_SCRIPT.read_text(encoding="utf-8").lower()

    assert "-m pyinstaller" in content
    assert "prismafunction.spec" in content
    assert 'cd /d "%~dp0"' in content
    assert 'rmdir /s /q "build"' in content
    assert 'rmdir /s /q "dist"' in content
    assert ".venv\\scripts\\python.exe" not in content
    assert "if errorlevel 1 exit /b %errorlevel%" in content


def test_release_wrapper_runs_powershell_from_repository_root():
    content = RELEASE_WRAPPER.read_text(encoding="utf-8").lower()
    assert 'cd /d "%~dp0"' in content
    assert '-file "%~dp0release.ps1"' in content
    assert "if errorlevel 1 exit /b %errorlevel%" in content


def test_release_script_contract_is_versioned_deterministic_and_filtered():
    content = RELEASE_SCRIPT.read_text(encoding="utf-8")
    assert '"dist\\PrismaFunction"' in content
    assert '"PrismaFunction.exe"' in content
    assert '"PrismaFunction-v$Version-windows-x64.zip"' in content
    assert '"PrismaFunction/$Relative"' in content
    assert "Sort-Object" in content
    assert "2000, 1, 1" in content
    assert "Get-FileHash" in content and "SHA256" in content
    for excluded in (".csv", ".log", ".pyc", ".venv", "__pycache__"):
        assert excluded in content
