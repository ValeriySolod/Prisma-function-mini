# P.28 packaged-application validation record — 2026-07-18

Overall status: **Partial / Blocked — not Pass**.

This record covers a physical Windows test of source commit `22d34a0` using
`PrismaFunction-v1.0.0-windows-x64.zip`. The expected and transferred archive
SHA-256 values matched:

```text
801bc0ad6610f51989e1a9fccc01cce86c4bb41029ae99d6b97042396d0c6fd4
```

## Environment

- Windows 10 Pro, build 26200, 64-bit.
- Test account: `TEST\portm`.
- The executable was launched non-elevated from
  `C:\Users\portm\Desktop\Prisma Function P28 Partial 20260718\PrismaFunction\PrismaFunction.exe`.
- Python 3.14.2, Git, and GitHub CLI were installed on the computer.
- The account belongs to the local Administrators group.

The installed developer tools and administrator-group membership mean this was
not the fully clean, standard-user environment required to complete P.28.

## Validation results

| Tested area | Status | Recorded evidence |
|---|---|---|
| Archive identity and transfer | Pass | The transferred archive checksum matched the recorded SHA-256 for the named package. |
| Non-elevated startup from a path containing spaces | Pass | The packaged executable launched successfully without elevation. No missing Python runtime, DLL, Qt, or Playwright packaging error occurred. |
| English UI and layout | Pass | The UI rendered correctly in English without clipping or overlap. |
| Chrome detection and launch | Pass | Chrome was detected and launched successfully. |
| Public PRISMA navigation and filtering | Pass | The public PRISMA Auctions page opened with `Marketed >= 1000`. |
| Monitoring: stale live-table IDs | Pass | The first attempt used auction IDs that had already disappeared from the live table. It correctly returned typed not-found errors and was not classified as an application defect. |
| Monitoring: current IDs | Pass | A second attempt used auction IDs `62621303` and `62653952`. The first successful cycle reported 2 checked, 2 changed, 0 errors; `Finished` was normalized to `Completed`. Later cycles reported 2 checked, 0 changed, 0 errors and `Success` results. Monitoring stopped cleanly. |
| Header-only PRISMA export | Pass (limited) | A 719-byte header-only export was accepted with 0 processed rows and produced a valid header-only workbook. No data-row import was tested. |
| Generated workbook | Pass | **Open Result** opened `prisma_auctions.xlsx` successfully in OpenOffice Calc. The `Auctions` worksheet contained 16 headers. |
| Runtime data locations | Pass | The runtime database, workbook, and log were created below `%LOCALAPPDATA%\PrismaFunction`. No runtime database, workbook, state, or log artifacts were written beside the packaged executable. |
| Browser and application cleanup | Pass | **Stop Browser** and normal application shutdown left no `PrismaFunction` process or Playwright-managed Chrome process. |
| Migration lock cleanup | Pass with observation | No active `.migration.lock` remained. One best-effort `.migration.lock.stale-*` quarantine directory remained; it did not block startup or shutdown. This is an observation, not a confirmed defect. |
| Relaunch | Pass | Relaunch succeeded. |
| Restart baseline revalidation | Blocked | The live auction IDs disappeared before the repeated check, so the restart baseline could not be revalidated. |
| Fully clean physical Windows environment | Blocked | Python 3.14.2, Git, and GitHub CLI were installed, and the non-elevated test account was a member of the local Administrators group. |
| Browser coverage | Blocked | Chrome passed. Edge and unsupported-default-browser cases were not tested. |
| PRISMA export data-row coverage | Blocked | The tested export contained no data rows. |

## Conclusion and remaining work

The tested package passed the exercised startup, UI, Chrome, live monitoring,
header-only import, workbook, runtime-path, cleanup, and relaunch checks. P.28
remains **In progress** because the result is Partial / Blocked: repeat the full
checklist on a physical Windows computer without developer tools, using a
standard non-administrator account; exercise a PRISMA export containing data
rows; test Edge and an unsupported default browser; and revalidate the persisted
monitoring baseline after restart with auction IDs that remain live.

This record does not mark P.22, P.28, or the release checklist as fully passed.
