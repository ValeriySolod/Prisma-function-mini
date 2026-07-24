# Authoritative PRISMA Input CSV Contract

## Purpose

This document defines the input boundary for the official PRISMA auction export used by Prisma Function Mini. It is separate from the cumulative 12-column output CSV defined in `TECHNICAL_SPECIFICATION.md`.

The contract is based on the reviewed `Auction_overview.csv` evidence. It must not be inferred from the cumulative output schema, display names, legacy monitoring CSV files, or undocumented PRISMA behavior.

## File-level contract

The supported PRISMA input export has these properties:

- encoding: Windows-1252 (`cp1252`), without a UTF-8 BOM;
- delimiter: semicolon (`;`);
- header count: exactly 35;
- every data row must have exactly 35 fields;
- decimal separator: dot (`.`);
- empty optional fields remain empty and must not be converted to zero;
- malformed encoding, delimiter, headers, row width, decimals, dates, timestamps, or units must produce a typed validation failure.

The UTF-8 requirement applies only to the cumulative output CSV. It does not apply to this PRISMA input export.

## Exact input header order

1. `Auction ID`
2. `Start of Auction`
3. `Network Point Name Exit`
4. `Network Point EIC Exit`
5. `Network Point Type Exit`
6. `Network Point ID Exit`
7. `Network Point Name Entry`
8. `Network Point EIC Entry`
9. `Network Point Type Entry`
10. `Network Point ID Entry`
11. `Network Point Name Exit/Entry`
12. `Network Point EIC Exit/Entry`
13. `Network Point ID Exit/Entry`
14. `Published capacity`
15. `Published capacity unit`
16. `Marketable Capacity`
17. `Unit Marketable Capacity`
18. `Marketed Capacity`
19. `Unit Marketed Capacity`
20. `Regulated Tariff Exit TSO`
21. `Unit Regulated Exit Capacity Tariff`
22. `Regulated Tariff Entry TSO`
23. `Unit Regulated Entry Capacity Tariff`
24. `Surcharge`
25. `Unit Surcharge`
26. `Product Runtime Start`
27. `Product Runtime End`
28. `Capacity Category`
29. `TSO Exit`
30. `TSO EIC Exit`
31. `TSO Entry`
32. `TSO EIC Entry`
33. `Direction`
34. `Type of Gas`
35. `State`

Header spelling, capitalization, spacing, and order are exact. Unknown, missing, duplicate, or reordered headers are unsupported unless a later approved contract revision explicitly adds a compatible variant.

## Stable identity and side selection

`Auction ID` is the exact PRISMA auction identity and must be non-empty.

`Direction` selects the side-specific network-point fields:

| Exact `Direction` | Required Network Point ID | Network-point display source | Normalized capacity direction |
|---|---|---|---|
| `Entry` | `Network Point ID Entry` | `Network Point Name Entry` | `Entry` |
| `Exit` | `Network Point ID Exit` | `Network Point Name Exit` | `Exit` |
| `Exit/Entry` | `Network Point ID Exit/Entry` | `Network Point Name Exit/Entry` | `Bundle` |

The selected Network Point ID must be non-empty. A display name, EIC, TSO, opposite-side identifier, or inferred value must never replace it.

The stable duplicate key remains:

1. exact `Auction ID`;
2. selected side-specific Network Point ID;
3. normalized capacity direction;
4. normalized `Product Runtime Start`;
5. normalized `Product Runtime End`.

## Source-to-domain mapping

| Domain/output value | Authoritative source |
|---|---|
| Auction identity | `Auction ID` |
| Auction Date | date component of `Start of Auction` |
| Direction / Capacity Type | exact `Direction` mapping above |
| Side-specific Network Point ID | exact direction-selected ID column above |
| Network Point | exact direction-selected name column above |
| Flow Start | `Product Runtime Start` |
| Flow End | `Product Runtime End` |
| Capacity category | `Capacity Category` |
| Booked capacity | `Marketed Capacity` with `Unit Marketed Capacity` |
| Exit tariff | `Regulated Tariff Exit TSO` with `Unit Regulated Exit Capacity Tariff` |
| Entry tariff | `Regulated Tariff Entry TSO` with `Unit Regulated Entry Capacity Tariff` |
| Auction Premium | `Surcharge` with `Unit Surcharge` |

`Surcharge` is the sole authoritative source for `Auction Premium (EUR/MWh/h)`. A blank `Surcharge` produces a blank premium. It must not produce zero.

For `Entry`, only the entry regulated tariff is selected. For `Exit`, only the
exit regulated tariff is selected. The opposite-side value is ignored and
tariffs are never added. A missing or invalid required side-specific tariff
rejects the row. `Exit/Entry` has no approved single side-specific tariff and is
rejected rather than guessed, selected, or summed.

### Product Type and duration

