# PrismaFunction v1.0.0 release notes

PrismaFunction is a compact Windows desktop application for loading PRISMA
auction CSV data, processing it into a local Excel result, and monitoring live
auction status through the user's browser.

## Highlights

- PySide6 desktop UI with English controls, statuses, and error messages.
- Automatic use of the Windows default Google Chrome or Microsoft Edge.
- CSV validation, local persistence, Excel export, and live PRISMA monitoring.
- Safe Start/Stop Monitoring and managed-browser cleanup without closing
  unrelated browser windows.
- Windowed PyInstaller onedir package with application and executable version
  metadata.
- Runtime diagnostic logs for packaged-operation troubleshooting.

## Operational requirements and limitations

- A supported 64-bit Windows environment and an installed Chrome or Edge set
  as the default browser are required.
- The application automates the installed browser; Playwright browser binaries
  are not bundled in the archive.
- Authentication-required PRISMA content may require the user to sign in.
- Website or browser changes can interrupt a live lookup; the application
  reports bounded timeout, unavailable-page, and changed-page-structure errors.
- Release validation on a second Windows PC remains a manual prerequisite for
  publishing v1.0.0.

## Integrity verification

The release includes
`PrismaFunction-v1.0.0-windows-x64.zip.sha256`. Compare its first field with
the SHA-256 value returned by Windows PowerShell `Get-FileHash` before opening
or distributing the ZIP. Exact commands are in `BUILDING.md`.
