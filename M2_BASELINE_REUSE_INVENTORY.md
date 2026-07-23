# M.2 Baseline and Reuse Inventory

## 1. Purpose and evidence basis

This document is the M.2 analysis deliverable for Prisma Function Mini. It
classifies the inherited Prisma-function repository before any production code
is adapted or removed. M.2 changes no runtime behavior.

The inventory was produced from the checked-in files on 2026-07-20. Evidence
was taken from production definitions and imports, the assertions in every test
module, the Mini sources of truth, packaging definitions, validation records,
and the runtime path and SQLite schema implementations. Test counts below count
top-level `test_*` functions; parametrized cases may execute more cases than the
listed function count. Existing automated and manual evidence is historical
Prisma-function evidence only. It does not prove the future Mini application.

Classification terms are exact:

- **Reuse unchanged**: the present contract matches an approved Mini contract.
- **Reuse after Mini-specific adaptation**: useful behavior exists, but identity,
  input/output, orchestration, or ownership must change and be retested.
- **Monitoring-only and remove later**: excluded by the Mini specification; keep
  it intact until M.13 so shared dependencies can be separated safely.
- **Obsolete or replace**: not an approved Mini implementation or authority.
- **Requires further real-PRISMA or Windows evidence**: code or historical tests
  cannot establish the required external behavior.

## 2. Production module inventory

| Component | Classification | Evidence and Mini disposition |
|---|---|---|
| `app.py` | Obsolete or replace | `PrismaMonitorApp` is a monitoring dashboard with manual Monitoring CSV selection, Start/Stop Monitoring, live-result activity, and a manual PRISMA Export CSV import. Mini needs a date-range-first state machine and a different worker workflow. Qt signal, polling, cancellation, and deferred-close patterns may inform M.7/M.11, but the class is not a Mini shell. |
| `auction_csv.py` | Monitoring-only and remove later | Defines and validates the UTF-8 Monitoring CSV (`AuctionCsvRecord`). It is not the official cp1252 PRISMA export contract and has no Mini input role. |
| `browser.py` | Requires further real-PRISMA or Windows evidence | Owns a generation-safe Playwright lifecycle, default Chrome/Edge executable detection, cancellation, cleanup, session validation, and an inherited `Marketed >= 1000` PRISMA filter that Mini must not reuse. It always launches `headless=False`, maximized, and serves live monitoring rather than date-filtered download. Reuse requires M.8 adaptation and real evidence for background/headless behavior, date filters, authentication state, and download ownership. |
| `csv_contracts.py` | Reuse after Mini-specific adaptation | Exact header, delimiter, encoding, duplicate-header, partial-header, empty-file, and wrong-kind detection is useful. The combined detector also exposes the excluded Monitoring CSV format; Mini should retain the official PRISMA-export boundary without routing monitoring input through the product path. |
| `monitoring.py` | Monitoring-only and remove later | `MonitoringEngine` compares live statuses and produces monitoring results. Status monitoring is explicitly excluded. |
| `monitoring_storage.py` | Monitoring-only and remove later | Owns `monitoring_checks`, `monitoring_status_transitions`, and `monitoring_latest_status` in the shared database. These tables and semantics are excluded, not Mini history or operation audit. |
| `notifications.py` | Monitoring-only and remove later | Creates user-visible status-change notifications from persisted monitoring transitions. Notifications are excluded. |
| `prisma_import_workflow.py` | Reuse after Mini-specific adaptation | Provides recoverable ordering across source validation, SQLite operation state, auction mutation, staged/validated Excel publication, and final acceptance. It accepts a user-selected local file plus one `source_date`, contains Monitoring CSV messaging, and publishes the inherited workbook/schema. M.11 must orchestrate an automatically downloaded file tied to a requested range and the approved Mini audit. |
| `prisma_page.py` | Requires further real-PRISMA or Windows evidence | Session/authentication/readiness errors and sanitized location diagnostics are reusable concepts. The live table lookup and status normalization are monitoring-only. Real PRISMA DOM evidence is required before selecting readiness landmarks, date-filter controls, changed-DOM outcomes, and download behavior for M.8-M.10. |
| `prisma_references.py` | Reuse unchanged | Immutable, exact, side-aware Market/Storage aliases reject duplicate/conflicting aliases and do no fuzzy or cross-side matching. The two Market aliases are backed by `evidence/p35-1/EVIDENCE_MANIFEST.md`; Storage aliases are explicitly derived from `RESERVOIR` rows. Preserve this catalog and its fail-closed policy unless new authoritative evidence is separately approved. |
| `prisma_source_updates.py` | Reuse after Mini-specific adaptation | Immutable source identity, exact SHA-256 retry, changed-during-import detection, typed accepted/rejected outcomes, and basename-only metadata are useful. Its policy allows only one source per single source date, rejects older dates, and was designed for caller-supplied daily files; Mini must audit requested ranges and allow safe overlapping ranges. |
| `processor.py` | Reuse after Mini-specific adaptation | Strict cp1252 parsing, row accounting, selected-side network-point identity, capacity/tariff normalization, threshold filtering, product normalization, and authoritative enrichment are strong foundations. Its row/output contract feeds the inherited 16-column storage/workbook rather than the approved Mini 11-column contract, so M.4 must reconcile names, types, units, duration, ordering, and reason codes before reuse. |
| `runtime_logging.py` | Reuse after Mini-specific adaptation | Rotating logging, sensitive-value-safe browser diagnostics, and fail-safe logging behavior are useful. Logger/file/application identities are `prisma_function` and `prisma-function.log`; Mini identity and final no-fallback policy must be verified in M.3. |
| `runtime_paths.py` | Reuse after Mini-specific adaptation | Provides absolute `%LOCALAPPDATA%` resolution, deterministic fallback, explicit directories, migration locking, atomic file migration, SQLite Backup API handling, integrity checks, and conflict preservation. Every current destination is below `%LOCALAPPDATA%\PrismaFunction` and filenames/schema include monitoring identity. M.3 must create a Mini root and make an explicit, tested migration decision rather than automatically adopting or moving old data. |
| `scheduler.py` | Monitoring-only and remove later | Periodically invokes `MonitoringEngine`; scheduling is excluded. |
| `storage.py` | Reuse after Mini-specific adaptation | Uses `BEGIN IMMEDIATE`, foreign keys, a uniqueness constraint matching the five stable identity fields, rollback/error preservation, operation states, cumulative rows, and staged `os.replace` workbook publication. The `auctions` table and workbook contain inherited fields (including TSO, premium, and state), the export has 16 headers rather than 11, `prisma_source_operations` is unique by one `source_date`, and legacy/backfill tables are Prisma-function-specific. M.5/M.6 require a Mini schema, migration decision, audit counts, conflict contract, and approved workbook mapping. |
| `ui_components.py` | Reuse after Mini-specific adaptation | Centralized PySide6 styling and custom widgets may be reused selectively. Current styles and controls were designed for the monitoring dashboard; M.7 must retain only components that fit the minimal date-range UI and accessibility contract. |
| `validate_package.py` | Reuse after Mini-specific adaptation | Deterministically checks required Qt/Playwright runtime files and excludes source, test, log, CSV, SQLite, and workbook artifacts. Distribution, executable, database, workbook, log, and diagnostic strings all use old identity and must change in M.3/M.14. |
| `version.py` | Obsolete or replace | Authoritative inherited identity is `PrismaFunction`, `PRISMA Monitor`, version `1.0.0`. M.3 must define the Mini identity; the old values must not remain authoritative. |

