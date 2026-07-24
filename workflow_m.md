# Workflow M — Prisma Function Mini

## 1. Purpose

Workflow M defines how **Prisma Function Mini** is planned, implemented, reviewed, and validated.

The application is a single-user Windows desktop program. It opens PRISMA in a managed background browser session, lets the user select the required date range in Prisma Function Mini, downloads the official PRISMA CSV export, transforms it into the approved cumulative CSV contract, and stores historical results without duplicates.

## 2. Product baseline

Every increment must remain consistent with these requirements:

1. PRISMA is the authoritative source of auction data.
2. The user selects the source dates in Prisma Function Mini.
3. PRISMA must run through an application-owned managed browser session. Visible browser interaction should be avoided where the PRISMA workflow technically permits it.
4. The application downloads the official PRISMA CSV export automatically.
5. Mini must not automate a PRISMA Capacity filter. Only auctions with booked
   capacity of at least 1000 kWh/h after supported unit normalization are
   included by local CSV processing, using only an explicitly verified
   authoritative CSV field and semantics.
6. The output CSV must use UTF-8 encoding, a semicolon delimiter, a dot decimal
   separator, and expose:
   - auction date;
   - exit market or storage;
   - entry market or storage;
   - capacity type: entry, exit, or bundle;
   - network point name;
   - product type: WD, Day Ahead, Month, Quarter, or Year;
   - flow start date and time;
   - flow end date and time;
   - booked capacity in kWh/h;
   - duration in hours;
   - auction tariff in EUR/MWh/h.
   - `Auction Premium (EUR/MWh/h)`.
7. The output file is cumulative: existing historical rows are preserved and new rows are appended.
8. Repeated downloads or imports must not create duplicate auction rows.
9. Market and storage mappings are limited to `MARKET_STORAGE_MAPPING.md`.
   Unresolved output values remain blank. No fuzzy, geographic, cross-side,
   TSO, EIC, substring, or name-based inference is allowed.
10. Existing proven processing, mapping, persistence, runtime-path, browser, and packaging components from Prisma-function may be reused only when they match Mini requirements.
11. Monitoring-specific functionality from the previous application is outside Mini scope unless explicitly approved.
12. Any change to this baseline requires explicit customer approval and a documented roadmap update.

## 3. Language rules

- Application interface text: English.
- Buttons, labels, dialogs, statuses, errors, output headers, filenames used by the program, code identifiers, branch names, commit messages, prompts, and technical documentation: English unless the project explicitly requires otherwise.
- User-facing development explanations may be Ukrainian.
- Do not mix languages inside one application interface or output contract.

## 4. Source of truth

Before every increment, Codex must inspect:

1. `AGENTS.md`, if present;
2. `ROADMAP.md`;
3. this `workflow_m.md`;
4. architecture and product documentation;
5. relevant production code and tests;
6. `git status --short --branch`.

The roadmap and approved product documentation are the source of truth. If they conflict, stop and request clarification instead of silently choosing one.

## 5. Development model

1. All production code changes are implemented through Codex.
2. One task equals one complete, reviewable, and verified increment.
3. Start every increment from an up-to-date `main`.
4. Use a dedicated branch for every increment.
5. Recommended branch format: `feature/m<number>-<short-name>`, `fix/m<number>-<short-name>`, or `docs/m<number>-<short-name>`.
6. Do not expand scope, alter architecture, upgrade dependencies, or perform unrelated refactoring without explicit approval.
7. Preserve all existing user changes.
8. Add relevant tests for every feature and a regression test for every bug fix.
9. Do not proceed to the next increment until the current increment is merged into `main`.
10. The user creates and merges pull requests and performs branch cleanup unless they explicitly delegate those actions.
11. Codex must not commit, push, open a pull request, merge, rebase, force-push, delete a branch, or publish a release without explicit permission.
12. Never store credentials, tokens, personal data, complete sensitive URLs, or runtime secrets in the repository.

## 6. Increment workflow

### 6.1. Planning

Codex must:

- identify the next roadmap increment;
- confirm its exact scope and acceptance criteria;
- identify affected components and risks;
- create a short implementation plan for complex work;
- avoid implementation when required evidence or a product decision is missing.

### 6.2. Implementation

Codex must:

- implement only the approved increment;
- keep business logic independent from the PySide6 presentation layer;
- keep browser and file work outside the GUI thread;
- communicate worker results to Qt through safe signal boundaries;
- make retry, cancellation, shutdown, and cleanup behavior explicit;
- preserve cumulative data atomically;
- make deduplication deterministic and based on stable source identity;
- return clear English error messages without freezing the application.

