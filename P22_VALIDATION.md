# P.22 packaged executable validation

Status: **In progress — physical-PC validation exposed an intermittent browser runtime crash; clean-Windows validation has not passed.**

## P.22.1 runtime diagnostic increment

On a second physical Windows PC, the packaged executable launched successfully,
its SHA-256 matched the original build, and Playwright opened the configured
Chrome or Edge default browser. After several minutes, or sometimes when the
window was maximized, the browser closed unexpectedly and the application
reported a browser-closed error. The root cause is not yet determined.

Persistent rotating diagnostics were added for evidence collection. They record
startup/runtime identity, default-browser resolution and non-secret launch
options, generation-scoped browser/page/context lifecycle events, navigation and
filter completion, exceptions with tracebacks, shutdown classification, and
cleanup state. This is diagnostic-only: no browser flags, channels, retry,
relaunch, synchronization, generation protection, or UI semantics were changed.

Use `P22_CLEAN_WINDOWS_CHECKLIST.md` to execute and record the remaining manual
validation when a separate physical Windows 10 or Windows 11 computer is
available. A VirtualBox validation attempt was discontinued because the VM setup
was unreliable and repeatedly returned to Windows installation. Virtual machines
are no longer part of the planned validation approach. No clean-machine result is
currently available.

Build identity: 2026-07-11, SHA-256
`9DE470B81A7F591BC261FAB5BE8EF9B21AF70F5972A52C244A640FAD25D0E137`.

Test environment: Windows NT 10.0.26200.0, Europe/Kyiv, medium-integrity
non-administrator sandbox user. This is the project development machine; Python
3.14.6 and the project virtual environment are installed. It is **not** a clean
Windows machine or VM.

Build command (repository root):

```bat
call .venv\Scripts\activate.bat && call build.bat
```

PyInstaller 6.21.0 completed successfully. The onedir package contained 1,214
files. `dist\PrismaFunction\PrismaFunction.exe` (14,048,940 bytes),
`_internal\python314.dll`, PySide6 QtCore/QtWidgets modules,
`_internal\PySide6\plugins\platforms\qwindows.dll`, and Playwright's
`driver\node.exe` were present.

## Validation matrix

| P.22 scenario | Status | Command/action and objective evidence |
|---|---|---|
| Clean documented build | Pass | Activated `.venv`, ran `build.bat`; clean PyInstaller build exited 0. |
| Package/runtime contents | Pass | Recursively inspected `dist\PrismaFunction`; executable and runtime files listed above were present. |
| Launch packaged executable directly | Pass (limited) | `Start-Process dist\PrismaFunction\PrismaFunction.exe`; process remained alive for 5 seconds without invoking `app.py` or Python. |
| Launch from a path containing spaces | Pass (limited) | Copied the package to `%TEMP%\Prisma Function P22` and launched its executable with `%TEMP%` as the working directory; process remained alive for 5 seconds. |
| Launch without administrator rights | Pass (limited) | Both launches ran at Medium Mandatory Level as a non-admin sandbox user. |
| PySide6/Qt platform plugin loading | Blocked | `qwindows.dll` is packaged and the process remained alive, but this session exposed no GUI window handle; visible rendering could not be observed. |
| Application startup and shutdown | Blocked | Startup process survival passed; the session exposed no window handle, so a graceful UI close could not be sent or observed. Forced termination was used only to clean up validation processes. |
| Valid CSV selection/loading | Blocked | Interactive packaged GUI was not accessible from this session. Existing automated CSV/UI tests are supporting evidence only, not packaged-executable validation. |
| Invalid and empty CSV handling | Blocked | Same interactive limitation. |
| Monitoring start/stop against a safely available target | Blocked | Same interactive limitation; no live target workflow was exercised. |
| Cleanup after shutdown | Blocked | Graceful packaged shutdown was not observable. Validation processes were forcibly stopped and no process was intentionally left running. |
| Writable database/result/log paths | Pass (development-host location only) | Created `data\result` and a probe file beside the copied package as the non-admin user. P.22.1 adds logs under `%LOCALAPPDATA%\PrismaFunction\logs`, with a `%TEMP%\PrismaFunction\logs` fallback; physical-PC verification of the new diagnostic build and protected install locations remains outstanding. |
| Retry after recoverable failure | Blocked | Packaged UI retry was not exercised; unit tests cover retry behavior but do not replace this manual check. |
| Currently configured default browser | Blocked | This sandbox user's `HKCU\...\http\UserChoice` key is absent, so no supported default browser is configured for the executable to launch. |
| No-Python/no-development-environment machine | Blocked | This machine has Python and the project environment installed. |

## Remaining clean-machine work

Complete `P22_CLEAN_WINDOWS_CHECKLIST.md` against this exact onedir package on a
separate physical Windows computer and attach the recorded environment, outcomes,
and evidence here. This work is deferred until that computer is available. P.22
remains in progress because its acceptance criteria require a genuinely clean
Windows environment. Collect the P.22.1 persistent log during reproduction; the
diagnostic increment itself does not establish a passing clean-Windows result.
