# P.22 clean-Windows package validation checklist

Use this checklist on a separate physical Windows 10 or Windows 11 computer when one is available. VirtualBox validation was discontinued because the VM setup was unreliable and repeatedly returned to Windows installation; virtual machines are no longer part of the planned validation approach. The test account must be a standard, non-administrator account, and the computer must not have Python, the project virtual environment, or developer tools installed. Test the existing complete `dist\PrismaFunction` onedir package; do not rebuild it on the clean computer.

## Test record

- [ ] Date and tester:
- [ ] Build identifier/version or source commit supplied with the package:
- [ ] Expected package archive or `PrismaFunction.exe` SHA-256:
- [ ] Actual SHA-256 (`Get-FileHash <path> -Algorithm SHA256`):
- [ ] Hash matches the supplied value.
- [ ] Windows edition, version, OS build, and architecture:
- [ ] Test account is non-administrator:
- [ ] Python, the project virtual environment, and developer tools are absent.
- [ ] Chrome version (or `Not installed`):
- [ ] Edge version (or `Not installed`):
- [ ] Configured Windows default browser:
- [ ] Package archive source and final extracted package location:
- [ ] Evidence location (screenshots, screen recording, generated files, and notes):

## Package transfer and startup

- [ ] Transfer the archive or complete `dist\PrismaFunction` directory. If archived, extract the entire onedir package; do not copy or launch `PrismaFunction.exe` by itself.
- [ ] Confirm `PrismaFunction.exe` and `_internal` remain together and the recorded SHA-256 still matches after transfer.
- [ ] Place a copy in a writable path containing spaces, for example `%USERPROFILE%\Desktop\Prisma Function P22\PrismaFunction`.
- [ ] Without using **Run as administrator**, launch `PrismaFunction.exe` from that path and record any Windows security prompt.
- [ ] Confirm it starts and remains usable without installing or locating Python and without a missing-runtime, DLL, or Qt plugin error.
- [ ] Confirm visible UI, dialogs, status text, and errors are in English, and the main window has a usable compact layout with no clipped or overlapping controls at the tested display scaling.

## Browser behavior

Record the default-browser setting and browser version for each applicable run.

- [ ] With Chrome as the Windows default HTTP/HTTPS browser, select **Open PRISMA** and confirm the application detects and launches Chrome.
- [ ] With Edge as the Windows default HTTP/HTTPS browser, select **Open PRISMA** and confirm the application detects and launches Edge.
- [ ] Set an installed browser other than Chrome or Edge as default. Select **Open PRISMA** and confirm the application stays responsive and shows a clear English unsupported-browser error without launching the wrong browser.
- [ ] Restore Chrome or Edge as default and confirm a retry launches the supported browser.

## CSV, processing, and monitoring

- [ ] Keep a supplied valid `Auction_overview.csv` and create an invalid copy (for example, remove a required column). Preserve both as evidence.
- [ ] Select the valid file; confirm the filename, loaded record count, table contents, and enabled actions are plausible and no error appears.
- [ ] Select the invalid file; confirm a clear English validation error appears, the application remains responsive, and the previously loaded valid filename, rows, and result/state remain intact and usable.
- [ ] With the valid CSV loaded and a supported browser open, select **Start Monitoring**. Confirm monitoring state and controls change correctly and the UI remains responsive.
- [ ] Select **Stop Monitoring**. Confirm monitoring stops, controls return to a usable state, and no browser or worker activity continues unexpectedly.
- [ ] If the environment permits processing the supplied CSV, select **Process CSV**, confirm success, and verify **Open Result** opens the generated workbook. Record an environment limitation instead of treating an unperformed step as a pass.

## Local storage and shutdown

- [ ] Verify the application creates and updates `%LOCALAPPDATA%\PrismaFunction\data\prisma_monitor.db` and `%LOCALAPPDATA%\PrismaFunction\data\result\prisma_auctions.xlsx`, with no writes beside the packaged executable.
- [ ] Confirm the diagnostic log is written to `%LOCALAPPDATA%\PrismaFunction\logs\prisma-function.log`; an unavailable user-data directory must produce a visible error rather than a `%TEMP%` or install-directory fallback.
- [ ] Close normally, including once after monitoring has run. Confirm the window closes cleanly and Task Manager shows no remaining `PrismaFunction.exe` or browser process started by the application.
- [ ] Relaunch after shutdown and confirm the application remains usable.

## Outcome and failures

- [ ] Overall outcome: `Pass`, `Fail`, or `Blocked` (do not use `Pass` for an unperformed or inaccessible case).
- [ ] Record every failed or blocked item with the checklist item, expected result, actual result, exact reproduction steps, frequency, relevant paths/settings, evidence, and error text copied exactly.
- [ ] Record whether Chrome, Edge, and unsupported-default-browser cases were each tested; list every outstanding case.
- [ ] Attach the completed checklist and evidence to the P.22 validation record.

The partial physical Windows P.28 run performed on 2026-07-18 is recorded in
`P28_VALIDATION_2026-07-18.md`. It is supporting evidence only and does not
satisfy this clean-environment checklist or mark P.22/P.28 as passed.