### 6.3. Validation

Before completion, Codex must run, as applicable:

1. focused tests for changed behavior;
2. the complete test suite;
3. Python compilation;
4. type, lint, packaging, or build checks configured by the project;
5. `git diff --check`;
6. `git diff`;
7. `git status --short --branch`.

Codex must never claim a check passed unless it actually ran and completed successfully. Manual Windows, PRISMA live-session, browser-background, CSV-consumer, and packaged-application checks must be reported separately from automated tests.

### 6.4. Handoff

The final increment report must state:

- outcome;
- changed components;
- tests and checks actually completed;
- known limitations or manual checks still required;
- exact next action required from the user.

When the code is ready, Codex may provide commands for the user to review, stage, commit, and push. Pull request creation and merge remain user-controlled unless explicitly delegated.

## 7. Data integrity rules

1. Existing historical data must never be silently deleted, overwritten, or rebuilt.
2. A failed import or export must not publish a partial CSV or partial database update.
3. Exact retries must be idempotent.
4. Duplicate detection must use a documented stable identity and must not fall back to display names.
5. Conflicting rows sharing one identity must fail closed and remain auditable.
6. Source rows that cannot be transformed safely must be rejected with a deterministic reason.
7. Date range, source file identity, processing time, inserted count, duplicate count, rejected count, and failure details must be recorded.
8. Runtime data must use the approved Windows user-data directory and not the installation directory.
9. File-lock, interrupted-write, and restart recovery behavior must be tested where relevant.

## 8. Browser automation rules

1. Use the existing Playwright-based managed-browser boundary where suitable.
2. Date filters are owned by Prisma Function Mini, not manually entered in PRISMA by the user.
3. Browser automation must not configure or depend on a PRISMA Capacity filter.
4. Automatic CSV download must verify that the downloaded file belongs to the requested date range and expected PRISMA export contract.
5. Browser startup, authentication-required state, timeout, unavailable page, changed DOM, failed download, cancellation, manual closure, retry, and shutdown must have typed and testable outcomes.
6. Background or headless execution may be used only after real PRISMA behavior is validated. If PRISMA requires a visible browser, minimize or hide it safely without weakening reliability.
7. Never bypass authentication, access controls, anti-bot controls, or PRISMA terms.

For M.10, date filtering consumes `MiniDateRange`, formats both inclusive
calendar dates as `DD.MM.YYYY      06:00`, and uses only the confirmed
`startOfAuctionFrom`, `startOfAuctionTo`, `submit-filters`, and
`filter-startOfAuctionFrom` data-test IDs. It verifies exact displayed values
and valid timezone-aware PRISMA `data-test-iso-value` attributes before Apply.
No `filter-startOfAuctionTo`, dynamic id, CSS class, visible-text, Capacity, or
download selector is part of this contract.

## 9. Output contract

The authoritative CSV column names and ordering must be documented before implementation and covered by tests.

The CSV must:

- use UTF-8 encoding, semicolon delimiters, and dot decimal separators;
- preserve the approved mapping and 12-column order;
- append new unique rows deterministically;
- retain old rows;
- remain unchanged on exact retry except for explicitly approved audit metadata;
- be published atomically;
- keep numeric, date/time, tariff, and premium values in their correct textual
  representations and units.

## 10. Definition of Done

An increment is complete only when:

- approved scope is implemented;
- acceptance criteria are covered;
- relevant automated tests exist and pass;
- the full test suite passes;
- applicable compile, lint, type, build, and packaging checks pass;
- `git diff --check` passes;
- final diff and status are inspected;
- documentation and roadmap reflect the actual result;
- no known critical issue is left unresolved;
- remaining manual validation is explicitly recorded;
- the user has the information needed to create and merge the pull request.

## 11. Initial roadmap direction

The first Mini increments should establish, in order:

1. Mini-specific project documentation and removal of stale Prisma-function roadmap assumptions.
2. Approved output contract and deduplication identity.
3. Minimal Mini UI with date-range selection and truthful state management.
4. Managed PRISMA background-session foundation.
5. Adaptation of the historical Excel implementation to the approved cumulative
   12-column CSV contract.
6. `Start of Auction` date-range automation, with booked-capacity filtering
   performed locally from explicitly verified CSV semantics.
7. Verified automatic CSV download.
8. End-to-end recovery, retry, cancellation, and data-integrity validation.
9. Windows packaging and clean-machine validation.

The exact increment IDs and status are maintained only in `ROADMAP.md`.
