# Prisma Function Mini Roadmap

`ROADMAP.md` is the authoritative implementation sequence. `workflow_m.md` defines the development workflow, and `TECHNICAL_SPECIFICATION.md` defines the product baseline and acceptance requirements.

## Status legend

- ✅ Completed
- 🟡 In progress
- ⬜ Planned
- ⛔ Blocked

## Roadmap

| ID | Increment | Status | Deliverable | Exit criteria |
|---|---|---|---|---|
| M.1 | Mini documentation foundation | ✅ Completed | Mini-specific `AGENTS.md`, `workflow_m.md`, `TECHNICAL_SPECIFICATION.md`, and `ROADMAP.md`. | Documents agree on scope, workflow, mapping, deduplication, reuse, and exclusions; merged to `main`. |
| M.2 | Baseline and reuse inventory | ✅ Completed | Evidence-backed inventory of reusable, adaptable, and removable components from Prisma-function in `M2_BASELINE_REUSE_INVENTORY.md`. | Each production module and test group is classified; no code behavior changes. |
| M.3 | Mini application identity and runtime boundary | ✅ Completed | Mini name, version, executable identity, runtime paths, logs, database, workbook path, packaging metadata, and documented no-automatic-migration decision. | Merged to `main`; focused identity, runtime-path, logging, package, and installer tests pass. |
| M.4 | Mini domain and output contracts | ✅ Completed | Immutable date-range, downloaded-source request, normalized-auction, 11-column output-row, accumulated-history, stable duplicate-key, validation-failure, and processing-result contracts in `mini_domain.py`. | Approved mapping, units, types, ordering, reason codes, normalization, failure rules, and duplicate behavior have focused tests. |
| M.5 | Stable deduplication and cumulative storage | ✅ Completed | Mini-specific transactional SQLite storage and operation audit. | Exact retry and overlapping ranges are idempotent; conflicts fail closed; existing history survives restart. |
| M.6 | Atomic cumulative Excel publication | ✅ Completed | Deterministic `Auctions` worksheet generated from authoritative storage. | Existing rows are preserved, new unique rows appear once, types/widths/order are tested, and failed publication preserves the last valid workbook. |
| M.7 | Minimal Mini UI foundation | ✅ Completed | Focused PySide6 window without monitoring dashboard behavior. | Start/end date controls, truthful state model, Start/Cancel/Open Result actions, and responsive worker signaling are tested; merged to `main`. |
| M.8 | Managed PRISMA background session | ✅ Completed | Mini-owned Playwright lifecycle with an explicit headless-first policy and no unverified visible fallback. | Startup, readiness, authentication-required, timeout, closure, cancellation, one bounded transient retry, and deterministic cleanup are covered without live access; merged to `main`. |
| M.9 | Excel-to-CSV contract adaptation | ✅ Completed | Adapt the historical M.4-M.6 11-column Excel contracts and publisher to the authoritative cumulative 12-column CSV, including Auction Premium. | UTF-8, semicolon delimiter, dot decimal separator, exact 12-column order, authoritative blank-preserving mapping, cumulative atomic publication, and regression tests pass. |
| M.10 | Automated PRISMA date filtering | ✅ Completed | Mini applies only the selected `Start of Auction` date range; PRISMA Capacity automation is prohibited. | Confirmed stable DOM selectors drive exact date entry and Apply; interpreted timestamps, applied state, refresh, typed failures, cancellation, duplicate submission, bounded retry compatibility, and cleanup have deterministic adapter tests. |
| M.11 | Automatic CSV download | ✅ Completed | Verified download to an application-controlled temporary location. | Missing, partial, empty, wrong-contract, cancellation, timeout, and retry scenarios are covered; requested range is audited; merged to `main`. |
| M.12 | Integrated transformation workflow | 🟡 In progress | Download, validation, normalization, authoritative enrichment, storage, audit, and CSV publication operate as one workflow. | Every row is accounted for; failure is atomic; exact retry is unchanged; integrated tests pass. |
| M.13 | Daily cumulative operation readiness | ⬜ Planned | User workflow supports safe daily updates and overlapping ranges. | Multiple-day and repeated-run scenarios preserve history without duplicates; restart recovery is validated. |
| M.14 | Remove excluded monitoring functionality | ⬜ Planned | Monitoring UI, scheduler, status checks, notifications, and monitoring-only persistence are removed from the Mini product path. | Import/browser/shared utilities remain green; no monitoring controls or background monitoring processes remain. |
| M.15 | Windows package and installer | ⬜ Planned | Mini-specific PyInstaller onedir package and per-user installer. | Structural validation passes; runtime data stays in the Mini user-data directory; no Python installation is required. |
| M.16 | Real PRISMA and clean-Windows validation | ⬜ Planned | Recorded end-to-end validation on a standard non-administrator Windows computer. | Background session, download, data-bearing transform, cumulative CSV output, retry, overlap, restart, shutdown, installer, and uninstaller checks pass. |
| M.17 | Release readiness | ⬜ Planned | Versioned release archive, checksum, release notes, and final checklist. | Automated and required manual checks are recorded as passed; publication requires explicit approval. |

