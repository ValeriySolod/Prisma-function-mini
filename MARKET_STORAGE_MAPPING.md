# Authoritative Market and Storage Mapping

## Rules

This file is the authoritative mapping boundary for Prisma Function Mini.
Mappings are exact and side-specific. Mini must not infer a value from
geography, TSO, EIC, identifiers, substrings, similar names, or the opposite
side. An empty cell is deliberately unresolved and must remain blank in output.

## Approved mappings

| Exact PRISMA network-point alias | Exit Market / Storage | Entry Market / Storage |
|---|---|---|
| `Kulata (BG)/Sidirokastron (GR)` | `BG` | `HTP` |
| `Kireevo (BG) / Zaychar (RS)` | `BG` | `RS` |
| `Mosonmagyarovar (AT) / Mosonmagyaróvár (HU)` | `CEGH` | `MGP` |
| `Arnoldstein Exit` | `CEGH` | `PSV` |
| `Baumgarten WAG AT->SK` | `CEGH` | `SK` |
| `Arnoldstein importazione (35718301)` |  | `PSV` |
| `VIP DK-THE (H646) (H646)` | `THE` |  |

No additional Market or Storage mappings are approved. In particular, a source
classification, display name, identifier, legacy catalog entry, or mapping on
the opposite side does not fill an unresolved cell; cross-side reuse is
prohibited. New mappings require
explicit authoritative evidence and approval.
