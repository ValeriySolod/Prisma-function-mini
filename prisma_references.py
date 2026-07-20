from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping


class ReferenceClassification(str, Enum):
    MARKET = "market"
    STORAGE = "storage"


class ReferenceSide(str, Enum):
    EXIT = "exit"
    ENTRY = "entry"


@dataclass(frozen=True)
class ReferenceAlias:
    source_value: str
    side: ReferenceSide


@dataclass(frozen=True)
class PrismaReference:
    canonical_name: str
    classification: ReferenceClassification
    aliases: tuple[ReferenceAlias, ...]


def normalize_reference_alias(value: str) -> str:
    """Normalize only surrounding whitespace and case for explicit aliases."""
    return value.strip().casefold()


class PrismaReferenceCatalog:
    """Immutable, side-aware index of explicitly declared PRISMA aliases."""

    def __init__(self, entries: Iterable[PrismaReference]) -> None:
        immutable_entries = tuple(entries)
        index: dict[tuple[ReferenceSide, str], PrismaReference] = {}
        canonical_names: set[str] = set()
        for entry in immutable_entries:
            if not entry.canonical_name.strip():
                raise ValueError("Reference canonical names must not be blank.")
            if entry.canonical_name != entry.canonical_name.strip():
                raise ValueError(
                    "Reference canonical names must not have surrounding whitespace."
                )
            canonical_key = entry.canonical_name.strip().casefold()
            if canonical_key in canonical_names:
                raise ValueError(
                    f"Duplicate reference canonical name: {entry.canonical_name}."
                )
            canonical_names.add(canonical_key)
            for alias in entry.aliases:
                normalized = normalize_reference_alias(alias.source_value)
                if not normalized:
                    raise ValueError("Reference aliases must not be blank.")
                key = (alias.side, normalized)
                if key in index:
                    raise ValueError(
                        "Conflicting or duplicate reference alias for "
                        f"{alias.side.value}: {alias.source_value}."
                    )
                index[key] = entry
        self._entries = immutable_entries
        self._index: Mapping[tuple[ReferenceSide, str], PrismaReference] = (
            MappingProxyType(index)
        )

    @property
    def entries(self) -> tuple[PrismaReference, ...]:
        return self._entries

    def lookup(self, source_value: str, side: ReferenceSide) -> PrismaReference | None:
        return self._index.get((side, normalize_reference_alias(source_value)))


def _market(
    canonical_name: str, *, exit_aliases: tuple[str, ...] = (), entry_aliases: tuple[str, ...] = ()
) -> PrismaReference:
    aliases = tuple(ReferenceAlias(value, ReferenceSide.EXIT) for value in exit_aliases)
    aliases += tuple(ReferenceAlias(value, ReferenceSide.ENTRY) for value in entry_aliases)
    return PrismaReference(canonical_name, ReferenceClassification.MARKET, aliases)


def _storage(
    canonical_name: str,
    *,
    exit_aliases: tuple[str, ...] = (),
    entry_aliases: tuple[str, ...] = (),
) -> PrismaReference:
    side_aliases = tuple(
        ReferenceAlias(value, ReferenceSide.EXIT) for value in exit_aliases
    )
    side_aliases += tuple(
        ReferenceAlias(value, ReferenceSide.ENTRY) for value in entry_aliases
    )
    return PrismaReference(
        canonical_name, ReferenceClassification.STORAGE, side_aliases
    )