## 3. Test-group inventory and authority

“Authoritative” means the invariant remains valuable for a future Mini test. It
does not mean the current test can remain unchanged or that it proves real
PRISMA, packaged, Excel, installer, or clean-machine behavior.

| Test group | Test functions | Classification | Authority and gap |
|---|---:|---|---|
| `tests/test_app.py` | 34 | Monitoring-only and remove later | Most assertions describe the old dashboard, Monitoring CSV, monitoring lifecycle, and old labels. Preserve only as regression protection while separating shared shutdown/import behavior; replace with M.7 Mini UI/state tests. |
| `tests/test_auction_csv.py` | 23 | Monitoring-only and remove later | Authoritative only for the excluded Monitoring CSV contract. |
| `tests/test_browser.py` | 30 | Requires further real-PRISMA or Windows evidence | Strong authority for executable detection, generation isolation, lifecycle cleanup, cancellation, sanitized diagnostics, typed auth/session failures, and recovery. Fake pages prove adapter logic only; visible/background behavior, date filtering, and downloads remain unproved. |
| `tests/test_csv_contracts.py` | 12 | Reuse after Mini-specific adaptation | Exact official-export encoding/header/error cases remain authoritative. Monitoring-format cases become separation/removal guards. |
| `tests/test_installer.py` | 4 | Reuse after Mini-specific adaptation | Per-user install, shortcuts, preservation of runtime data, and path-with-spaces wrapper rules remain authoritative after all identities/paths are changed. Structural text tests are not installed-app evidence. |
| `tests/test_monitoring.py` | 10 | Monitoring-only and remove later | Covers excluded live status comparison only. |
| `tests/test_monitoring_storage.py` | 16 | Monitoring-only and remove later | Covers excluded checks/transitions/latest-status tables. Transaction, rollback, and concurrency ideas should be represented independently in Mini storage tests, not retained through monitoring schema. |
| `tests/test_notifications.py` | 2 | Monitoring-only and remove later | Covers excluded status notifications only. |
| `tests/test_packaging.py` | 10 | Reuse after Mini-specific adaptation | Windowed onedir structure, runtime dependency presence, pinned PyInstaller, version consistency, deterministic release filtering, and absence of runtime writes remain authoritative after Mini renaming. Not a launch or clean-machine proof. |
| `tests/test_prisma_import_workflow.py` | 18 | Reuse after Mini-specific adaptation | Strong authority for wrong-contract rejection, ledger recovery, atomic publication, exact retry, rollback, and output validation. Fixtures/assertions use manual one-date input and inherited schema/workbook. |
| `tests/test_prisma_page.py` | 24 | Requires further real-PRISMA or Windows evidence | Sanitized authentication/readiness and typed live-page failures are useful; status-table parsing is monitoring-only. Synthetic DOM cannot authorize M.9 selectors. |
| `tests/test_prisma_references.py` | 25 | Reuse unchanged | Authoritative for exact side-aware aliases, Market/Storage classification, no fuzzy/substring matching, deterministic issue ordering, and catalog conflicts. |
| `tests/test_prisma_source_updates.py` | 15 | Reuse after Mini-specific adaptation | Authoritative for immutable SHA-256 identity, exact retry, source mutation/disappearance, timestamps, and deterministic typed outcomes; date/range policy must change. |
| `tests/test_processor.py` | 25 | Reuse after Mini-specific adaptation | Authoritative for strict official-export parsing, threshold/unit boundaries, direction/identity selection, row accounting, dates, tariffs, product types, and bad-row isolation. Expected output contract must be replaced by the 11-column Mini contract. |
| `tests/test_runtime_logging.py` | 5 | Reuse after Mini-specific adaptation | Authority for source/packaged log placement, no unsafe fallback, legacy conflict behavior, and logging failure isolation after Mini identity/path updates. |
| `tests/test_runtime_paths.py` | 18 | Reuse after Mini-specific adaptation | Strong authority for Windows path resolution, serialized/idempotent migration, conflict retention, WAL-safe SQLite backup, integrity, and independence from CWD/executable path. Current old-to-old migration fixtures cannot decide Mini historical migration. |
| `tests/test_scheduler.py` | 11 | Monitoring-only and remove later | Covers excluded periodic monitoring only. |
| `tests/test_storage.py` | 31 | Reuse after Mini-specific adaptation | Strong authority for stable uniqueness, atomic cumulative workbook, schema fingerprint/migration, rollback, foreign keys, concurrency, connection recovery, and historical data preservation. Schema and workbook expectations are not the Mini contract. |

