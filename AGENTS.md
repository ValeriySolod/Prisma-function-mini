# AGENTS.md

## Project

Prisma Function Mini is a single-user Windows desktop application that automates retrieval and transformation of official PRISMA auction exports.

The user selects a date range in the Mini application. The application runs PRISMA through a managed background browser session, downloads the official CSV export, transforms relevant auction rows into the approved Excel mapping, and preserves cumulative historical results without duplicates.

## Sources of truth

Before changing anything, inspect in this order:

1. `AGENTS.md`
2. `ROADMAP.md`
3. `workflow_m.md`
4. `TECHNICAL_SPECIFICATION.md`
5. relevant architecture, code, tests, and Git status

The roadmap and approved specification define scope. If they conflict or required evidence is missing, stop and ask for direction.

## Working rules

- Implement all production changes through Codex.
- One task must equal one complete, reviewable, and verified increment.
- Start each increment from an up-to-date `main` and use a dedicated branch.
- Recommended branches: `feature/m<number>-<short-name>`, `fix/m<number>-<short-name>`, or `docs/m<number>-<short-name>`.
- Do not change architecture, expand scope, upgrade dependencies, or perform unrelated refactoring without approval.
- Preserve all existing user changes.
- Add relevant tests for every feature and a regression test for every bug fix.
- Keep application UI, code identifiers, prompts, commit messages, workbook headers, and technical documentation in English.
- Never store credentials, tokens, personal data, complete sensitive URLs, or runtime secrets.
- Do not commit, push, open or merge pull requests, rebase, force-push, delete branches, or publish releases without explicit permission.
- The user normally creates and merges pull requests and cleans up branches.

## Product boundaries

- Date selection belongs to Prisma Function Mini.
- PRISMA access belongs to an application-owned Playwright browser lifecycle.
- Prefer a headless/background session when real PRISMA behavior supports it. If a visible browser is technically required, keep it managed and unobtrusive without weakening reliability.
- CSV download is automatic and must be tied to the requested date range.
- The output is a cumulative Excel workbook.
- Existing historical rows must be preserved.
- Exact retries must not create duplicates.
- Market and storage enrichment must use explicit authoritative evidence only.
- No fuzzy, geographic, TSO, EIC, substring, cross-side, or automatic mapping inference is allowed.
- Reuse verified components from Prisma-function only when they satisfy Mini requirements.
- Monitoring status, scheduler, notifications, monitoring CSV, and monitoring history are outside Mini scope unless explicitly approved.

## Architecture constraints

- Keep business logic independent from PySide6.
- Keep browser, CSV, database, and workbook work outside the GUI thread.
- Use Qt signals or an equivalent safe boundary for worker-to-UI communication.
- Keep browser ownership, cancellation, retry, shutdown, and cleanup explicit.
- Use typed outcomes for expected failures.
- Validate the downloaded CSV contract before persistence.
- Make database updates and workbook publication transactional or atomic.
- Use a documented stable auction identity; never use display names as an identity fallback.
- Store writable runtime data below the approved Windows user-data directory, not beside the executable.

## Required validation

Before handing off an increment, run as applicable:

1. focused tests;
2. full test suite;
3. Python compilation;
4. configured type, lint, build, and packaging checks;
5. `git diff --check`;
6. inspect `git diff`;
7. inspect `git status --short --branch`.

Never claim a check passed unless it actually ran successfully. Report manual Windows, live PRISMA, browser-background, Excel, installer, and clean-machine checks separately.

## Completion report

State:

- outcome;
- changed components;
- checks actually completed;
- known limitations and outstanding manual validation;
- the exact next action required from the user.