Product Type is classified from the exact `Product Runtime Start` and
`Product Runtime End` delivery boundaries in the `Europe/Berlin` PRISMA local
timezone. The gas day starts at 06:00 local time:

- `WD`: a delivery starting after 06:00 within a gas day and ending exactly at
  the next 06:00 gas-day boundary;
- `Day Ahead`: exactly one consecutive 06:00-to-06:00 gas day;
- `Month`: 06:00 on the first calendar day of a month through 06:00 on the
  first day of the next month;
- `Quarter`: 06:00 on January 1, April 1, July 1, or October 1 through 06:00
  on the first day of the next calendar quarter;
- `Year`: 06:00 on October 1 through 06:00 on October 1 of the following year.

Classification uses these exact calendar and gas-day boundaries, not raw
duration alone. Unmatched, nonexistent, or ambiguous local periods are rejected
as `product_type_unresolved`. Duration is elapsed UTC time between the
timezone-aware boundaries, so DST-transition delivery periods may contain 23,
24, or 25 hours.

## Capacity normalization

All accepted capacity is normalized deterministically. The current cumulative output header remains `Booked Capacity (kWh/h)`, so the normalized domain/output capacity is expressed as `kWh/h`:

```text
kWh/h -> kWh/h: value
kWh/d -> kWh/h: value / 24
```

The equivalent analytical basis in `MWh/h` is:

```text
kWh/h -> MWh/h: value / 1000
kWh/d -> MWh/h: value / 24000
```

Only `kWh/h` and `kWh/d` are supported for `Unit Marketed Capacity`. A blank marketed-capacity value or unit is incomplete required source data and must be rejected with a typed reason. Unsupported units must never be assumed.

Any local capacity threshold is evaluated only after normalization. PRISMA Capacity automation remains prohibited.

## Tariff and premium normalization

The approved output basis for both tariff and premium is `EUR/MWh/h`.

The user-approved business rule is that PRISMA auction monetary values are treated as EUR values; no foreign-exchange lookup, rate, or conversion is performed. Source unit labels that use `cent`, `CHF/100`, `halér`, or `pence` describe hundredth monetary units for this Mini contract and therefore use the same factor of `0.01 EUR` per source monetary unit. This interpretation is explicit and must not be extended to other labels without approval.

Let:

- `v` be the source numeric value;
- `H` be the exact positive duration in hours between `Product Runtime Start` and `Product Runtime End`.

The approved conversions to `EUR/MWh/h` are:

| Source unit shape | Conversion |
|---|---|
| hundredth-currency `/kWh/h/Runtime` | `v * 10 / H` |
| hundredth-currency `/kWh/d/Runtime` | `v * 240 / H` |
| hundredth-currency `/kWh/h/d` | `v * 10 / 24` |
| hundredth-currency `/kWh/d/d` | `v * 10` |

The reviewed source-unit labels covered by these shapes are:

- `cent/kWh/h/Runtime`;
- `cent/kWh/d/Runtime`;
- `cent/kWh/h/d`;
- `cent/kWh/d/d`;
- `CHF/100/kWh/h/Runtime`;
- `halér/kWh/h/Runtime`;
- `pence/kWh/h/Runtime`;
- `pence/kWh/d/Runtime`;
- `pence/kWh/h/d`;
- `pence/kWh/d/d`.

A non-empty tariff or surcharge with a blank or unsupported unit must be rejected. A blank selected tariff remains blank only if the canonical Mini domain/output contract permits an optional tariff; otherwise it is rejected as incomplete required data. A blank surcharge remains a blank premium.

Zero or negative runtime duration is invalid. Decimal arithmetic must be locale-independent and must not use binary floating-point for persisted normalized values.

## Market and Storage enrichment

Market and Storage values come only from the exact side-specific rules in `MARKET_STORAGE_MAPPING.md`. Unresolved values remain blank. Geography, TSO, EIC, identifiers, substrings, similar names, opposite-side values, legacy catalogs, and automatic matching are prohibited.

## Output boundary

The cumulative output remains a separate 12-column CSV:

- encoding: UTF-8;
- delimiter: semicolon (`;`);
- decimal separator: dot (`.`);
- includes `Auction Premium (EUR/MWh/h)`;
- preserves deterministic ordering and atomic replacement;
- retains the exact stable identity internally in SQLite even though Auction ID and Network Point ID are not output columns.

M.4-M.6 remain historical completed 11-column Excel increments. M.9 owns adaptation to this input contract and the 12-column cumulative output. M.10 owns date filtering, M.11 owns automatic download, and M.12 owns the integrated transformation workflow.

## Known evidence boundaries

The reviewed export proves the 35-column file structure and the presence of the identity, direction, capacity, tariff, surcharge, and runtime fields. It does not by itself prove browser DOM behavior, selected-date application, download initiation, or that every future PRISMA export uses the same schema. Those concerns remain in their roadmap increments and must fail closed when evidence or contracts differ.
