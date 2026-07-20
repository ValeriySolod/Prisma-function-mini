# Workflow P — Prisma-function

## 1. Призначення

Workflow P визначає послідовність створення, перевірки та розвитку програми **Prisma-function**.

Програма повинна бути невеликою, зрозумілою для користувача та працювати з браузерами **Google Chrome** і **Microsoft Edge**.

## 1.1. Authoritative customer requirements

This section is the permanent product acceptance baseline for the entire **Prisma-function** project. Every future increment, review, and roadmap decision must be checked against these requirements.

1. PRISMA is the source platform for European gas-capacity auction data.
2. The application processes official PRISMA auction exports.
3. The relevant source period starts from the selected first day of a month.
4. Only auctions with booked capacity of at least 1000 kWh/h after supported unit normalization are relevant. This threshold corresponds to the established PRISMA import and live-filter contract.
5. The transformed output must expose:
   - auction date;
   - exit market or storage facility;
   - entry market or storage facility;
   - capacity direction: entry, exit, or bundle;
   - network point name, for example `VGS Storage Hub`;
   - product type: `WD`, `Day Ahead`, `Month`, `Quarter`, or `Year`;
   - flow start date and time;
   - flow end date and time;
   - booked capacity in kWh/h;
   - runtime duration in hours;
   - auction tariff in EUR/MWh/h.
6. Market and storage enrichment must use only official PRISMA evidence.
7. A Market mapping may be added only when an exact Auction ID links:
   - the exact side-specific network-point name and identifier from the CSV export;
   - the corresponding Market Area shown in an official PRISMA PDF or equivalent official reference export.
8. Evidence files that do not contain the same Auction ID must not be cross-matched.
9. Ambiguous, visually overlapped, incomplete, or conflicting source rows must be excluded from authoritative mapping batches.
10. Do not infer mappings from geography, TSO names, EIC similarity, display-text similarity, naming conventions, or previously observed mappings.
11. Do not assume that an Exit alias is valid for Entry, or that an Entry alias is valid for Exit.
12. Every catalog expansion must be a separate reviewed batch with focused regression tests proving:
    - exact resolution on the evidenced side;
    - no resolution on an unevidenced side;
    - no fuzzy, substring, geographic, or automatic matching;
    - preservation of existing mappings and import behavior.
13. No future task may silently weaken, reinterpret, or contradict these requirements. Any requested deviation must be documented and explicitly approved by the customer before implementation.
14. Every authoritative mapping batch must identify the exact evidence files used and record their SHA-256 digests. The accepted mappings must remain reproducible from those unchanged source files.

## 2. Мовні правила

- Мова інтерфейсу програми: **English**.
- Назви кнопок, полів, повідомлень, статусів, діалогових вікон і помилок: **English**.
- Назви колонок CSV: **English**.
- Значення статусів у CSV: **English**.
- Назви файлів, класів, функцій і змінних у коді: **English**.
- Документація для розробника може бути українською.
- Не змішувати українську та англійську мови в інтерфейсі або CSV.

## 3. Основні правила роботи

1. Один етап — одна завершена задача.
2. Кожний новий етап виконувати в окремій Git-гілці.
3. Кожний новий завершений блок починати в новому чаті.
4. Перед змінами перевіряти актуальний стан гілки `main`.
5. Для реалізації коду використовувати Codex.
6. Після реалізації обов’язково виконувати review через GitHub Copilot без редагування файлів.
7. Після кожного етапу запускати тести.
8. Не переходити до наступного етапу, доки поточний не завершено та не об’єднано з `main`.
9. Не змінювати production-код, якщо необхідну поведінку можна підтвердити або покрити тестами.
10. Усі помилки повинні оброблятися без зависання програми та без блокування повторного запуску.

## 4. Порядок створення програми

### P.1. Базова структура

Створити мінімальну структуру проєкту:

- application entry point;
- UI module;
- browser controller;
- CSV reader and validator;
- monitoring logic;
- configuration;
- tests;
- setup and run scripts;
- project documentation.

Результат етапу:

- програма запускається;
- відкривається головне вікно;
- тести стартової структури проходять.

### P.2. Головне вікно

Створити компактне головне вікно.

Мінімальні елементи:

- `Open Browser`;
- `Load Monitoring CSV`;
- `Start Monitoring`;
- `Stop Monitoring`;
- `Status`;
- поле або журнал результатів.

Правила:

- усі написи англійською;
- недоступні дії повинні бути disabled;
- після помилки кнопки повинні повертатися у правильний стан;
- користувач повинен мати можливість повторити операцію.

### P.3. Automatic default browser detection

Програма повинна автоматично визначати браузер, налаштований як Windows default browser.

Підтримувані браузери для першої версії:

- `Google Chrome`;
- `Microsoft Edge`.

Вимоги:

- прибрати ручний вибір Chrome або Edge з GUI;
- прибрати browser selector і весь пов’язаний з ним UI state;
- відокремити browser detection від UI layer і browser controller;
- перевіряти існування executable визначеного браузера;
- обробляти unsupported default browser, missing or corrupted browser association, registry read failure і missing executable з чіткими англомовними повідомленнями про помилки;
- monitoring flow повинен і надалі використовувати Playwright, а не `webbrowser.open()`;
- коректно завершувати browser session;
- не залишати фонові процеси після зупинки.

Обов’язкові тести:

- Chrome as default browser;
- Edge as default browser;
- unsupported default browser;
- missing or corrupted browser association;
- missing executable;
- Windows registry read failure;
- successful retry after an error;
- complete removal of the browser selector from the UI.

### P.4. Відкриття Prisma

Реалізувати відкриття цільового сайту Prisma.

Перевірити сценарії:

- успішний запуск;
- помилка запуску Playwright;
- помилка створення browser instance;
- помилка створення page;
- закриття браузера користувачем;
- повторний запуск після помилки;
- зупинка під час запуску;
- захист від застарілого результату попереднього запуску.

### P.5. CSV contract

CSV повинен мати англійські назви колонок.

Базовий контракт:

```csv
auction_id,auction_url,lot_number,item_name,expected_status,last_known_status,check_interval_seconds,enabled
```

Опис колонок:

| Column | Purpose |
|---|---|
| `auction_id` | Unique auction identifier |
| `auction_url` | Direct URL to the auction page |
| `lot_number` | Lot number |
| `item_name` | Item or auction name |
| `expected_status` | Status that should trigger attention |
| `last_known_status` | Last status saved by the program |
| `check_interval_seconds` | Monitoring interval |
| `enabled` | Enables or disables monitoring for the row |

Допустимі boolean values:

- `true`;
- `false`.

Приклади status values:

- `Scheduled`;
- `Open`;
- `In Progress`;
- `Completed`;
- `Cancelled`;
- `Unknown`;
- `Error`.

CSV validation повинна перевіряти:

- наявність усіх обов’язкових колонок;
- унікальність `auction_id`;
- коректність URL;
- допустимий interval;
- допустиме boolean value;
- порожні обов’язкові поля;
- дублікати;
- неправильне кодування або пошкоджений файл.

Усі validation messages повинні бути англійською.

### P.6. Завантаження CSV

Після вибору CSV програма повинна:

1. відкрити файл;
2. перевірити заголовки;
3. перевірити кожний рядок;
4. показати кількість завантажених записів;
5. показати помилки з номером рядка;
6. не запускати monitoring при критичних помилках;
7. дозволити повторно вибрати виправлений файл.

Приклади повідомлень:

- `CSV file loaded successfully.`;
- `Missing required column: auction_url.`;
- `Invalid URL in row 4.`;
- `Duplicate auction_id in row 7.`;
- `No active auctions found.`;

### P.7. Monitoring engine

Для кожного активного запису програма повинна:

- відкривати відповідну сторінку;
- зчитувати поточний статус;
- порівнювати його з попереднім;
- фіксувати час перевірки;
- обробляти network timeout;
- обробляти зміну структури сторінки;
- продовжувати роботу з іншими записами після локальної помилки;
- підтримувати безпечну зупинку користувачем.

Monitoring не повинен блокувати UI thread.

### P.8. Результати моніторингу

Результати повинні використовувати англійські назви полів.

Рекомендований output CSV:

```csv
checked_at,auction_id,lot_number,item_name,current_status,previous_status,status_changed,result,error_message
```

Приклади `result`:

- `Success`;
- `Changed`;
- `Skipped`;
- `Error`.

Поле `error_message` повинно бути порожнім при успішній перевірці.

### P.9. UI state management

Визначити стани програми:

- `Idle`;
- `Loading CSV`;
- `Opening Browser`;
- `Ready`;
- `Monitoring`;
- `Stopping`;
- `Error`.

Для кожного стану визначити:

- активні кнопки;
- неактивні кнопки;
- текст status label;
- дозволені переходи;
- обробку помилок;
- можливість повторного запуску.

### P.10. Error handling

Обов’язково обробити:

- browser launch failure;
- page creation failure;
- invalid CSV;
- missing columns;
- unavailable website;
- timeout;
- authentication failure;
- unexpected page format;
- browser closed manually;
- monitoring stop request;
- unexpected exception.

Після будь-якої помилки:

- UI не повинен зависати;
- кнопки повинні повернутися у коректний стан;
- internal references повинні очищатися;
- browser resources повинні закриватися;
- повторний запуск повинен залишатися доступним.

### P.11. Testing

Мінімальні групи тестів:

1. UI state tests.
2. Browser controller tests.
3. CSV validation tests.
4. Monitoring tests.
5. Error handling tests.
6. Stop and retry tests.
7. Generation or stale-result protection tests.
8. Resource cleanup tests.

Перед завершенням кожного етапу:

- запустити focused tests;
- запустити full test suite;
- перевірити, що production behavior не регресував;
- перевірити GitHub Copilot review findings;
- виправити critical і important findings;
- повторно запустити full test suite.

### P.12. Packaging and launch

Підготувати:

- `setup.bat`;
- `run.bat`;
- dependency file;
- README;
- sample CSV;
- logs directory;
- output directory.

Для Git Bash запуск Windows scripts виконувати так:

```bash
./setup.bat
./run.bat
```

Для Command Prompt:

```bat
setup.bat
run.bat
```

### P.13. Final readiness check

Перед першою стабільною версією перевірити:

- automatic default browser detection;
- Chrome as default browser;
- Edge as default browser;
- unsupported default browser;
- PySide6 GUI readiness;
- valid CSV;
- invalid CSV;
- empty CSV;
- interrupted launch;
- browser close;
- monitoring start;
- monitoring stop;
- repeated start and stop;
- network failure;
- page structure mismatch;
- output CSV;
- cleanup after exit;
- all UI text is English;
- all CSV headers and status values are English;
- all tests pass.

### P.14. GUI framework migration to PySide6

Для GUI використовувати `PySide6` і виконати migration from Tkinter to PySide6.

Вимоги:

- business logic повинна залишатися незалежною від GUI framework;
- GUI повинен залишатися presentation layer;
- long-running work не повинен виконуватися в main GUI thread;
- worker-thread communication з GUI повинна використовувати Qt signals;
- використовувати `QMainWindow`;
- використовувати `QFileDialog` для вибору CSV;
- використовувати `QMessageBox` для повідомлень;
- використовувати `QTableView` або `QTableWidget` для tabular data;
- інтегрувати monitoring і browser lifecycle через Qt-safe mechanisms;
- весь UI text повинен залишатися англійською.

#### P.14.1. PySide6 application skeleton

Створити PySide6 application entry point, `QApplication` lifecycle і базовий `QMainWindow`, зберігши business logic поза GUI framework.

#### P.14.2. Main window and CSV table

Перенести main window controls, CSV selection через `QFileDialog`, messages через `QMessageBox` і tabular data до `QTableView` або `QTableWidget`.

#### P.14.3. Browser and monitoring integration

Інтегрувати browser lifecycle і monitoring workers через Qt-safe mechanisms та Qt signals без прямого оновлення widgets з background threads.

#### P.14.4. Tkinter removal

Видалити Tkinter UI, dependencies і пов’язаний GUI state після підтвердження parity та проходження PySide6 tests.

Обов’язкові тести:

- main window creation;
- correct initial UI state;
- CSV loading;
- monitoring start and stop;
- browser launch failure;
- worker exception handling;
- retry after failure;
- closing the application during monitoring;
- no direct widget updates from background threads.

### P.15. Windows executable packaging

Primary packaging tool: `PyInstaller`.

Fallback packaging tool: `cx_Freeze`.

Packaging починати лише після завершення:

- automatic default browser detection;
- PySide6 migration;
- monitoring integration;
- resource cleanup;
- stable application paths;
- passing the full test suite.

Підготувати:

- PyInstaller `.spec` file;
- application icon;
- version metadata;
- executable name;
- application data paths;
- writable user-data directory;
- logs and output directories;
- bundled configuration;
- bundled Qt plugins;
- Playwright and browser dependency strategy;
- clean-build script;
- release-build script.

Перший packaging mode:

- `onedir`;
- `windowed`;
- without a console window.

`onefile` залишити як later-stage option після стабілізації `onedir`.

Runtime data не повинні записуватися до temporary directory PyInstaller. Рекомендована writable location:

`%LOCALAPPDATA%\PrismaFunction\`

Packaging checks:

- launch on Windows without Python installed;
- launch from a path containing spaces;
- launch without administrator rights;
- Qt platform plugin loading;
- default browser detection;
- Chrome and Edge launch through Playwright;
- CSV selection;
- monitoring start and stop;
- writable database, result, and log directories;
- successful retry;
- safe removal without changing system settings.

### P.16. Windows release readiness

Final release checks:

- clean build;
- application icon and version metadata;
- Windows Defender scan;
- clean Windows machine or VM;
- no Python installed;
- Chrome as default browser;
- Edge as default browser;
- unsupported default browser;
- valid and invalid CSV;
- monitoring start and stop;
- browser cleanup;
- application shutdown;
- log generation;
- result generation;
- upgrade from a previous build;
- installation and usage documentation.

Результат етапу:

- release archive;
- versioned executable;
- checksum;
- release notes;
- installation instructions.

### P.17. Remove the manual browser selector from the UI

Status: **Completed**.

Remove the manual Chrome/Edge selector and all UI state that exists only to support manual browser selection.

Completion note: The manual Chrome/Edge selector and its UI-only state were removed.

### P.18. Use the operating system default browser automatically

Status: **Completed**.

Automatically detect and use the browser configured as the operating system default, while preserving clear error handling for unsupported or invalid browser associations.

Completion note: The application now detects and uses the operating system default browser, with handling for unsupported or invalid browser associations.

### P.19. Evaluate and select the Qt GUI framework

Status: **Completed**.

Evaluate the following Qt-based GUI frameworks:

- `PySide6`;
- `PyQt6`.

Select the framework based on licensing, packaging, maintenance, documentation, and project compatibility before starting the GUI migration.

Completion note: PySide6 was selected as the Qt framework.

### P.20. Migrate the Tkinter interface to the selected Qt framework

Status: **Completed**.

Migrate the current Tkinter interface to the Qt-based framework selected in P.19 while preserving existing application behavior, UI states, error handling, and background-work safety.

Completion note: The Tkinter GUI was migrated to PySide6 while preserving application behavior, background-work safety, error handling, and tests. The full test suite passed with `125 passed`.

### P.21. Package the application as a Windows executable

Status: **Completed**.

Package the application as a Windows `.exe` after the Qt migration is complete.

Packaging tools to evaluate:

- evaluate `PyInstaller` first;
- retain `cx_Freeze` as an alternative.

Completion note: Added a pinned PyInstaller build dependency, a version-controlled
windowed `onedir` specification for `PrismaFunction.exe`, a clean Windows build
script using the active Python environment, packaging documentation, Git ignores,
and focused configuration tests. Clean-environment executable validation remains
in P.22.

### P.22. Validate the packaged executable on a clean Windows environment

Status: **In progress — physical-PC validation exposed an intermittent browser runtime crash; clean-Windows validation has not passed**.

Validate the packaged executable on a clean physical Windows computer without a project development environment or Python installation, including launch, default-browser use, CSV loading, monitoring, shutdown, and writable data paths.

Progress note: the documented windowed onedir build succeeded and package
contents, direct non-admin process launch, launch from a path containing spaces,
and writes beside the package were checked on the Windows development host.
This host is not a clean machine, its sandbox user has no configured HTTP default
browser, and its packaged GUI was not interactively accessible. A VirtualBox
validation attempt was discontinued because the VM setup was unreliable and
repeatedly returned to Windows installation. Virtual machines are no longer part
of the planned validation approach. Use `P22_CLEAN_WINDOWS_CHECKLIST.md` when a
separate physical Windows computer is available. The clean-machine GUI, CSV,
monitoring, browser, graceful-shutdown, cleanup, retry, and protected
install-location checks remain. See `P22_VALIDATION.md`.

#### P.22.1. Add persistent packaged-browser runtime diagnostics

Status: **Completed (diagnostic increment only); P.22 remains In progress**.

Validation on a second physical Windows PC confirmed package launch, matching
executable SHA-256, and default Chrome/Edge launch through Playwright, but exposed
an intermittent browser closure after several minutes or sometimes on window
maximize. The root cause is not yet determined. Persistent, generation-scoped
runtime and browser lifecycle diagnostics were added to collect evidence without
changing launch flags, browser selection, retry/relaunch behavior, lifecycle
synchronization, generation protection, cleanup, or UI result semantics. This
does not mark clean-Windows validation complete.

### P.23. Live PRISMA auction monitoring

Status: **Completed — P.23.1, P.23.2, and P.23.3 are Completed**.

Use the Playwright page owned by the existing browser lifecycle as the live
monitoring source. Authentication/session support and complete recovery for
timeouts, unavailable pages, DOM changes, and manual browser closure are separate
follow-up increments.

#### P.23.1. Implement live PRISMA page adapter

Status: **Completed**.

Completion note: validated the source application against the real public PRISMA
short-and-long-term auctions page in system-default Chrome. The live page loaded
with its research-consent banner untouched, the existing Start of Auction date
filter remained active, and the current filter panel accepted `Marketed >= 1000`.
The adapter inspected the rendered table, matched auction `62255317` by the live
`Auction ID` column, read live status `Finished`, and normalized it to `Completed`
on repeated scheduled checks. Live-site differences were corrected by supporting
the collapsed current-design filter panel (`Marketed` plus `Filter`) and selecting
the rendered header row instead of PRISMA's empty sorting-header row. Missing rows
remained typed failures, delayed loading completed safely, stopping monitoring
restored the UI, and stopping the application-managed browser closed only its
PRISMA page while unrelated Chrome remained open. Runtime logs recorded lifecycle,
filter, public auction ID, result, and cleanup diagnostics without cookies,
credentials, or account data. Focused regression tests were added for both live
DOM corrections. Authentication and broader recovery remain scoped to P.23.2 and
P.23.3; clean-Windows validation is not claimed by this increment.

#### P.23.2. Add authentication/session handling if required

Status: **Completed**.

Completion note: P.23.1 live-site evidence established that the current daily
auctions workflow is public and works without authentication, including with the
research-consent banner left untouched. P.23.2 therefore adds focused validation
of the existing lifecycle-owned page before filtering and every live table read.
It accepts the expected PRISMA origin/path only when a meaningful auctions-page
landmark is visible, tolerates delayed rendering, recognizes authentication by a
sanitized redirect path or visible login structure, and reports typed
authentication-required or invalid-session failures. Diagnostics contain only
generation, safe classification, and origin/path without query strings, fragments,
userinfo, page content, cookies, storage, or session identifiers. No credentials,
cookie/profile persistence, login automation, retry loop, second browser, context,
or page were added. P.23 remains in progress because P.23.3 recovery work is not
complete.

#### P.23.3. Harden live-page failure and recovery behavior

Status: **Completed**.

Handle live-page timeouts, unavailable pages, DOM changes, and manually closed
browsers with complete recovery and user-visible lifecycle behavior.

Completion note: every live lookup now has a bounded controller wait and reports
a typed timeout instead of blocking a monitoring cycle indefinitely. A timeout
stops only its owning browser generation, abandons the stale request, and returns
the UI to a retryable non-monitoring state without automatic relaunch or an
unbounded retry loop. Closed or unusable pages, contexts, and browser disconnects
are converted to stable application-level failures; generation-aware lifecycle
callbacks stop active monitoring, perform idempotent managed-resource cleanup,
and cannot overwrite a newer generation. Normal `Stop Browser` cleanup remains
classified as user-requested and does not produce an unexpected-failure result.

Missing tables or required headers, malformed rows, unreadable statuses, and
ambiguous auction matches are typed page-structure failures. A genuinely absent
auction ID remains a separate typed result from a valid table, and live monitoring
never falls back to CSV data or fabricates a status. English UI messages distinguish
timeout, unavailable/closed page, unreadable page structure, and a missing auction.
Diagnostics record generation, lifecycle classification, termination type, and
retryable recovery without cookies, credentials, storage state, or page HTML.

Verification used deterministic fake pages and browsers only. The complete suite
passed with 185 tests. Project source and tests compiled successfully, and the
final diff passed whitespace validation. Manual validation with a real public
PRISMA session is still recommended for browser-close, disconnect, and live DOM
timing behavior; no new real-site validation is claimed by this increment.

### P.29. Add project-wide Windows CI

Status: **Completed**.

Run project-wide validation on GitHub Actions using `windows-latest` and pinned
project dependencies. The workflow runs for pushes to `main`, pull requests
targeting `main`, and manual dispatches. It executes the complete pytest suite
with headless Qt settings, compiles the project Python sources and tests, and
builds the existing PyInstaller specification as a packaging validation without
publishing a release or uploading build artifacts. Concurrent runs for the same
branch or pull request are cancelled when superseded.

Completion note: The Windows CI workflow and local reproduction instructions
were added and all relevant local validation passed. CI does not install
Playwright browser binaries and does not require secrets or interactive desktop
access.

### P.30. Final release readiness and versioned release archive

Status: **Completed (repository-side)**.

Version 1.0.0 is now authoritative in `version.py` and is exposed through Qt,
the compact window title, and PyInstaller Windows executable metadata. The
deterministic PowerShell release workflow validates the onedir executable,
creates `PrismaFunction-v1.0.0-windows-x64.zip` with `PrismaFunction` as its
top-level directory, filters runtime and development artifacts, and writes a
SHA-256 checksum. Automated metadata and script contracts, exact build and
verification instructions, v1.0.0 release notes, and the final release
checklist are included.

Completion note: Repository-side deliverables and automated validation for
this increment are complete. Actual package launch and functional validation,
archive inspection, checksum verification, and validation on a second Windows
PC remain checklist items unless explicitly recorded after running them. The
`v1.0.0` Git tag and GitHub Release publication are manual post-merge actions;
neither is claimed by this increment.

## 5. Git workflow для кожного етапу

1. Оновити `main`.
2. Створити окрему feature branch.
3. Реалізувати один завершений етап через Codex.
4. Перевірити:
   - `git status --short`;
   - `git diff --stat`;
   - `git diff`.
5. Запустити тести.
6. Виконати GitHub Copilot review без редагування.
7. За потреби створити окремий Codex prompt для виправлень.
8. Повторно запустити тести.
9. Створити commit.
10. Push branch.
11. Створити Pull Request.
12. Merge у `main`.
13. Оновити локальний `main`.
14. Видалити локальну та remote feature branch.
15. Наступний етап почати в новому чаті.

### P.31. Modern PySide6 monitoring dashboard

Status: **Completed**.

The desktop interface now uses a responsive monitoring-dashboard layout with a
graphite workflow sidebar and a light main workspace. It provides explicit
browser and monitoring state badges, context-aware controls, truthful summary
counters, and a model-backed auction table with search, status filtering, and
incremental live-result updates. Recent user-relevant activity is visible
without replacing rotating diagnostic logs, and the log directory can be
opened through Qt. Presentation code, filtering, table state, status delegates,
and the centralized theme are separated from browser and monitoring logic.

Completion note: Focused offscreen Qt coverage verifies initial state, CSV and
browser transitions, stale generations, monitoring prerequisites and lifecycle,
incremental counters and rows, search/filter behavior, activity handling,
stable error wording, and managed-resource shutdown. Manual visual checks at
Windows display scaling levels from 125% through 200% remain recommended.

### P.32. Windows installer and uninstaller using Inno Setup

Status: **Completed**.

The version-controlled `PrismaFunction.iss` definition builds a per-user Inno
Setup installer from the existing PyInstaller onedir distribution at
`dist\PrismaFunction`. Installation does not require administrator privileges
and defaults to `%LOCALAPPDATA%\Programs\PrismaFunction`.

The installer uses the authoritative application identity and executable version
metadata, creates a Start Menu shortcut, offers an optional desktop shortcut,
supports paths containing spaces, and includes a functional uninstaller. A
stable application identifier supports in-place upgrades of later versions.

Only the validated packaged runtime is installed. Python source, tests,
development files, caches, runtime databases, logs, generated workbooks, and
other writable user data are excluded. Uninstall removes installed application
files and shortcuts but intentionally preserves application-owned runtime data
below `%LOCALAPPDATA%\PrismaFunction`.

`build-installer.bat` validates the existing PyInstaller distribution and invokes
Inno Setup 6. Optional signing is supported through the documented Inno Setup
sign-tool configuration. Deterministic tests verify the installer contract,
per-user behavior, shortcut definitions, upgrade identity, uninstall behavior,
and packaging exclusions. Build, signing, installation, upgrade, uninstall, and
manual validation procedures are documented in `INSTALLER.md`.

### P.33. Unified PRISMA CSV import foundation

Status: **Completed — P.33.1-P.33.7 are Completed**.

P.33 separates two independent inputs that must never be converted into or
silently substituted for one another.

#### CSV contracts

The **Monitoring CSV** configures live auction monitoring. It is UTF-8,
comma-delimited, and has exactly these columns in this order:
`auction_id`, `auction_url`, `lot_number`, `item_name`, `expected_status`,
`last_known_status`, `check_interval_seconds`, `enabled`. Existing row
validation in `load_auction_csv()` remains authoritative and backward
compatible. A UTF-8 BOM is not accepted by the established contract.

The **PRISMA Export CSV** is a raw export downloaded from PRISMA. It is cp1252,
semicolon-delimited, and has exactly these columns in this order:
`Auction ID`, `Start of Auction`, `Network Point Name Exit`,
`Network Point EIC Exit`, `Network Point Type Exit`, `Network Point ID Exit`,
`Network Point Name Entry`, `Network Point EIC Entry`,
`Network Point Type Entry`, `Network Point ID Entry`,
`Network Point Name Exit/Entry`, `Network Point EIC Exit/Entry`,
`Network Point ID Exit/Entry`, `Published capacity`,
`Published capacity unit`, `Marketable Capacity`,
`Unit Marketable Capacity`, `Marketed Capacity`, `Unit Marketed Capacity`,
`Regulated Tariff Exit TSO`, `Unit Regulated Exit Capacity Tariff`,
`Regulated Tariff Entry TSO`, `Unit Regulated Entry Capacity Tariff`,
`Surcharge`, `Unit Surcharge`, `Product Runtime Start`, `Product Runtime End`,
`Capacity Category`, `TSO Exit`, `TSO EIC Exit`, `TSO Entry`, `TSO EIC Entry`,
`Direction`, `Type of Gas`, `State`. A BOM is not part of the confirmed export
contract.

#### P.33.1. Separate and detect both CSV contracts

Status: **Completed**.

P.33.1 adds a single source of truth for both exact headers and a public typed
detection/routing API. Detection reads only the header, uses structure rather
than the filename, returns `monitoring`, `prisma_export`, `unsupported`, or
`ambiguous`, and rejects incomplete headers, duplicates, wrong delimiters,
empty files, and unknown formats with specific English errors. Ambiguity is an
explicit outcome for API stability, although it is structurally impossible for
the current exact, disjoint headers. `process_csv()` explicitly requires a
PRISMA export; `load_auction_csv()` keeps its existing monitoring validation.

Definition of Done for P.33.1: the real repository export confirms the complete
PRISMA header; both exact contracts and reading rules have one source of truth;
no partial or fallback detection occurs; existing capacity, tariff, surcharge,
product-type, direction, database, Excel, browser, monitoring, and UI behavior
is unchanged; focused and complete tests pass; project Python files compile;
and the final diff passes whitespace validation.

#### P.33.2. Complete original PRISMA export import — Completed

The detailed importer classifies every physical source row as imported,
filtered, or rejected and reports human-readable CSV row numbers, stable reason
codes, English messages, and invariant counts. Issues intentionally do not copy
complete source rows. The compatibility `process_csv(path)` entry point still
requires the exact PRISMA Export contract and returns only imported normalized
row dictionaries.

Marketed capacity supports `kWh/h`, `MWh/h` (×1000), and `kWh/d` (÷24). Valid
values below 1000 kWh/h are filtered; empty, malformed, negative, non-finite,
and unsupported-unit values are rejected. Entry, Exit, and Exit/Entry map to
`entry`, `exit`, and `bundle`, using their corresponding network-point fields.
Dates use strict `DD.MM.YYYY HH:MM` parsing and runtime must be positive. Product
types are `WD` for runtimes through 24 hours beginning on the auction calendar
date, `Day Ahead` for other runtimes through 24 hours, then `Month` through 31
days, `Quarter` through 93 days, and `Year` above 93 days.

Regulated tariff components and surcharge support only
`cent/kWh/h/Runtime` (×10) and `cent/kWh/d/Runtime` (×10 ÷24), producing
EUR/MWh/h values. An empty value/unit pair is zero. Unsupported currencies,
including pence and halér, are explicitly rejected rather than converted or
mislabelled as EUR.

#### P.33.3. Market and storage reference enrichment — Completed

P.33.3 adds `prisma_references.py`, a UI-independent immutable catalog of stable
canonical references, explicit classifications (`market` or `storage`), and
side-specific aliases. Lookup strips surrounding whitespace and compares case
insensitively. It performs no fuzzy, substring, or inferred matching. Catalog
construction rejects blank, surrounding-whitespace, duplicate, or conflicting
canonical names and duplicate/conflicting side/alias pairs, both within one
entry and across entries.

Semantic P.33.2 imports are enriched only after parsing and validation succeed.
The normalized source `Direction` remains authoritative: `entry` requires the
entry-side value, `exit` requires the exit-side value, and `bundle` requires
both. A populated side irrelevant to that direction is preserved in `raw_row`
but ignored; it cannot alter direction, network point, or enrichment. A missing
required side or unknown required alias rejects the row with a typed enrichment
reason code plus field, side, and unchanged source-value context.

Successful detailed records retain the unchanged 18-field normalized row, an
immutable copy of the complete raw row, the starting physical source line, and
optional side-specific `exit_reference` / `entry_reference` values. Each
resolved reference contains its canonical name, `market` or `storage`
classification, and side. `process_csv()` and normalized row dictionary keys
remain backward compatible; legacy `exit_market` and `entry_market` names are
preserved for P.33.2 compatibility even when the classified reference is a
storage facility.

The deliberately small seed catalog contains the exact five market mappings
from `mapping.csv` (BG/HTP, BG/RS, CEGH/MGP, CEGH/PSV, and CEGH/SK) and the VGS
Storage Hub alias evidenced by `Auction_overview.csv`. It is not represented as
a complete PRISMA catalog. Extend it only by adding confirmed `PrismaReference`
entries and explicit side aliases to `DEFAULT_PRISMA_REFERENCES`; constructor
validation prevents ambiguous additions.

Validation evidence covers direction authority, side mismatches, classified
market/storage references, bundles, exact normalized aliases, unknown/missing
required sides, intra-entry and cross-entry alias conflicts, raw/source-line
preservation, compatibility, and deterministic ordering.
`python -m compileall .` and `git diff --check` also pass.

#### P.33.4. Controlled daily source updates

Status: **Completed**.

`prisma_source_updates.py` provides a deterministic, UI-independent lifecycle
boundary for caller-supplied local PRISMA Export CSV files. The caller supplies
an exact `datetime.date`, a timezone-aware evaluation time, and the previous
immutable accepted state. The policy computes SHA-256 from the exact file bytes
and exposes only the basename in audit metadata. It never infers dates or reads
the clock.

The stable lifecycle statuses are `APPLIED`, `UNCHANGED`, and `REJECTED`, with
typed reasons for applied, identical, stale, conflicting, future-dated, and
invalid sources. A first or newer valid source is applied. An already accepted
date and digest is unchanged without rerunning the importer; different content
for an accepted date, stale dates, and future dates are rejected before import.
`import_prisma_export()` remains the authoritative validation boundary. Fatal
validation never advances state or exposes a partial import, while header-only
exports and row-level filtered/rejected outcomes remain valid auditable imports.
Only an applied result returns advanced accepted state.

The pure daily due policy compares a caller-supplied aware local evaluation time
with an explicit wall-clock scheduled time. It does not sleep, start threads, or
read the system clock; acceptance for the source date suppresses another due
update. Tests cover local times before and after the schedule and non-UTC
offsets.

P.33.4 does not change `MonitoringScheduler`, `AuctionStorage`, SQLite schemas,
the UI, or source files. It adds no threads, browser automation, downloads, or
persistence. End-to-end persistence/UI integration and user-facing issue
reporting are completed in P.33.5. Automatic downloading remains outside the
confirmed local-file import scope.

Validation evidence: focused lifecycle policy tests, affected processor/storage/
scheduler contract tests, the complete pytest suite, Python source compilation,
and `git diff --check` pass for this increment.

#### P.33.5. Integrate the completed import workflow — Completed

SQLite is the authoritative source-operation ledger. Each operation is identified
by source date, exact-byte SHA-256 digest, and a generated operation ID. A pending
record is durable before auction mutation; auction changes, persisted summary
metadata, and the `data_committed` transition are one transaction. The cumulative
workbook is generated under a unique name in its destination directory, closed,
validated, and atomically replaced before the operation becomes `accepted`.
Failures retain a recoverable ledger state and never overwrite a prior workbook;
a conflicting same-date digest is blocked until recovery. Exact retries report
the stored accepted summary and regenerate a missing or invalid workbook from
SQLite without changing auction rows. Legacy accepted-state JSON remains readable
when no ledger exists, but SQLite owns all new lifecycle decisions.

Automatic browser downloading and authentication automation remain outside P.33.5;
the workflow accepts only an explicitly selected local PRISMA Export CSV.

P.33.5 adds an explicit `Import PRISMA Export` action and source-date control to
the PySide6 UI. It is independent from `Load Monitoring CSV`, which remains the
Monitoring CSV entry point. The central contract detector rejects Monitoring,
unsupported, and ambiguous inputs with specific English messages before detailed import.

`prisma_import_workflow.py` is the UI-independent orchestration boundary. It
uses the existing audited importer, reference enrichment, controlled daily
source policy, SQLite operation transaction, and atomic Excel export. Parsing,
enrichment, and update rules are not duplicated in the UI.

Long-running work executes outside the Qt GUI thread. Qt signals restore the
controls on success or failure, while status and activity report processed,
inserted, updated, unchanged, filtered, rejected/audit issue counts, issue
details, and output destination. Browser ownership, monitoring, scheduler,
search/filter/table counters, shutdown, and Monitoring CSV semantics remain
unchanged. Automatic downloading, authentication automation, and schema
redesign are outside this completed local-file integration scope.

Validation evidence: focused workflow/storage/UI recovery tests pass (52 tests),
focused importer/reference/source-policy/contract tests pass (101 tests), and
the complete suite passes (299 tests). Production modules compile and the final
diff passes whitespace validation.

#### P.33.6. Manual validation fixes — Completed

P.33.6 completes two changes identified by manual validation. The Monitoring CSV
action is labelled `Load Monitoring CSV` consistently in the button, file dialog,
and PRISMA-import rejection guidance without renaming its established internal
APIs or the separate `Import PRISMA Export` action. The cumulative `Auctions`
worksheet now receives one deterministic header-keyed set of column widths after
pandas creates the staged workbook. Widths are verified with a numeric tolerance
by the existing openpyxl validation boundary before atomic publication, for both
header-only and populated output. An exact retry therefore repairs an otherwise
valid legacy workbook with default widths from authoritative SQLite data without
mutating auction rows or changing source-operation semantics. Microsoft Excel is
not required.

Historical Market / Storage backfill was investigated but is deliberately not
implemented in P.33.6. Automatic backfill during normal import/update is rejected.
Existing nonblank values must never be overwritten because their provenance and
possible user edits are unknown. A future explicit maintenance operation may
enrich only blank single-side rows whose direction is exactly `entry` or `exit`,
whose retained network point is present, and for which the current reference
catalog returns one exact side-aware canonical match. Unknown, ambiguous,
missing-identity, and insufficient-identity rows must be skipped and audited.
Historical bundle rows cannot be reconstructed safely because SQLite does not
retain both original side-specific source identities. `network_point_id` must not
be used until an authoritative mapping exists. Fuzzy, substring, TSO-based, and
display-text guessing are prohibited.

Any future historical maintenance operation must be explicit, transactional,
idempotent, rollback-safe, and auditable at row level. Its execution surface and
durable audit format remain product decisions. P.33.6 does not add a migration,
GUI maintenance action, CLI, automatic backfill, database mutation, or new
maintenance module, and it does not claim that historical rows were modified.

Acceptance criteria: the UI-label fix and Excel-width fix are implemented and
covered by focused regression tests; legacy default-width output is repairable by
exact retry without database-row changes; the backfill safety investigation and
its constraints are documented; implementation of an explicit historical
maintenance backfill remains a deferred follow-up. Focused and complete tests,
Python compilation, and whitespace validation pass.

#### P.33.7. Explicit historical Market / Storage backfill — Completed

`AuctionStorage.backfill_historical_market_storage()` is the sole public launch
point. It is never called by schema creation, application startup, CSV import,
daily update, export, or storage opening. There is no overwrite mode. The
existing immutable `DEFAULT_PRISMA_REFERENCES` catalog, or an explicitly supplied
`PrismaReferenceCatalog`, remains the only mapping authority.

Storage initialization enables and verifies foreign keys outside a transaction,
then acquires `BEGIN IMMEDIATE` before reading any schema fingerprint. Concurrent
initializers therefore serialize through SQLite's configured busy timeout: a short
overlap waits and reclassifies the committed current schema, while an expired timeout
raises SQLite's lock error without leaving a partial schema. One backfill call likewise
acquires `BEGIN IMMEDIATE` before its first `SELECT`, then examines every
stored auction in stable SQLite `id` order and performs classification, validation,
updates, run/audit insertion, and commit in that transaction. Valid `entry` and
`exit` rows use exact side-aware lookup of the retained `network_point`. NULL or
whitespace-only required-side values are missing. Trimmed, case-insensitive canonical
equivalents retain their original representation; genuine conflicts leave the entire
row unchanged. Unknown aliases are skipped. Malformed dates, reversed intervals,
missing identities/product types, and invalid or non-finite persisted numerics are invalid;
naive flow timestamps are compared only with naive timestamps, aware timestamps are
compared as instants, and mixed-awareness or otherwise unorderable pairs are invalid;
bundle rows are skipped because both original side identities were not retained.

The typed `HistoricalBackfillSummary` includes a collision-safe `run_id` and reports `examined`, `updated`, `unchanged`,
`skipped`, `conflicts`, `invalid`, `committed`, and ordered row audit. Mutually
exclusive row counts equal `examined`. Each `HistoricalBackfillAudit` contains
the SQLite row id and composite key, previous and resolved values, status,
machine-readable reason, English message, and changed flag. Statuses are
`updated`, `unchanged/already_complete`, `skipped/unresolvable`, `conflict`, and
`invalid`. Reasons are `missing_values_filled`, `already_complete`,
`reference_unresolvable`, `insufficient_bundle_identity`, `reference_conflict`,
and `invalid_historical_row`.

Each successful invocation appends a UTC-timestamped `committed` record to
`historical_market_storage_runs` and exactly one positioned row record per examined
physical auction to `historical_market_storage_audit`; `(run_id, auction_row_id)` is
the row-audit primary key. Both foreign keys use `ON DELETE RESTRICT`, and every
storage connection enables and verifies `PRAGMA foreign_keys = ON`. The unreleased
single-column experimental audit table is replaced only when its ordered column name,
declared type, NULL/default/PK metadata, foreign keys, and indexes exactly match that
one known fingerprint. The current runs/audit tables are likewise accepted only with
their exact `table_info`, foreign-key, and index fingerprints, including the stable
`auction_row_id` index. Any unknown, extended, or partial schema fails closed before
mutation. Migration uses separate DDL statements in one explicit transaction: dropping
the experimental table and creating runs, audit, and indexes commit or roll back together,
and `auctions` is never dropped or rebuilt. Ordinary pre-P.33.7 databases initialize
normally. Every production storage connection is closed exactly once after transaction
completion on both success and exception paths. A close failure after success remains
visible; while another failure is active, rollback and close diagnostics are attached
best-effort, and failure of that diagnostic mechanism never replaces the primary
exception or traceback. If SQLite rollback itself fails, only preservation of the primary
exception and a deterministic close attempt are guaranteed. When rollback succeeds,
processing, SQL, audit, or validation exceptions roll back auctions, the run, and row
audit and return no success summary. A successful repeat changes no auction rows, appends its own
run/audit history, and reports them as already complete. Invocation remains API-only.

#### P.33.8. Expanded authoritative Market / Storage mapping — Completed

The immutable default reference catalog now covers every exact side-specific
network-point name that the checked-in `Auction_overview.csv` explicitly marks as
`RESERVOIR`: 37 Exit aliases and 37 Entry aliases. The existing five Market pairs
remain the exact mappings from `mapping.csv`; no market identity was derived from
TSO, EIC, display text, or geography.

Storage aliases are declared separately for Exit and Entry. An alias observed on
only one side is not assumed to be valid on the other side. Exact source strings
that occur on both sides share one catalog entry, while different injection and
withdrawal names remain distinct instead of being grouped heuristically. The
established `VGS Storage Hub` canonical display name is preserved for backward
compatibility. Lookup normalization remains limited to surrounding whitespace and
case, and constructor conflict detection is unchanged.

Regression coverage derives the authoritative Storage sets from the checked-in
export and proves both completeness and absence of unevidenced Storage aliases for
each side. It also verifies that a one-sided Storage alias cannot resolve on the
unevidenced side. Import contracts, normalized row fields, persistence schemas,
backfill semantics, and UI behavior are unchanged.

### P.34.1. Safe auction deduplication — Completed

Every imported auction requires the nonblank selected network-point ID for its
normalized direction: `Network Point ID Entry` for Entry, `Network Point ID Exit`
for Exit, and `Network Point ID Exit/Entry` for Exit/Entry. Blank and
whitespace-only selected IDs are rejected as audited source rows with reason code
`missing_network_point_id`, the exact selected field name, the original source
value, and the applicable `entry` or `exit` side; bundle issues have no single
side. Existing normalization trims surrounding whitespace while preserving valid
identifier text, including leading zeroes.

Network-point names are display and enrichment values, not identity fallbacks.
The persisted identity remains the existing five fields: `auction_id`,
`network_point_id`, `direction`, `flow_start`, and `flow_end`.

`AuctionStorage` validates the complete caller-supplied batch before its first
auction `INSERT` or `UPDATE`. A blank or whitespace-only `network_point_id` fails
with `AuctionStorageError`. Identical rows sharing one identity remain idempotent
and retain the established processed/inserted/updated/unchanged accounting.
Different persisted values sharing one identity are a conflicting batch and fail
closed with `AuctionStorageError`; no row from that batch can insert or modify an
auction, so existing stored auctions remain unchanged.

P.34.1 does not change or rebuild the SQLite `auctions` schema or its unique
constraint. It performs no migration, deletion, or modification of historical
rows. P.26 runtime-data-path work is explicitly outside this increment.

Acceptance evidence covers Entry, Exit, and Exit/Entry audit context;
whitespace-only IDs; preservation of valid IDs; identical duplicates; conflicts
against empty and populated databases; direct storage validation; reference
enrichment; and the integrated import workflow. Focused and complete tests,
Python compilation, and whitespace validation are required.

### P.24. Persist monitoring checks and status transitions

Status: **Completed**.

Every actual live lookup is stored in the runtime SQLite database at
`RuntimePaths.database`. The monitoring schema is additive and semantically
independent from PRISMA Export auctions, source-operation ledgers, and historical
backfill tables. It contains an immutable check history, a transition history
linked to its originating check by an enforced foreign key, and one latest
successful status row per exact textual auction ID. Schema creation uses
`CREATE TABLE IF NOT EXISTS`, deterministic indexes, verified foreign-key
enforcement, and a write-reserving transaction, preserving existing database
content.

The live lookup runs without holding a database transaction. When its observation
is ready to persist, the storage transaction reads the latest successfully
persisted status for that exact auction ID. If none exists, the caller-supplied
Monitoring CSV `last_known_status` is the initial baseline; the CSV is never
rewritten. Storage, rather than the engine or caller, derives the final
`previous_status`, `status_changed`, and `Success`/`Changed` classification. A
successful observation always advances latest state. It produces a transition
only when its current status differs from that authoritative effective baseline.
Repeated observations therefore remain visible as checks without duplicate transitions.
An `Error` check retains the effective baseline as both previous and fallback
current status, is audited, and neither advances state nor creates a transition.
`Skipped` means that no live lookup occurred and is not persisted.

Authoritative baseline resolution, canonical classification, the check, its
optional transition, and successful latest-state update occur in one
`BEGIN IMMEDIATE` transaction. Rollback and close diagnostics never
replace the primary failure. Event timestamps come from application-owned,
timezone-aware datetimes and are normalized to ISO-8601 UTC with a `Z` suffix;
SQLite `CURRENT_TIMESTAMP` is not used for monitoring event time. Short-lived
connections make the abstraction safe for the existing worker-thread model.
The worker persists synchronously before the scheduler callback emits results
to Qt. A persistence failure terminates the run, returns the GUI to its
retryable idle state, shows a stable English error, and does not emit the
unpersisted cycle as a successful UI update. Reopening the application or a new
persistence object against the same database restores the baseline.

Deterministically ordered read APIs expose all checks and transitions with an
optional auction-ID filter, plus latest-status lookup for one auction or a set.
The records returned by these APIs are immutable typed dataclasses. P.24 adds no
notification behavior or UI; user-visible status-change notifications remain
exclusively P.25.

Automated validation covers additive schema initialization, foreign keys,
unchanged and changed observations, repeated and sequential transitions, error
and skipped semantics, rollback, restart restoration, stale-CSV override,
independent IDs, ordering, timezone normalization, runtime-path wiring, worker
ordering/failure recovery, and existing monitoring/import/storage/packaging
regressions. No manual live-session or installed-package validation is claimed
for P.24.

### P.25. User-visible status-change notifications

Status: **Completed; manual Windows visual/accessibility validation remains recommended**.

Notifications are derived only from the persisted `MonitoringResult` objects
delivered for the current monitoring cycle through the existing
`monitoring_results` Qt signal. An immutable notification value object owns the
independently testable decision and exact message formatting. A result is
eligible only when `status_changed` is true, `result` is exactly `Changed`, and
trimmed previous and current statuses are both nonempty and different. Its
stable English message is `Auction <auction_id>: <previous_status> →
<current_status>`.

Initial baselines, successful unchanged checks, skipped or disabled records,
lookup errors, persistence failures, malformed empty or equal statuses, cycle
summaries, and historical transitions read after restart do not create
notifications. No notification history is persisted or replayed; P.24 remains
the sole persistence authority. No toast, tray, email, sound, network, modal,
or background-service behavior was added.

Eligible transitions appear in scheduler result order directly below the one
existing aggregate summary for that cycle in Recent activity. Status-change
entries carry an explicit textual label, bold emphasis, contrasting foreground,
an accessible description, and a typed item role, so distinction does not rely
on color. Notifications and ordinary activity share the existing newest-first
50-item bound and Clear action. All widget mutation remains in the Qt main-thread
slot reached through the existing signal/slot boundary.

Focused automated validation covers exact eligibility and formatting, one and
multiple ordered changes, unchanged/baseline/error/skipped/malformed results,
mixed bounded history, accessible presentation, Qt signal delivery, and exactly
one aggregate cycle summary. The complete pytest suite, Python compilation, and
whitespace validation passed for this increment. A manual Windows smoke check
of visual contrast, screen-reader wording, and live-transition appearance is
still recommended; no such manual validation is claimed here.

### P.26. Move writable runtime data to the user data directory

Status: **Completed; manual installed-package migration smoke testing remains recommended**.

One authoritative runtime-path module resolves source and frozen execution to
the same Windows user-data root. `LOCALAPPDATA` must be absolute; when it is
missing, the deterministic Windows-compatible fallback is
`%USERPROFILE%\AppData\Local` (or the equivalent home directory). The
application never uses its installation directory, bundle directory, current
working directory, or temporary directory as a normal-write fallback.

Final layout:

```text
%LOCALAPPDATA%\PrismaFunction\
  data\prisma_monitor.db
  data\result\prisma_auctions.xlsx
  state\prisma_import_state.json
  logs\prisma-function.log[.1-.3]
