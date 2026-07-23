# Prisma Function Mini

Prisma Function Mini is a single-user Windows desktop application for retrieving
and converting official PRISMA auction exports. The user selects a start and end
date in Mini; the application-owned background browser opens PRISMA, applies the
requested dates, downloads the official CSV automatically, and converts
qualifying auctions to the authoritative Excel mapping.

Browser automation applies only the PRISMA `Start of Auction` date range. Mini
does not automate a PRISMA Capacity filter. The booked-capacity threshold is
applied locally during CSV processing only from an explicitly verified
authoritative CSV field and semantics.

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

Roadmap increments M.1 through M.8 are implemented. M.9 has confirmed DOM
evidence for the two `Start of Auction` date controls but remains blocked on
authoritative Apply-action and applied-range evidence. Automatic download and
integrated processing remain M.10 and M.11.

## Development and tests

Use the repository virtual environment on Windows:

```powershell
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pytest
& .\.venv\Scripts\python.exe -m compileall -q .
```

The application entry point is `app.py`. It exposes only the focused Mini UI;
inherited monitoring modules remain isolated until their scheduled removal in
M.13 and are not reachable from this window.
