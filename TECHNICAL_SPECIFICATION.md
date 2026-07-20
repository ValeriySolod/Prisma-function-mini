# Prisma Function Mini — Technical Specification

## 1. Product purpose

Prisma Function Mini is a single-user Windows desktop application for daily collection and transformation of official PRISMA gas-capacity auction data.

The application must let the user choose a date range, retrieve the corresponding PRISMA CSV export through a managed background browser session, transform qualifying auction rows into an approved Excel mapping, and cumulatively preserve historical results without duplicates.

## 2. Scope

### Included

- PySide6 Windows desktop interface;
- start-date and end-date selection in Mini;
- validation of the selected date range;
- managed PRISMA browser lifecycle;
- automatic application of PRISMA date and capacity filters;
- automatic download of the official CSV export;
- CSV contract detection and validation;
- filtering and unit normalization;
- authoritative Market/Storage enrichment;
- transformation into the approved workbook columns;
- cumulative local persistence;
- deterministic duplicate prevention;
- atomic Excel publication;
- progress, cancellation, retry, error reporting, and safe shutdown;
- Windows packaging and clean-machine validation.

### Excluded

Unless separately approved, Mini does not include:

- monitoring CSV files;
- periodic auction-status monitoring;
- monitoring scheduler;
- live status comparison;
- status-change notifications;
- monitoring history or dashboards;
- email, tray, network, or background-service notifications;
- inferred or fuzzy Market/Storage mappings;
- multi-user, server, or cloud synchronization.

## 3. User workflow

1. The user opens Prisma Function Mini.
2. The user selects a start date and an end date.
3. The application validates that the range is complete, ordered, and supported.
4. The user starts processing.
5. Mini opens an application-owned PRISMA session in the background.
6. Mini navigates to the auction export view and applies:
   - the selected date range;
   - the approved booked-capacity threshold.
7. Mini downloads the official CSV export to an application-controlled temporary location.
8. Mini verifies that the file is a supported PRISMA export and corresponds to the requested operation.
9. Mini transforms qualifying rows, enriches only evidenced references, and validates every output record.
10. Mini stores new unique records and audits duplicates and rejected rows.
11. Mini publishes the cumulative Excel workbook atomically.
12. Mini shows a truthful summary and allows the user to open the result.

## 4. Functional requirements

### FR-001 — Date selection

- The main window must provide `Start date` and `End date` controls.
- Dates are selected in Mini, not manually in PRISMA.
- The start date must not be later than the end date.
- The range must not contain unsupported future dates.
- Validation errors must be shown before browser work begins.
- The processed date range must be recorded in the operation audit.

### FR-002 — Background PRISMA session

- Mini owns the complete Playwright browser lifecycle.
- Headless/background execution is preferred when verified against the real PRISMA workflow.
- If PRISMA requires a visible browser, Mini may use a managed minimized or unobtrusive window while preserving reliability.
- Browser startup, readiness, authentication-required state, timeout, unavailable page, changed DOM, manual closure, cancellation, and cleanup must have deterministic outcomes.
- Mini must not bypass authentication, access controls, anti-bot controls, or PRISMA terms.
- No browser processes owned by Mini may remain after completion or application shutdown.

### FR-003 — Automatic CSV download

- Mini must navigate to the approved PRISMA auction export page.
- Mini must apply the selected dates automatically.
- Mini must apply the established relevant-capacity rule: booked capacity of at least 1000 kWh/h after supported unit normalization.
- Mini must initiate and await the official CSV download.
- The download must use an application-controlled temporary path.
- Mini must reject missing, empty, partial, unexpected, or unsupported files.
- Temporary source files must not become the historical source of truth after successful processing.

### FR-004 — Source validation and transformation

- Every source row must be classified as processed, duplicate, filtered, or rejected.
- Supported capacity and tariff units must be normalized explicitly.
- Dates and timestamps must be parsed strictly.
- Product types must be normalized only to the approved values.
- Market/Storage enrichment must use the immutable authoritative reference catalog.
- Ambiguous or unsafe rows must be rejected with a stable reason code and source-row context.

### FR-005 — Approved Excel mapping

The authoritative worksheet is named `Auctions`. Its columns and order are:

| # | Column | Value |
|---:|---|---|
| 1 | `Auction Date` | Date when the auction was held |
| 2 | `Exit Market / Storage` | Authoritative exit Market or Storage name |
| 3 | `Entry Market / Storage` | Authoritative entry Market or Storage name |
| 4 | `Capacity Type` | `Entry`, `Exit`, or `Bundle` |
| 5 | `Network Point` | PRISMA network-point display name |
| 6 | `Product Type` | `WD`, `Day Ahead`, `Month`, `Quarter`, or `Year` |
| 7 | `Flow Start` | Flow start date and time |
| 8 | `Flow End` | Flow end date and time |
| 9 | `Booked Capacity (kWh/h)` | Capacity normalized to kWh/h |
| 10 | `Duration (hours)` | Exact duration between Flow Start and Flow End |
| 11 | `Auction Tariff (EUR/MWh/h)` | Tariff normalized to EUR/MWh/h |

Workbook rules:

- headers and order are stable and covered by tests;
- dates, timestamps, integers, decimals, and text use appropriate Excel types;
- deterministic widths and formatting are applied;
- output ordering is deterministic;
- the workbook must open in Microsoft Excel;
- publication uses a staged file and atomic replacement;
- a failure must leave the previous valid workbook unchanged.

### FR-006 — Daily cumulative history

- The same runtime database and workbook are updated on every successful daily run.
- Existing records remain available.
- New unique records are appended.
- Runs for overlapping date ranges are supported.
- An exact retry inserts no duplicate auction row.
- A run with no new rows still records a truthful operation result.
- Startup and processing must not silently rebuild or discard existing history.

### FR-007 — Duplicate prevention

The stable auction identity is:

- exact PRISMA `Auction ID`;
- selected side-specific `Network Point ID`;
- normalized capacity direction;
- normalized `Flow Start`;
- normalized `Flow End`.

Rules:

- display names are never identity fallbacks;
- blank required identity fields cause row rejection;
- identical rows with the same identity are duplicates and do not create new records;
- conflicting rows with the same identity fail closed and are audited;
- duplicate checking occurs before workbook publication;
- database uniqueness constraints and application validation must agree;
- deduplication is covered for exact retries, overlapping ranges, repeated source rows, and application restart.

### FR-008 — Audit and recovery

Each operation must record:

- requested start and end dates;
- evaluated time;
- source file hash;
- processed, inserted, duplicate, filtered, and rejected counts;
- result status;
- stable failure or rejection details.

Database mutation and audit creation must be transactional. Interrupted workbook publication must be recoverable. A failed operation must remain retryable without corrupting historical data.

### FR-009 — User interface states

At minimum:

- `Idle`;
- `Validating`;
- `Opening PRISMA`;
- `Downloading`;
- `Processing`;
- `Publishing`;
- `Completed`;
- `Cancelling`;
- `Error`.

Unavailable actions must be disabled. Long-running work must not block the GUI thread. The user must receive concise English progress and error messages.

## 5. Reuse policy

Reuse from Prisma-function is allowed after contract and regression review.

Preferred candidates:

- Playwright browser ownership and cleanup;
- PRISMA page readiness and typed failure boundaries;
- CSV contract detection and parsing;
- unit and product normalization;
- authoritative reference catalog;
- import transformation;
- SQLite persistence and deduplication;
- atomic workbook publication;
- runtime user-data paths and migration safety;
- logging, packaging, and validation utilities.

Do not carry into Mini unless explicitly approved:

- MonitoringEngine;
- MonitoringScheduler;
- monitoring CSV contract and loader;
- live auction-status adapter used only for monitoring;
- monitoring database tables;
- status-transition notifications;
- monitoring dashboard controls and activity semantics.

Reuse must be selective. Removing excluded functionality must not weaken shared browser, import, persistence, or packaging behavior.

## 6. Non-functional requirements

- Target: supported 64-bit Windows desktop environment.
- Single local user; no administrator rights required.
- UI remains responsive during browser and processing work.
- Writable data resides below `%LOCALAPPDATA%\\PrismaFunctionMini`.
- Installation and source directories are not runtime write targets.
- Logs must not expose credentials, tokens, cookies, personal data, or complete sensitive URLs.
- Results must be deterministic for the same authoritative input and catalog.
- Shutdown must wait for or safely cancel owned non-daemon work.
- The packaged application must run without a separately installed Python runtime.

### 6.1 Mini identity and runtime boundary

The authoritative internal/package identity is `PrismaFunctionMini`, the
display/product name is `Prisma Function Mini`, the executable is
`PrismaFunctionMini.exe`, and the initial Mini version is `0.1.0`.

The writable runtime layout is:

- database: `%LOCALAPPDATA%\PrismaFunctionMini\data\prisma_function_mini.db`;
- workbook: `%LOCALAPPDATA%\PrismaFunctionMini\data\result\prisma_function_mini.xlsx`;
- state: `%LOCALAPPDATA%\PrismaFunctionMini\state\prisma_function_mini_state.json`;
- log: `%LOCALAPPDATA%\PrismaFunctionMini\logs\prisma-function-mini.log`;
- temporary downloads: `%LOCALAPPDATA%\PrismaFunctionMini\temporary-downloads`.

The inherited `%LOCALAPPDATA%\PrismaFunction` root is read-only historical user
data. Mini performs no automatic scan, copy, move, overwrite, deletion,
rebuild, or reinterpretation of that root. Any future opt-in copy/transform
requires the approved M.5/M.6 contracts and a separately tested migration.
`M3_IDENTITY_AND_RUNTIME_BOUNDARY.md` records the complete decision.

## 7. Acceptance baseline

The product baseline is accepted when a clean Windows validation demonstrates:

- date selection in Mini;
- reliable managed background PRISMA opening;
- automatic date filtering and CSV download;
- correct transformation into the approved 11-column workbook;
- exclusion of capacity below the approved threshold;
- correct authoritative Market/Storage enrichment;
- daily cumulative updates;
- no duplicates after exact retry and overlapping ranges;
- preserved history after restart;
- recoverable failure and successful retry;
- clean browser and application shutdown;
- all automated tests and packaging validation passing.

Manual real-PRISMA and clean-machine results must be recorded separately from automated test results.