```

At startup, Qt is created first so path failures can be reported visibly. The
runtime paths are then validated once and the required file logger is opened in
the new location before migration begins. If that handler cannot be created,
startup stops and migration is not called; no claim is made that file
diagnostics exist. Migration then covers only paths confirmed by the
application's prior code: `data\prisma_monitor.db`,
`data\result\prisma_auctions.xlsx`, and `data\prisma_import_state.json` beside
the source tree or packaged executable, plus the former
`%TEMP%\PrismaFunction\logs\prisma-function.log[.1-.3]` logging fallback.
User-selected CSV files and unrelated files are never scanned or moved.

The legacy current log normally conflicts with the newly opened current log, so
it is retained as a deterministic `.legacy-<digest>` copy rather than replacing
the active handler's file. Rotated legacy logs follow the same conflict policy.

An atomically created lock directory with a unique PID/token owner record
serializes concurrent launches. A briefly empty or malformed new lock is never
removed. Recovery requires a minimum age and a non-running or unreadable stale
owner. On Windows, stale removal and release open the directory with read-only
identity/query plus synchronization/delete rights, verify its volume/file ID,
and rename that exact handle to quarantine; this prevents a path replacement
from being removed. Release also checks the exact owner token. Process liveness
uses read-only `OpenProcess` and `WaitForSingleObject` queries with guaranteed
handle cleanup, never process signaling. SQLite uses the
SQLite backup API and an integrity check, incorporating committed WAL content
without copying `-wal` or `-shm` blindly. Source and destination are compared as
consistent verified snapshots using deterministic logical content, never as a
normalized backup versus raw live bytes. Other artifacts are copied to a staged
file, SHA-256 verified, and atomically published. Repeated migration treats an
identical destination as complete. A different destination is preserved and
the legacy version is retained beside it as `.legacy-<digest>`; the original
source also remains available. Staged files are removed after interruption and
migration retries on the next launch. Path escape outside the confirmed roots
is rejected.

If the user-data root, SQLite backup, verification, or migration lock cannot be
used safely, startup stops with an actionable data error; it does not create a
new empty database over uncertain legacy data. For recovery, close other
PrismaFunction processes, preserve both legacy and user-data copies, confirm
`LOCALAPPDATA`, and retry. Conflict copies can be inspected or restored
manually after closing PrismaFunction; no conflict is overwritten silently.

### P.27. Package the application with PyInstaller

Status: **Completed; same-machine interactive launch smoke testing remains manual**.

The authoritative `PrismaFunction.spec` now produces a Windows `onedir`,
windowed `PrismaFunction.exe` with no console window. PyInstaller hooks collect
PySide6 and its Windows platform plugin, while the specification explicitly
collects Playwright modules and data, including its Node driver. Application
dependencies are discovered from the production entry point; pytest,
setuptools, source files, caches, and other developer-only content are excluded.
The existing 1.0.0 Windows file and product metadata remain attached.

`validate_package.py` deterministically verifies the executable, Python runtime,
required Qt libraries and platform plugin, and Playwright driver. It also
rejects source/developer files and pre-created writable database, workbook,
state, or log artifacts. Packaged runtime writes continue to resolve only below
`%LOCALAPPDATA%\PrismaFunction`; the distribution is not a write target.
Exact build, structural validation, metadata verification, and isolated
same-machine startup commands are documented in `BUILDING.md`. Clean-machine
validation remains P.28, and no P.32 installer work is included.

### P.28. Validate the executable on a clean Windows environment

Status: **In progress — the 2026-07-18 physical Windows result is Partial / Blocked, not Pass**.

The dated evidence in `P28_VALIDATION_2026-07-18.md` records successful
non-elevated packaged startup, English UI rendering, Chrome launch, public
PRISMA monitoring, header-only export processing, workbook opening, user-data
placement, process cleanup, and relaunch. It also records the remaining blockers:
the computer had developer tools installed, the account was a local
Administrators-group member, the export had no data rows, Edge and unsupported
default browsers were not tested, and disappearing live auction IDs prevented
restart baseline revalidation. A fully clean physical Windows test is still
required; neither P.22 nor P.28 is fully passed.

## 6. Definition of Done

Етап вважається завершеним, коли:

- реалізовано тільки погоджений scope;
- UI text is English;
- CSV headers and values are English;
- помилки обробляються;
- retry працює;
- ресурси очищаються;
- focused tests проходять;
- full test suite проходить;
- each increment demonstrates that it remains consistent with the authoritative customer requirements;
- Copilot review не має невиправлених critical findings;
- зміни об’єднані з `main`;
- feature branch видалена.

### P.34.2. Maximize the managed browser window — Completed

The Playwright-managed Chrome or Edge window launches with Chromium's
`--start-maximized` argument. Its page is created with `no_viewport=True`, so
Playwright does not constrain the rendered PRISMA page to the default fixed
viewport and instead follows the native maximized window size.

Regression coverage verifies both launch settings while preserving default
browser detection, lifecycle ownership, filtering, monitoring, cleanup, and
retry behavior. Focused browser tests, the complete 418-test suite, Python compilation,
whitespace validation, and the manual Windows maximized-window smoke check passed.

### P.35. Authoritative PRISMA reference catalog expansion — Completed

The updated checked-in `Auction_overview.csv` is the only authoritative evidence
for this expansion. The immutable Storage catalog contains every exact nonblank
`Network Point Name Exit` and `Network Point Name Entry` explicitly classified as
`RESERVOIR`: exactly 50 Exit aliases and 51 Entry aliases. Aliases are admitted
only on the side where the export provides that classification.

No cross-side equivalence, canonical grouping, geography, TSO relationship, EIC
relationship, or Market mapping is inferred. The established `VGS Storage Hub`
canonical-name compatibility behavior is preserved, and the five explicit
`mapping.csv` Market mappings are unchanged. Import logic, normalized contracts,
persistence, historical backfill behavior, schemas, and UI behavior are also
unchanged.

Regression coverage derives both exact side-specific sets from the authoritative
export, proves catalog completeness and the absence of unevidenced Storage aliases,
and focuses on newly introduced aliases plus aliases evidenced on only one side.

#### P.35.1. Expand authoritative Market mapping catalog (Batch 1) — Completed

The immutable default Market catalog includes exactly two additional customer-approved,
side-specific network-point aliases: the Entry alias `Arnoldstein importazione
(35718301)` resolves to PSV, and the Exit alias `VIP DK-THE (H646) (H646)` resolves
to THE. Each accepted alias is linked by the same exact Auction ID between
`evidence/p35-1/Auction_overview.csv` and the Market Area on the stated page of
`evidence/p35-1/Auction_Overview.pdf`, and has normalized booked capacity of at least
1000 kWh/h. The filenames, SHA-256 digests, accepted rows, canonical markets,
Marketed Capacity values and units, and PDF pages are recorded in
`evidence/p35-1/EVIDENCE_MANIFEST.md`.

Twelve aliases from the preliminary 14-row candidate set were rejected because their
booked capacity normalizes below 1000 kWh/h. Other rows sharing an Auction ID between
the evidence files were not reviewed or accepted in Batch 1, even where their capacity
may meet the threshold. They remain outside P.35.1 and provide no mappings. This batch
adds no bundle or `RESERVOIR` aliases and makes no inferred, fuzzy, substring,
identifier-only, geographic, TSO, EIC, or automatic mapping available. Aliases remain
strictly side-specific. All earlier Market mappings and the complete Storage catalog
are preserved. Lookup normalization, import behavior, normalized output contracts,
persistence, schemas, historical backfill, UI, and browser behavior are unchanged.
P.35.1 accepts exactly two mappings and makes no completeness claim.

Focused regression coverage proves exact canonical Market resolution for both aliases,
opposite-side rejection for each alias, continued rejection of representative fuzzy,
substring, and identifier-only values, the exact complete Market alias set, and the
existing complete Storage catalog contract.