def _storage_catalog_entries() -> tuple[PrismaReference, ...]:
    """Build exact side aliases evidenced as RESERVOIR in Auction_overview.csv."""
    exit_aliases = (
        "Bobbau (6CZA)",
        "Epe - IV (UGS-A) (01110021)",
        "Leer - Mooräcker - 2 (700096 Nüttermoor H UGS-A) (01100108)",
        "Leer - Mooräcker - 4 (700096 Jemgum I UGS-A) (01100109)",
        "Speicher Frankenthal (RC Speicher Frankenthal)",
        "UGS ETZEL (H171) (H171)",
        "UGS ETZEL CRYSTAL (H231) (H231)",
        "UGS ETZEL EGL (H286) (H286)",
        "UGS ETZEL ESE (H197) (H197)",
        "UGS HARSEFELD (H103) (H103)",
        "UGS Jemgum GTG (37Z000000008869Q)",
        "UGS Kraak (2564)",
        "Zone UGS EWE L-Gas (21W0000000000176)",
        "Empelde (37)",
        "Empelde H-Gas (119)",
        "Epe/Xanten II (UGS-A) (31110001)",
        "Etzel (Speicher Crystal), Bitzenlander Weg 10 (8541I)",
        "Etzel (Speicher ESE),Bitzenlander Weg 3 (8543I)",
        "Friedeburg-Etzel, Bitzenlander Weg 2 (8542I)",
        "Friedeburg-Etzel, Schienenstrang, EGL (8536I)",
        "Haiming 2 7F (3432I)",
        "Haiming 2-7F/bn Einpressen (BAY-700069-1800-2)",
        "Haiming 2-RAGES/bn Einpressen (BAY-700069-1800-6)",
        "Inzenham-West USP Einpressen (BAY-700069-3202-2)",
        "Jemgum I (1BMA)",
        "Jemgum III (1BRA)",
        "Nüttermoor (1BQA)",
        "Speicher Bierwang (3381I)",
        "Speicher Breitbrunn (3416I)",
        "Speicher Epe H (8513I)",
        "Speicher Epe L (9199I)",
        "Speicher Gronau-Epe H1 (8520)",
        "Speicher Gronau-Epe H4 (EPEH1)",
        "Speicher Gronau-Epe L2 (EPEL2)",
        "Speicher Haiming 3-Haidach (3433I)",
        "Speicher Reckrod (RC Speicher Reckrod)",
        "Speicherzone Nord (Rehden) (37Z0000000089417)",
        "TEP Storage Hub (6257)",
        "UGS JEMGUM EWE (H200) (H200)",
        "UGS LESUM H (H623) (H623)",
        "UGS NUETTERMOOR (H101) (H101)",
        "UGS NUETTERMOOR H (MOORAECKER) (H651) (H651)",
        "UGS Peckensen (1322)",
        "UGS Staßfurt (61004)",
        "UGS UELSEN (H099) (H099)",
        "USP Haidach/Einpressen (BAY-700069-8021-2)",
        "VGS Storage Hub (4290)",
        "Wolfersberg/USP Einpressen (BAY-700069-0205-2)",
        "Zone MND ESG (MND_Exit)",
        "Zone UGS EWE H-Gas (37Z000000007514V)",
    )
    entry_aliases = (
        "Empelde H-Gas (356)",
        "Epe - III (UGS-E) (01210003)",
        "Epe/Xanten I (UGS-E) (31210001)",
        "Gronau - Epe - 11 (UGS-E) (04200012)",
        "Gronau - Epe - 13 (UGS-E) (04200013)",
        "Leer - Mooräcker - 1 (700096 Nüttermoor H UGS-E) (01200015)",
        "Leer - Mooräcker - 3 (700096 Jemgum I UGS-E) (01200016)",
        "Speicher Frankenthal (RC Speicher Frankenthal)",
        "UGS ETZEL (H152) (H152)",
        "UGS ETZEL CRYSTAL (H230) (H230)",
        "UGS ETZEL EGL (H285) (H285)",
        "UGS ETZEL ESE (H196) (H196)",
        "UGS Jemgum GTG (37Z000000008869Q)",
        "UGS Kraak (2564)",
        "Bobbau (6CZA)",
        "Empelde (304)",
        "Etzel (Speicher Crystal), Bitzenlander Weg 10 (8541P)",
        "Etzel (Speicher ESE),Bitzenlander Weg 3 (8543P)",
        "Friedeburg-Etzel, Bitzenlander Weg 2 (8542P)",
        "Friedeburg-Etzel, Schienenstrang, EGL (8536P)",
        "Haiming 2 7F (3432P)",
        "Haiming 2-7F/bn Entnahme (BAY-700069-1800-1)",
        "Haiming 2-RAGES/bn Entnahme (BAY-700069-1800-5)",
        "Inzenham-West USP Entnahme (BAY-700069-3202-1)",
        "Jemgum I (1BMA)",
        "Jemgum III (1BRA)",
        "Nüttermoor (1BQA)",
        "Speicher Bierwang (3381P)",
        "Speicher Breitbrunn (3416P)",
        "Speicher Epe H (8513P)",
        "Speicher Epe L (9199P)",
        "Speicher Gronau-Epe H1 (8520E)",
        "Speicher Gronau-Epe H4 (EPEH1E)",
        "Speicher Gronau-Epe L2 (EPEL2E)",
        "Speicher Haiming 3-Haidach (3433P)",
        "Speicher Reckrod (Speicher Reckrod)",
        "Speicherzone Nord (Rehden) (37Z0000000089417)",
        "UGS HARSEFELD (H102) (H102)",
        "UGS JEMGUM EWE (H199) (H199)",
        "UGS LESUM H (H622) (H622)",
        "UGS NUETTERMOOR (H100) (H100)",
        "UGS NUETTERMOOR H (MOORAECKER) (H650) (H650)",
        "UGS Peckensen (1322)",
        "UGS Staßfurt (61004)",
        "UGS UELSEN (H098) (H098)",
        "USP Haidach/Entnahme (BAY-700069-8021-1)",
        "VGS Storage Hub (4290)",
        "Wolfersberg/USP Entnahme (BAY-700069-0205-1)",
        "Zone MND ESG (MND_Entry)",
        "Zone UGS EWE H-Gas (37Z000000007514V)",
        "Zone UGS EWE L-Gas (21W0000000000176)",
    )
    source_values = tuple(dict.fromkeys(exit_aliases + entry_aliases))
    return tuple(
        _storage(
            "VGS Storage Hub" if source_value == "VGS Storage Hub (4290)" else source_value,
            exit_aliases=(source_value,) if source_value in exit_aliases else (),
            entry_aliases=(source_value,) if source_value in entry_aliases else (),
        )
        for source_value in source_values
    )


