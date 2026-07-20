# Prisma Function Mini

Prisma Function Mini is a single-user Windows desktop application for retrieving
and converting official PRISMA auction exports. The user selects a start and end
date in Mini; the application-owned background browser opens PRISMA, applies the
requested dates, downloads the official CSV automatically, and converts
qualifying auctions to the authoritative Excel mapping.

The result is a cumulative `Auctions` workbook. Daily and overlapping imports
preserve existing historical rows, append only new stable auction identities,
and do not create duplicates on exact retries. Market and Storage enrichment is
accepted only from explicit authoritative evidence.

Mini selectively reuses verified parsing, reference, transaction, browser,
runtime-path, and packaging techniques from the legacy Prisma Function product
where they satisfy Mini contracts. Scheduler, notifications, monitoring CSV,
monitoring history, and dashboard monitoring are not part of the Mini product;
inherited monitoring code remains temporarily isolated until roadmap increment
M.13 removes it.

## Authoritative output

The worksheet is named `Auctions` and uses this exact column order:

1. `Auction Date`
2. `Exit Market / Storage`
3. `Entry Market / Storage`
4. `Capacity Type`
5. `Network Point`
6. `Product Type`
7. `Flow Start`
8. `Flow End`
9. `Booked Capacity (kWh/h)`
10. `Duration (hours)`
11. `Auction Tariff (EUR/MWh/h)`

## Implementation status

Roadmap increments M.1 through M.5 are implemented. M.5 adds Mini-specific
transactional SQLite storage at the approved runtime database path. It preserves
cumulative auction history across restarts, enforces the exact five-field M.4
duplicate key, treats identical retries and overlaps idempotently, rejects
same-key payload conflicts without partial auction writes, and records operation
and validation-failure audit details. Atomic Excel publication is M.6; browser
automation, automatic download, the Mini UI, packaging, and real
Windows/PRISMA validation remain later increments.

## Development and tests

Use the repository virtual environment on Windows:

```powershell
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pytest
& .\.venv\Scripts\python.exe -m compileall -q .
```

The current application entry point is `app.py`. It still contains inherited UI
and monitoring behavior scheduled for replacement/removal by later roadmap
increments; it is not yet the completed Mini workflow.