## In-progress increments

### M.12 — Integrated transformation workflow

M.12 connects the managed browser, date filter, automatic download, exact
35-column source validation, row-accounted transformation, authoritative
mapping, transactional cumulative storage and audit, and atomic CSV publisher
through the M.7 worker boundary. It applies the local normalized marketed
capacity threshold, exact gas-day/calendar product classification, DST-aware
duration, side-specific tariffs, and surcharge premium conversion. M.12 remains
In progress until merge.

## Completed increments

### M.10 — Automated PRISMA date filtering

M.10 consumes the existing validated `MiniDateRange` and maps each inclusive
local calendar boundary to `DD.MM.YYYY      06:00`. It fills only
`[data-testid="startOfAuctionFrom"]` and
`[data-testid="startOfAuctionTo"]`, verifies each exact displayed value and a
valid timezone-aware `data-test-iso-value`, and then activates
`[data-testid="submit-filters"]`. Successful application is confirmed only by
`[data-testid="filter-startOfAuctionFrom"]`; no end-tag selector is required or
inferred. Auction-result refresh is awaited through Playwright load state
without arbitrary sleeps.

Missing controls, rejected values, invalid interpreted timestamps, Apply
timeout, authentication loss, cancellation, and refresh failure have typed
outcomes. One adapter instance submits at most once, including after an
uncertain post-Apply failure, while M.8 retains one bounded pre-action session
retry and deterministic cleanup. CSV download and all M.9 processing,
persistence, duplicate, and publication behavior remain outside this adapter.

### M.9 — Excel-to-CSV contract adaptation

M.9 adds the optional Auction Premium domain and SQLite field, upgrades existing
M.5/M.6 databases in place with blank historical premium, permits unresolved
authoritative Market/Storage values to remain blank, and replaces the active
Mini Excel publisher with deterministic atomic cumulative CSV publication.
The runtime result is `prisma_function_mini.csv` with UTF-8 encoding, semicolon
delimiters, dot-decimal text, exact 12-column order, and unchanged files on
equivalent retries.

### M.5 — Stable deduplication and cumulative storage

M.5 adds a Mini-only SQLite schema for cumulative normalized auction history and
operation audit records at the approved runtime database path. A write-reserving
transaction compares the complete immutable M.4 payload against the exact
five-field duplicate key before mutation. Identical rows are counted as
duplicates, new rows are inserted once, and any same-key payload conflict fails
closed without partial auction writes while preserving a failed audit result.

Operations record the requested range, source basename, SHA-256 and size,
outcome, inserted/duplicate/conflict/validation-failure counts, failure details,
and timezone-aware UTC start/completion timestamps. Reads are deterministic,
schema initialization is repeatable, and cumulative history survives reopening.

### M.6 — Atomic cumulative Excel publication

The M.6 feature branch renders the exact 11-column `Auctions` worksheet from
Mini SQLite history in deterministic storage order. Excel dates, timestamps,
numeric values, widths, and number formats are explicit. Publication validates
a same-directory staged workbook before atomic replacement, removes abandoned
staging files after failures, preserves an existing valid workbook on any
staging or replacement failure, and leaves an equivalent workbook untouched on
an exact retry.

M.6 was reviewed and merged into `main`.

M.4-M.6 remain historical completed implementation. Their merged 11-column
Excel contracts, cumulative SQLite storage, and atomic workbook publisher are
not retroactively relabeled as CSV implementation.

## Next recommended increment

M.13 — Daily cumulative operation readiness. Monitoring removal remains M.14.

## Current contract

### M.9 — Excel-to-CSV contract adaptation

M.9 adapts the historical M.4-M.6 implementation to the revised authoritative
cumulative output: 12 CSV columns, UTF-8 encoding, semicolon delimiters, dot
decimal separators, and `Auction Premium (EUR/MWh/h)`. Market and Storage values
come only from `MARKET_STORAGE_MAPPING.md`; unresolved values remain blank.

M.10 now owns the confirmed date-filter interaction described above. PRISMA
Capacity automation remains prohibited. The marketed-capacity threshold of at
least 1000 kWh/h may be applied locally only after the CSV field and semantics
are verified.

The M.11 automatic-download boundary is implemented with deterministic fake
Playwright and filesystem tests. Live PRISMA interaction, the confirmed
selectors in the current production DOM, and headless/background behavior
remain unvalidated.

## Maintenance rules

- Update statuses only when the repository contains the stated result.
- Mark an increment completed only after its changes are merged into `main`.
- Record automated and manual validation separately.
- Do not reorder or expand increments without explicit approval.
- Do not infer Market/Storage mappings or weaken the stable identity contract.
