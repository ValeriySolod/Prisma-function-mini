from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "PrismaFunction.iss"
BUILD_INSTALLER = ROOT / "build-installer.bat"


def test_installer_is_per_user_versioned_and_uses_packaged_distribution():
    content = INSTALLER.read_text(encoding="utf-8")

    assert '#define AppVersion GetFileVersion(' in content
    assert 'DefaultDirName={localappdata}\\Programs\\{#AppInternalName}' in content
    assert "PrivilegesRequired=lowest" in content
    assert 'Source: "{#AppSourceDir}\\*"' in content
    assert "recursesubdirs" in content
    assert "createallsubdirs" in content
    assert 'Filename: "{app}\\{#AppExeName}"' in content


def test_installer_provides_start_menu_optional_desktop_and_uninstaller():
    content = INSTALLER.read_text(encoding="utf-8")

    assert 'Name: "{group}\\{#AppDisplayName}"' in content
    assert 'Name: "desktopicon"' in content
    assert "Flags: unchecked" in content
    assert 'Name: "{autodesktop}\\{#AppDisplayName}"' in content
    assert "UninstallDisplayIcon={app}\\{#AppExeName}" in content
    assert "SignedUninstaller=yes" in content
    assert "SignTool={#SignToolName}" in content


def test_installer_does_not_delete_or_source_runtime_and_developer_paths():
    content = INSTALLER.read_text(encoding="utf-8").lower()

    assert "[uninstalldelete]" in content
    assert "{localappdata}\\prismafunction" in content
    forbidden_sources = (
        "source: \"*.py\"",
        "source: \"tests",
        "source: \"data",
        "source: \"logs",
        "source: \"release",
        "source: \".venv",
    )
    assert not any(source in content for source in forbidden_sources)
    assert "deleteafterinstall" not in content


def test_installer_build_wrapper_validates_package_and_handles_spaces():
    content = BUILD_INSTALLER.read_text(encoding="utf-8").lower()

    assert 'cd /d "%~dp0"' in content
    assert "python validate_package.py" in content
    assert '"%iscc%" %sign_arg% "prismafunction.iss"' in content
    assert "inno_setup_compiler" in content
    assert "inno_signtool_name" in content
    assert "if errorlevel 1 exit /b %errorlevel%" in content
