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
| M.3 | Mini application identity and runtime boundary | 🟡 In progress | Mini name, version, executable identity, runtime paths, logs, database, workbook path, and packaging metadata. | No remaining runtime writes target the old PrismaFunction location; migration decision documented and tested; merge into `main` remains required for completion. |
| M.4 | Mini domain and output contracts | ⬜ Planned | Immutable date-range, source-operation, normalized-auction, workbook-row, audit, and failure contracts. | Approved 11-column mapping, units, types, ordering, reason codes, and validation rules have focused tests. |
| M.5 | Stable deduplication and cumulative storage | ⬜ Planned | Mini-specific transactional SQLite storage and operation audit. | Exact retry and overlapping ranges are idempotent; conflicts fail closed; existing history survives restart. |
| M.6 | Atomic cumulative Excel publication | ⬜ Planned | Deterministic `Auctions` worksheet generated from authoritative storage. | Existing rows are preserved, new unique rows appear once, types/widths/order are tested, and failed publication preserves the last valid workbook. |
| M.7 | Minimal Mini UI foundation | ⬜ Planned | Focused PySide6 window without monitoring dashboard behavior. | Start/end date controls, truthful state model, Start/Cancel/Open Result actions, and responsive worker signaling are tested. |
| M.8 | Managed PRISMA background session | ⬜ Planned | Selectively reused Playwright lifecycle for Mini. | Startup, readiness, background/headless strategy, authentication-required, timeout, closure, cancellation, retry, and cleanup are covered. |
| M.9 | Automated PRISMA date filtering | ⬜ Planned | Mini applies the selected date range and approved capacity filter. | Real DOM evidence confirms filter behavior; changed/unavailable DOM failures are typed; deterministic adapter tests pass. |
| M.10 | Automatic CSV download | ⬜ Planned | Verified download to an application-controlled temporary location. | Missing, partial, empty, wrong-contract, cancellation, timeout, and retry scenarios are covered; requested range is audited. |
| M.11 | Integrated transformation workflow | ⬜ Planned | Download, validation, normalization, authoritative enrichment, storage, audit, and workbook publication operate as one workflow. | Every row is accounted for; failure is atomic; exact retry is unchanged; integrated tests pass. |
| M.12 | Daily cumulative operation readiness | ⬜ Planned | User workflow supports safe daily updates and overlapping ranges. | Multiple-day and repeated-run scenarios preserve history without duplicates; restart recovery is validated. |
| M.13 | Remove excluded monitoring functionality | ⬜ Planned | Monitoring UI, scheduler, status checks, notifications, and monitoring-only persistence are removed from the Mini product path. | Import/browser/shared utilities remain green; no monitoring controls or background monitoring processes remain. |
| M.14 | Windows package and installer | ⬜ Planned | Mini-specific PyInstaller onedir package and per-user installer. | Structural validation passes; runtime data stays in the Mini user-data directory; no Python installation is required. |
| M.15 | Real PRISMA and clean-Windows validation | ⬜ Planned | Recorded end-to-end validation on a standard non-administrator Windows computer. | Background session, download, data-bearing transform, Excel output, retry, overlap, restart, shutdown, installer, and uninstaller checks pass. |
| M.16 | Release readiness | ⬜ Planned | Versioned release archive, checksum, release notes, and final checklist. | Automated and required manual checks are recorded as passed; publication requires explicit approval. |

## Current increment

### M.3 — Mini application identity and runtime boundary

Scope:

- define `PrismaFunctionMini` / `Prisma Function Mini` application, executable,
  package, version-resource, and installer identities;
- place every Mini runtime write below `%LOCALAPPDATA%\PrismaFunctionMini`;
- define Mini database, workbook, state, log, and temporary-download paths;
- keep `%LOCALAPPDATA%\PrismaFunction` read-only with no automatic migration;
- preserve inherited monitoring functionality until M.13;
- add focused runtime and packaging identity regression coverage.

The implementation and migration decision are documented in
`M3_IDENTITY_AND_RUNTIME_BOUNDARY.md`. M.3 remains in progress until its changes
are merged into `main`.

## Next recommended increment

After M.3 is reviewed and merged into `main`, execute
**M.4 — Mini domain and output contracts** next.

M.4 must define and test:

- immutable date-range and source-operation contracts;
- normalized-auction, workbook-row, audit, and failure contracts;
- the approved 11-column mapping, types, units, ordering, and reason codes.

Do not begin M.4 before M.3 is merged. Monitoring removal remains M.13.

## Maintenance rules

- Update statuses only when the repository contains the stated result.
- Mark an increment completed only after its changes are merged into `main`.
- Record automated and manual validation separately.
- Do not reorder or expand increments without explicit approval.
- Do not infer Market/Storage mappings or weaken the stable identity contract.