# Market aliases are the exact side-specific network-point mappings checked into
# mapping.csv or accepted through an authoritative evidence manifest.
# Storage aliases are the exact side-specific network-point names explicitly
# classified as RESERVOIR in the checked-in Auction_overview.csv export. Add
# entries only from confirmed source data; the constructor rejects every
# duplicate side/alias pair.
DEFAULT_PRISMA_REFERENCES = PrismaReferenceCatalog(
    (
        _market(
            "BG",
            exit_aliases=("Kulata (BG)/Sidirokastron (GR)", "Kireevo (BG) / Zaychar (RS)"),
        ),
        _market("HTP", entry_aliases=("Kulata (BG)/Sidirokastron (GR)",)),
        _market("RS", entry_aliases=("Kireevo (BG) / Zaychar (RS)",)),
        _market(
            "CEGH",
            exit_aliases=(
                "Mosonmagyarovar (AT) / Mosonmagyaróvár (HU)",
                "Arnoldstein Exit",
                "Baumgarten WAG AT->SK",
            ),
        ),
        _market("MGP", entry_aliases=("Mosonmagyarovar (AT) / Mosonmagyaróvár (HU)",)),
        _market(
            "PSV",
            entry_aliases=(
                "Arnoldstein Exit",
                "Arnoldstein importazione (35718301)",
            ),
        ),
        _market("SK", entry_aliases=("Baumgarten WAG AT->SK",)),
        _market(
            "THE",
            exit_aliases=("VIP DK-THE (H646) (H646)",),
        ),
    )
    + _storage_catalog_entries()
)