No current test covers a Mini-selected start/end range, an automatically
downloaded source tied to that range, the approved 11-column workbook, a Mini
runtime root, Mini database migration, background/headless real PRISMA behavior,
or a Mini package/installer identity. Those are later roadmap exit criteria.

## 4. Documentation, data, and evidence inventory

| Files | Classification | Disposition |
|---|---|---|
| `AGENTS.md`, `ROADMAP.md`, `workflow_m.md`, `TECHNICAL_SPECIFICATION.md` | Reuse unchanged | Current Mini sources of truth. M.2 adds this inventory and updates only roadmap status/current-next text. |
| `workflow_p.md` | Obsolete or replace | Historical Prisma-function roadmap and implementation record. Useful provenance for inherited behavior, but not a Mini source of truth and heavily monitoring-oriented. Retain as historical reference until later cleanup is explicitly scoped. |
| `README.md` | Obsolete or replace | Ukrainian `PRISMA Monitor` instructions describe manual CSV selection, monitoring, repository-relative output, and future automatic download. Replace with Mini instructions when executable behavior exists. |
| `BUILDING.md`, `INSTALLER.md`, `RELEASE_CHECKLIST.md`, `RELEASE_NOTES_v1.0.0.md` | Reuse after Mini-specific adaptation | All carry old product/executable/archive/runtime names and monitoring workflows. Build/release safety concepts remain useful, but none is current Mini operating documentation. |
| `P22_VALIDATION.md`, `P22_CLEAN_WINDOWS_CHECKLIST.md`, `P28_VALIDATION_2026-07-18.md` | Requires further real-PRISMA or Windows evidence | Historical evidence only. P.22 includes limited/blocked GUI checks and an obsolete temporary-log statement; P.28 proves a Prisma-function package on one exercised environment, visible Chrome/live monitoring, a header-only import, OpenOffice (not Microsoft Excel), and `%LOCALAPPDATA%\PrismaFunction`. It does not prove Mini or clean-machine acceptance. |
| `evidence/p35-1/EVIDENCE_MANIFEST.md`, `evidence/p35-1/Auction_overview.csv`, `evidence/p35-1/Auction_Overview.pdf` | Reuse unchanged | Authoritative provenance for exactly two accepted side-specific Market aliases. Checked-in manifest hashes match the evidence files: CSV `c02a696672774a89d376a73478d68d2c9e8ce90b7f27a275fa960653c1da6cd6`; PDF `4bd3558cc2dc69dd09ab5f179cc9887664fc61e43ed09a0359612cc86f25ae80`. The manifest makes no completeness claim. |
| root `Auction_overview.csv` | Requires further real-PRISMA or Windows evidence | Byte-identical to the evidenced CSV by SHA-256, but its root placement is inherited developer/source evidence, not an automatically downloaded Mini runtime input. Packaging excludes CSV files. |
| `mapping.csv` | Obsolete or replace | Five manually named geographic/TSO mappings lack the required Auction-ID/PDF/side provenance and include a mojibake value. It must not be used as Mini mapping authority. |
| `requirements.txt`, `pytest.ini` | Reuse after Mini-specific adaptation | Current pinned runtime/test/build dependencies and Python test path are a reproducible baseline. Later increments must confirm which dependencies remain after monitoring removal; no dependency change belongs to M.2. |
| `.gitignore`, `.gitattributes` | Reuse after Mini-specific adaptation | General exclusions/EOL rules are useful, but ignored runtime patterns are repository-relative and do not establish the Mini runtime boundary. Review new Mini build/output names when introduced. |
| `data/result/.gitkeep` | Obsolete or replace | Preserves an inherited repository-relative output directory. Approved Mini runtime output belongs below `%LOCALAPPDATA%\PrismaFunctionMini`, never in this source-tree placeholder. |

