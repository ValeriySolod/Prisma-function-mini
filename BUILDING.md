# Windows application build

## Prerequisites

- Windows;
- Python with the `py` launcher;
- an active Python environment with the pinned project dependencies.

Create the environment and install dependencies using the project's existing
setup command:

```bat
setup.bat
```

Then activate that environment before building:

```bat
.venv\Scripts\activate.bat
```

## Build

Run the Windows build script from the repository root:

```bat
build.bat
python validate_package.py
```

The windowed application and its supporting files are written to
`dist\PrismaFunctionMini\`. The executable is expected at
`dist\PrismaFunctionMini\PrismaFunctionMini.exe`.

The Playwright Python modules needed by the application are included. The
application uses an installed system-default Chrome or Edge browser; browser
binaries are not bundled. A successful build does not replace the manual
release-readiness checks in `RELEASE_CHECKLIST.md`.

Verify the Windows executable metadata in PowerShell:

```powershell
$exe = Get-Item .\dist\PrismaFunctionMini\PrismaFunctionMini.exe
if ($exe.VersionInfo.FileVersion -ne "0.1.0" -or $exe.VersionInfo.ProductVersion -ne "0.1.0") { throw "Executable version metadata mismatch." }
if ($exe.VersionInfo.ProductName -ne "Prisma Function Mini" -or $exe.VersionInfo.OriginalFilename -ne "PrismaFunctionMini.exe") { throw "Executable identity metadata mismatch." }
Write-Host "Executable metadata verified."
```

For a local packaged startup smoke check, use a new writable data root and a
working directory outside the repository. This checks that startup does not
use the source tree, active virtual environment, current directory, or the
distribution directory for writable data:

```powershell
$smokeRoot = Join-Path $env:TEMP "PrismaFunctionMini-smoke"
$packagedExe = (Resolve-Path .\dist\PrismaFunctionMini\PrismaFunctionMini.exe).Path
New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null
$originalLocalAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA", "Process")
$originalLocation = Get-Location
try {
    $env:LOCALAPPDATA = $smokeRoot
    Set-Location -LiteralPath $env:TEMP
    & $packagedExe
} finally {
    if ($null -eq $originalLocalAppData) {
        Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue
    } else {
        $env:LOCALAPPDATA = $originalLocalAppData
    }
    Set-Location -LiteralPath $originalLocation
}
```

When using a different repository location, replace the executable path with
its absolute path. Confirm the main window opens without a console window, then
close it normally. Verify that logs and any generated data are below
`$smokeRoot\PrismaFunctionMini` and that `dist\PrismaFunctionMini` remains unchanged.
This is a same-machine smoke check, not clean-machine validation.

## Prepare and create the release archive

Version `0.1.0` is defined in `version.py`. Before preparing a release, start
from a clean working tree, activate the project environment, and run the full
validation commands below. Then build and archive from the repository root:

```bat
build.bat
release.bat
```

`release.bat` requires the successful onedir build at
`dist\PrismaFunctionMini\PrismaFunctionMini.exe`. It uses Windows PowerShell and .NET;
no external archive program is required. It creates these ignored outputs:

```text
release\PrismaFunctionMini-v0.1.0-windows-x64.zip
release\PrismaFunctionMini-v0.1.0-windows-x64.zip.sha256
```

The ZIP has `PrismaFunctionMini\` as its top-level directory. Its entries are
sorted and use a fixed timestamp for reproducible archive input. Runtime CSV,
log, cache, temporary, output, and virtual-environment files are excluded.

Verify the checksum in PowerShell from the repository root:

```powershell
$expected = (Get-Content .\release\PrismaFunctionMini-v0.1.0-windows-x64.zip.sha256).Split()[0]
$actual = (Get-FileHash .\release\PrismaFunctionMini-v0.1.0-windows-x64.zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "SHA-256 checksum mismatch." }
Write-Host "SHA-256 verified: $actual"
```

Inspect the archive before publication and complete every manual item in
`RELEASE_CHECKLIST.md`. The Git tag and GitHub Release are post-merge actions.

## Reproduce Windows CI locally

From an activated environment with `requirements.txt` installed, run these
checks from the repository root:

```bat
set QT_QPA_PLATFORM=offscreen
set PYTHONUTF8=1
python -m pytest -q tests\test_packaging.py
python -m pytest -q
python -m compileall -q app.py auction_csv.py browser.py csv_contracts.py monitoring.py monitoring_storage.py notifications.py prisma_import_workflow.py prisma_page.py prisma_references.py prisma_source_updates.py processor.py runtime_logging.py runtime_paths.py scheduler.py storage.py ui_components.py validate_package.py version.py tests
python -m PyInstaller --clean --noconfirm PrismaFunctionMini.spec
python validate_package.py
```

The packaging command validates the checked-in PyInstaller configuration and
writes an unarchived build to `dist\PrismaFunctionMini\`; CI does not publish or
upload it. Playwright browser binaries are not required by these checks.

Source and packaged runs write application-owned data only below
`%LOCALAPPDATA%\PrismaFunctionMini`; they do not require the repository or install
directory to be writable. Mini does not scan, copy, move, overwrite, or delete
historical `%LOCALAPPDATA%\PrismaFunction` data automatically. See
`M3_IDENTITY_AND_RUNTIME_BOUNDARY.md` for the migration decision.
