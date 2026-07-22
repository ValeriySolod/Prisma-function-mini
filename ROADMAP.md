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
| M.7 | Minimal Mini UI foundation | 🟡 In progress | Focused PySide6 window without monitoring dashboard behavior. | Start/end date controls, truthful state model, Start/Cancel/Open Result actions, and responsive worker signaling are tested. |
| M.8 | Managed PRISMA background session | ⬜ Planned | Selectively reused Playwright lifecycle for Mini. | Startup, readiness, background/headless strategy, authentication-required, timeout, closure, cancellation, retry, and cleanup are covered. |
| M.9 | Automated PRISMA date filtering | ⬜ Planned | Mini applies the selected date range and approved capacity filter. | Real DOM evidence confirms filter behavior; changed/unavailable DOM failures are typed; deterministic adapter tests pass. |
| M.10 | Automatic CSV download | ⬜ Planned | Verified download to an application-controlled temporary location. | Missing, partial, empty, wrong-contract, cancellation, timeout, and retry scenarios are covered; requested range is audited. |
| M.11 | Integrated transformation workflow | ⬜ Planned | Download, validation, normalization, authoritative enrichment, storage, audit, and workbook publication operate as one workflow. | Every row is accounted for; failure is atomic; exact retry is unchanged; integrated tests pass. |
| M.12 | Daily cumulative operation readiness | ⬜ Planned | User workflow supports safe daily updates and overlapping ranges. | Multiple-day and repeated-run scenarios preserve history without duplicates; restart recovery is validated. |
| M.13 | Remove excluded monitoring functionality | ⬜ Planned | Monitoring UI, scheduler, status checks, notifications, and monitoring-only persistence are removed from the Mini product path. | Import/browser/shared utilities remain green; no monitoring controls or background monitoring processes remain. |
| M.14 | Windows package and installer | ⬜ Planned | Mini-specific PyInstaller onedir package and per-user installer. | Structural validation passes; runtime data stays in the Mini user-data directory; no Python installation is required. |
| M.15 | Real PRISMA and clean-Windows validation | ⬜ Planned | Recorded end-to-end validation on a standard non-administrator Windows computer. | Background session, download, data-bearing transform, Excel output, retry, overlap, restart, shutdown, installer, and uninstaller checks pass. |
| M.16 | Release readiness | ⬜ Planned | Versioned release archive, checksum, release notes, and final checklist. | Automated and required manual checks are recorded as passed; publication requires explicit approval. |

## Completed increments

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

## Next recommended increment

After M.7 is reviewed and merged into `main`, execute
**M.8 — Managed PRISMA background session** next. Browser automation, CSV
download, and integrated processing remain outside M.7. Monitoring removal
remains M.13.

## Current increment

### M.7 — Minimal Mini UI foundation

The M.7 feature branch replaces the inherited monitoring dashboard entry point
with a focused PySide6 window. It provides start/end dates, validation before
worker startup, the exact documented UI states, Start/Cancel/Open Result action
policies, queued worker progress/outcome signals, cooperative cancellation, and
shutdown that waits for owned non-daemon work. The workflow runner is an
explicit seam; browser automation, download, and integrated processing are not
implemented by M.7.

M.7 remains in progress until review and merge to `main`.

## Maintenance rules

- Update statuses only when the repository contains the stated result.
- Mark an increment completed only after its changes are merged into `main`.
- Record automated and manual validation separately.
- Do not reorder or expand increments without explicit approval.
- Do not infer Market/Storage mappings or weaken the stable identity contract.