## 5. Packaging and launch inventory

| Files | Classification | Evidence and required change |
|---|---|---|
| `PrismaFunction.spec` | Reuse after Mini-specific adaptation | Sound windowed onedir structure and Playwright collection; entry point, executable, collection, and version-resource names are old. |
| `PrismaFunction.version` | Obsolete or replace | Every Windows metadata field identifies PrismaFunction/PRISMA Monitor 1.0.0. |
| `PrismaFunction.iss` | Reuse after Mini-specific adaptation | Per-user, x64-compatible, runtime-preserving installer mechanics are useful. AppId, names, executable, source/output directories, shortcuts, publisher decision, and preserved runtime root are old. A new AppId/migration/upgrade policy requires an explicit M.3/M.14 decision. |
| `build.bat`, `build-installer.bat` | Reuse after Mini-specific adaptation | Safe repository-root wrappers, but all artifact/spec/executable names and validation commands target the old package. They also invoke global `python`; the canonical Mini build environment must be documented later. |
| `release.bat`, `release.ps1` | Reuse after Mini-specific adaptation | Deterministic ZIP ordering, fixed timestamps, filtering, and SHA-256 are useful. Release paths and archive root/name are old; the script performs destructive replacement only inside the intended release outputs. |
| `run.bat`, `setup.bat` | Reuse after Mini-specific adaptation | Development convenience only. Text still says old program, and setup upgrades pip from the network; neither is a packaged-user flow. |
| `validate_package.py` | Reuse after Mini-specific adaptation | See production inventory; package validation is structural only. |
| `.github/workflows/windows-ci.yml` | Reuse after Mini-specific adaptation | The Windows CI sequence is useful automated evidence, but its compile list, `PrismaFunction.spec`, distribution path, and old packaging tests must follow Mini identity and the eventual monitoring separation. Headless Qt and fake-browser tests are not real PRISMA, visible UI, package launch, installer, or clean-machine evidence. |

No package was built, launched, installed, or published for M.2. M.14 and M.15
must establish Mini-specific structural and physical evidence separately.

## 6. Runtime-data boundaries and migration risks

