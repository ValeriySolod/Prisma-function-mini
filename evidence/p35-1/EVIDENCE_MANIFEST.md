# P.35.1 Authoritative Market Mapping Evidence Manifest

## Sources

- `Auction_Overview.pdf`
  - SHA-256: `4bd3558cc2dc69dd09ab5f179cc9887664fc61e43ed09a0359612cc86f25ae80`
- `Auction_overview.csv`
  - SHA-256: `c02a696672774a89d376a73478d68d2c9e8ce90b7f27a275fa960653c1da6cd6`

## Accepted rows

P.35.1 Batch 1 accepts exactly two side-specific mappings:

| Side | Exact network-point alias | Network-point ID | Network-point type | PDF Market Area | Canonical market | Auction ID | PDF page | Marketed Capacity | Unit |
|---|---|---|---|---|---|---|---:|---:|---|
| entry | Arnoldstein importazione (35718301) | 35718301 | BORDER_TRANSITION_POINT | Italy | PSV | 62333921 | 20 | 3803500 | kWh/h |
| exit | VIP DK-THE (H646) (H646) | H646 | BORDER_TRANSITION_POINT | Trading Hub Europe | THE | 62235775 | 26 | 5137 | kWh/h |

## Limitation

Only exact side-specific network-point aliases linked between the two source files by the same Auction ID and having booked capacity of at least 1000 kWh/h after supported unit normalization are accepted. Twelve aliases from the preliminary 14-row candidate set were rejected because their normalized booked capacity was below 1000 kWh/h. Other shared-Auction-ID rows were not reviewed or accepted in Batch 1, even if some may meet the capacity threshold; they remain outside P.35.1 and provide no mappings. Rows without an exact shared Auction ID, bundle rows, `RESERVOIR` aliases, fuzzy matches, substrings, identifiers used as aliases, and inferred relationships are excluded from this batch. This manifest records exactly two accepted side-specific mappings and makes no completeness claim.