| Boundary today | Evidence | Mini risk and required decision |
|---|---|---|
| Root | `%LOCALAPPDATA%\PrismaFunction` from `runtime_paths.APP_DIRECTORY_NAME` | Must become the approved `%LOCALAPPDATA%\PrismaFunctionMini`. M.3 must prove there are no remaining writes to the old root. |
| SQLite | `data\prisma_monitor.db`; shared `auctions`, `prisma_source_operations`, historical Market/Storage audit, and monitoring tables | Reusing the file wholesale would carry excluded monitoring data and an incompatible operation/workbook schema. Starting empty could abandon historical auctions. M.3 must document whether migration is none, copy/transform, or explicit opt-in; M.5 must test it transactionally without mutating the old database. |
| Workbook | `data\result\prisma_auctions.xlsx`; generated from SQLite with 16 inherited columns | Mini requires 11 columns and cumulative preservation. An existing workbook cannot be treated as authoritative without reconciliation to SQLite and stable identity. M.6 must stage, validate, and atomically replace only after database success, preserving the previous valid workbook on failure/lock. |
| Legacy JSON state | `state\prisma_import_state.json`, plus migration from old repository/executable-relative locations | Represents accepted single-date manual sources, not Mini range audits. Do not silently import it into a Mini ledger without a documented compatibility transform. |
| Logs | `logs\prisma-function.log` with rotation; historical migration from `%TEMP%\PrismaFunction\logs` | Rename identity and keep credential/cookie/full-sensitive-URL exclusion. Failure must not redirect writes beside the executable or to an unapproved fallback. |
| Temporary download | No automatic-download boundary exists | M.10 must define an application-controlled temporary directory, partial-file handling, cancellation cleanup, hash capture, and the point at which the temporary source may be removed. It must never become cumulative history. |
| Source/install directory | Runtime migration scans a fixed list beside the source or packaged executable; package validator rejects runtime artifacts in `dist` | The inherited safety mechanism is useful, but Mini must not scan broadly, move unrelated files, or write beside its executable. Exact old/Mini roots and targets must be verified before migration. |

### Historical-data migration conclusion

There is not enough approved evidence in M.2 to choose automatic historical
migration. The old database mixes useful auction rows with excluded monitoring
tables, old workbook columns, and single-date source operations. Therefore M.3
must record an explicit migration policy and fixtures before any runtime path is
changed. Until then, the old root must be treated as read-only user data and no
code may silently copy, move, delete, rebuild, or reinterpret it.

## 7. External-evidence and delivery risk register

| Risk | Current evidence | Required later evidence |
|---|---|---|
| Browser visibility | Current controller explicitly launches a maximized visible browser. Historical P.28 exercised visible Chrome. | M.8: real PRISMA comparison of headless/background and, if necessary, managed unobtrusive visible behavior on Windows; lifecycle and cleanup evidence. |
| Date filter | No production code or test applies a Mini-selected start/end range. | M.9: sanitized real DOM evidence for both `Start of Auction` date controls, accepted interaction, Apply semantics, applied range, and typed changed-DOM failures. PRISMA Capacity automation is prohibited. |
| CSV download | No code awaits a Playwright download or validates a downloaded file against a requested range. Historical import is local/manual. | M.10: real response/download/blob behavior, filename/content contract, completeness, timeout, cancellation, retry, and audit binding. Do not automate credentials or persist session material. |
| Workbook publication | `storage.py` stages, writes, validates, and uses `os.replace`; tests cover failure preservation and widths for the inherited workbook. | M.6/M.15: approved 11 columns/types/order, file-lock recovery, Microsoft Excel open, cumulative/overlap/restart cases, packaged path. |
| Database and deduplication | Stable five-field uniqueness and concurrency tests exist, but the surrounding row/operation schemas are inherited. | M.4/M.5: exact immutable contracts, conflict comparison, range audit, schema creation/migration, restart and concurrent transaction tests. |
| Monitoring exclusion | Monitoring is intertwined with `app.py`, browser live-status adapters, the database, docs, packaging checks, and many tests. | M.13: removal only after shared import/browser/runtime/package behavior has independent Mini coverage; prove no monitoring controls, scheduler, workers, notifications, CSV, or tables remain on the Mini product path. |
| Package/install identity | All executable, metadata, archive, installer, docs, tests, and runtime paths identify the old product. | M.3 defines identity; M.14 adapts/builds; M.15 validates non-admin install, runtime writes, launch, shutdown, uninstall preservation, and clean Windows without Python. |

## 8. M.2 exit assessment

All 18 inherited production modules, all 18 test groups, current and inherited
documentation, source/evidence data, packaging/launch files, and writable
runtime boundaries are classified above. Authoritative tests, stale identities,
historical evidence limits, excluded monitoring behavior, and the requested
runtime/database/migration/browser/download/workbook risks are explicit. No
production code or architecture was changed. The M.2 documentation deliverable
and exit criteria are therefore satisfied; M.3 is the next implementation
increment.
