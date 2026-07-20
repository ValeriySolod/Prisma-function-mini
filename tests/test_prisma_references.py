from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from csv_contracts import PRISMA_EXPORT_COLUMNS
from prisma_references import (
    DEFAULT_PRISMA_REFERENCES,
    PrismaReference,
    PrismaReferenceCatalog,
    ReferenceAlias,
    ReferenceClassification,
    ReferenceSide,
)
from processor import (
    MIN_MARKETED_CAPACITY_KWH_H,
    PrismaEnrichmentReasonCode,
    PrismaImportStatus,
    import_prisma_export,
)


BASE = {
    "Auction ID": "000123456789012345",
    "Start of Auction": "01.01.2025 09:00",
    "Marketed Capacity": "1000",
    "Unit Marketed Capacity": "kWh/h",
    "Product Runtime Start": "02.01.2025 00:00",
    "Product Runtime End": "03.01.2025 00:00",
    "Direction": "Entry",
    "Network Point Name Entry": "VGS Storage Hub (4290)",
    "Network Point ID Entry": "ENTRY-ID",
}


BATCH_1_MARKET_ALIASES = (
    ("Arnoldstein importazione (35718301)", ReferenceSide.ENTRY, "PSV"),
    ("VIP DK-THE (H646) (H646)", ReferenceSide.EXIT, "THE"),
)


EXISTING_MARKET_ALIASES = {
    ("Kulata (BG)/Sidirokastron (GR)", ReferenceSide.EXIT, "BG"),
    ("Kireevo (BG) / Zaychar (RS)", ReferenceSide.EXIT, "BG"),
    ("Kulata (BG)/Sidirokastron (GR)", ReferenceSide.ENTRY, "HTP"),
    ("Kireevo (BG) / Zaychar (RS)", ReferenceSide.ENTRY, "RS"),
    ("Mosonmagyarovar (AT) / Mosonmagyaróvár (HU)", ReferenceSide.EXIT, "CEGH"),
    ("Arnoldstein Exit", ReferenceSide.EXIT, "CEGH"),
    ("Baumgarten WAG AT->SK", ReferenceSide.EXIT, "CEGH"),
    ("Mosonmagyarovar (AT) / Mosonmagyaróvár (HU)", ReferenceSide.ENTRY, "MGP"),
    ("Arnoldstein Exit", ReferenceSide.ENTRY, "PSV"),
    ("Baumgarten WAG AT->SK", ReferenceSide.ENTRY, "SK"),
}


P35_1_EVIDENCE_DIR = Path(__file__).parents[1] / "evidence" / "p35-1"
P35_1_EVIDENCE_DIGESTS = {
    "Auction_Overview.pdf": (
        "4bd3558cc2dc69dd09ab5f179cc9887664fc61e43ed09a0359612cc86f25ae80"
    ),
    "Auction_overview.csv": (
        "c02a696672774a89d376a73478d68d2c9e8ce90b7f27a275fa960653c1da6cd6"
    ),
}


P35_1_ACCEPTED_EVIDENCE_ROWS = {
    "62333921": {
        "Direction": "Entry",
        "Network Point Name Entry": "Arnoldstein importazione (35718301)",
        "Network Point ID Entry": "35718301",
        "Network Point Type Entry": "BORDER_TRANSITION_POINT",
        "Marketed Capacity": "3803500",
        "Unit Marketed Capacity": "kWh/h",
    },
    "62235775": {
        "Direction": "Exit",
        "Network Point Name Exit": "VIP DK-THE (H646) (H646)",
        "Network Point ID Exit": "H646",
        "Network Point Type Exit": "BORDER_TRANSITION_POINT",
        "Marketed Capacity": "5137",
        "Unit Marketed Capacity": "kWh/h",
    },
}


def write_csv(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "references.csv"
    pd.DataFrame(rows).reindex(columns=PRISMA_EXPORT_COLUMNS).fillna("").to_csv(
        path, sep=";", encoding="cp1252", index=False
    )
    return path


def test_known_entry_storage_enrichment_and_source_metadata(tmp_path: Path) -> None:
    result = import_prisma_export(write_csv(tmp_path, [BASE]))
    assert result.rows[0]["entry_market"] == "VGS Storage Hub"
    assert result.rows[0]["exit_market"] == ""
    assert result.rows[0]["direction"] == "entry"
    record = result.enriched_records[0]
    assert record.source_row_number == 2
    assert record.raw_row["Network Point Name Entry"] == "VGS Storage Hub (4290)"
    assert record.entry_reference is not None
    assert (
        record.entry_reference.canonical_name,
        record.entry_reference.classification,
        record.entry_reference.side,
    ) == (
        "VGS Storage Hub",
        ReferenceClassification.STORAGE,
        ReferenceSide.ENTRY,
    )
    assert record.exit_reference is None


def test_all_authoritative_reservoir_aliases_are_side_specific_storage() -> None:
    overview = pd.read_csv(
        Path(__file__).parents[1] / "Auction_overview.csv",
        sep=";",
        encoding="cp1252",
        dtype=str,
    ).fillna("")
    for side in ReferenceSide:
        source_side = side.value.title()
        name_column = f"Network Point Name {source_side}"
        type_column = f"Network Point Type {source_side}"
        reservoir_names = set(
            overview.loc[overview[type_column] == "RESERVOIR", name_column]
        ) - {""}
        assert len(reservoir_names) == (
            50 if side is ReferenceSide.EXIT else 51
        )
        for source_value in reservoir_names:
            reference = DEFAULT_PRISMA_REFERENCES.lookup(source_value, side)
            assert reference is not None, (side, source_value)
            assert reference.classification is ReferenceClassification.STORAGE


def test_storage_catalog_contains_only_authoritative_side_aliases() -> None:
    overview = pd.read_csv(
        Path(__file__).parents[1] / "Auction_overview.csv",
        sep=";",
        encoding="cp1252",
        dtype=str,
    ).fillna("")
    for side in ReferenceSide:
        source_side = side.value.title()
        name_column = f"Network Point Name {source_side}"
        type_column = f"Network Point Type {source_side}"
        expected = set(
            overview.loc[overview[type_column] == "RESERVOIR", name_column]
        ) - {""}
        actual = {
            alias.source_value
            for reference in DEFAULT_PRISMA_REFERENCES.entries
            if reference.classification is ReferenceClassification.STORAGE
            for alias in reference.aliases
            if alias.side is side
        }
        assert actual == expected


def test_storage_alias_is_not_assumed_for_unevidenced_side() -> None:
    assert DEFAULT_PRISMA_REFERENCES.lookup(
        "TEP Storage Hub (6257)", ReferenceSide.ENTRY
    ) is None


@pytest.mark.parametrize(
    ("filename", "expected_digest"), P35_1_EVIDENCE_DIGESTS.items()
)
def test_p35_1_authoritative_evidence_digest_is_unchanged(
    filename: str, expected_digest: str
) -> None:
    evidence_path = P35_1_EVIDENCE_DIR / filename
    assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == expected_digest


def test_p35_1_accepted_csv_evidence_rows_are_exact_and_capacity_eligible() -> None:
    overview = pd.read_csv(
        P35_1_EVIDENCE_DIR / "Auction_overview.csv",
        sep=";",
        encoding="cp1252",
        dtype=str,
    ).fillna("")

    for auction_id, expected_fields in P35_1_ACCEPTED_EVIDENCE_ROWS.items():
        matches = overview.loc[overview["Auction ID"] == auction_id]
        assert len(matches) == 1
        row = matches.iloc[0]
        assert {field: row[field] for field in expected_fields} == expected_fields

        assert row["Unit Marketed Capacity"] == "kWh/h"
        normalized_capacity_kwh_h = float(row["Marketed Capacity"])
        assert normalized_capacity_kwh_h >= MIN_MARKETED_CAPACITY_KWH_H


@pytest.mark.parametrize(
    ("source_value", "side", "canonical_name"), BATCH_1_MARKET_ALIASES
)
def test_p35_1_market_aliases_resolve_exactly_on_evidenced_side(
    source_value: str, side: ReferenceSide, canonical_name: str
) -> None:
    reference = DEFAULT_PRISMA_REFERENCES.lookup(source_value, side)
    assert reference is not None
    assert (reference.canonical_name, reference.classification) == (
        canonical_name,
        ReferenceClassification.MARKET,
    )


@pytest.mark.parametrize(
    ("source_value", "evidenced_side", "canonical_name"),
    BATCH_1_MARKET_ALIASES,
)
def test_p35_1_one_sided_market_aliases_do_not_cross_resolve(
    source_value: str, evidenced_side: ReferenceSide, canonical_name: str
) -> None:
    opposite_side = (
        ReferenceSide.EXIT
        if evidenced_side is ReferenceSide.ENTRY
        else ReferenceSide.ENTRY
    )
    assert DEFAULT_PRISMA_REFERENCES.lookup(source_value, evidenced_side) is not None
    assert DEFAULT_PRISMA_REFERENCES.lookup(source_value, opposite_side) is None


@pytest.mark.parametrize(
    "source_value",
    (
        "Arnoldstein importazione",
        "Arnoldstein importazione (35718301) extra",
        "rnoldstein importazione (35718301)",
        "VIP DK-THE",
        "VIP DK-THE (H646)",
        "35718301",
        "H646",
    ),
)
def test_p35_1_fuzzy_substring_and_identifier_matching_remain_unavailable(
    source_value: str,
) -> None:
    assert all(
        DEFAULT_PRISMA_REFERENCES.lookup(source_value, side) is None
        for side in ReferenceSide
    )


def test_p35_1_preserves_all_existing_market_mappings() -> None:
    actual = {
        (alias.source_value, alias.side, reference.canonical_name)
        for reference in DEFAULT_PRISMA_REFERENCES.entries
        if reference.classification is ReferenceClassification.MARKET
        for alias in reference.aliases
    }
    assert actual == EXISTING_MARKET_ALIASES | set(BATCH_1_MARKET_ALIASES)


@pytest.mark.parametrize(
    ("source_value", "side"),
    [
        ("Epe - IV (UGS-A) (01110021)", ReferenceSide.EXIT),
        ("Epe - III (UGS-E) (01210003)", ReferenceSide.ENTRY),
        ("UGS Jemgum GTG (37Z000000008869Q)", ReferenceSide.EXIT),
        ("UGS Jemgum GTG (37Z000000008869Q)", ReferenceSide.ENTRY),
    ],
)
def test_new_authoritative_storage_aliases_resolve_on_evidenced_side(
    source_value: str, side: ReferenceSide
) -> None:
    reference = DEFAULT_PRISMA_REFERENCES.lookup(source_value, side)
    assert reference is not None
    assert reference.classification is ReferenceClassification.STORAGE


@pytest.mark.parametrize(
    ("source_value", "evidenced_side", "unevidenced_side"),
    [
        ("Epe - IV (UGS-A) (01110021)", ReferenceSide.EXIT, ReferenceSide.ENTRY),
        ("Epe - III (UGS-E) (01210003)", ReferenceSide.ENTRY, ReferenceSide.EXIT),
    ],
)
def test_new_one_sided_storage_aliases_do_not_cross_resolve(
    source_value: str,
    evidenced_side: ReferenceSide,
    unevidenced_side: ReferenceSide,
) -> None:
    assert DEFAULT_PRISMA_REFERENCES.lookup(source_value, evidenced_side) is not None
    assert DEFAULT_PRISMA_REFERENCES.lookup(source_value, unevidenced_side) is None


def test_known_exit_market_exact_alias(tmp_path: Path) -> None:
    row = {
        **BASE,
        "Direction": "Exit",
        "Network Point Name Entry": "",
        "Network Point Name Exit": "Arnoldstein Exit",
        "Network Point ID Exit": "EXIT-ID",
    }
    enriched = import_prisma_export(write_csv(tmp_path, [row])).rows[0]
    assert (enriched["exit_market"], enriched["direction"]) == ("CEGH", "exit")
    reference = import_prisma_export(write_csv(tmp_path, [row])).enriched_records[0].exit_reference
    assert reference is not None
    assert (reference.canonical_name, reference.classification) == (
        "CEGH", ReferenceClassification.MARKET
    )


def test_known_entry_market_and_harmless_normalization(tmp_path: Path) -> None:
    row = {**BASE, "Network Point Name Entry": "  arnoldstein EXIT  "}
    enriched = import_prisma_export(write_csv(tmp_path, [row])).rows[0]
    assert enriched["entry_market"] == "PSV"


def test_bundle_enrichment_derives_capacity_type_from_both_sides(tmp_path: Path) -> None:
    row = {
        **BASE,
        "Direction": "Exit/Entry",
        "Network Point Name Exit": "Arnoldstein Exit",
        "Network Point ID Exit": "EXIT-ID",
        "Network Point Name Entry": "Arnoldstein Exit",
        "Network Point Name Exit/Entry": "Arnoldstein bundle",
        "Network Point ID Exit/Entry": "BUNDLE-ID",
    }
    enriched = import_prisma_export(write_csv(tmp_path, [row])).rows[0]
    assert (enriched["exit_market"], enriched["entry_market"], enriched["direction"]) == (
        "CEGH", "PSV", "bundle"
    )
    record = import_prisma_export(write_csv(tmp_path, [row])).enriched_records[0]
    assert record.exit_reference is not None and record.entry_reference is not None
    assert (
        record.exit_reference.canonical_name,
        record.exit_reference.classification,
        record.entry_reference.canonical_name,
        record.entry_reference.classification,
    ) == (
        "CEGH", ReferenceClassification.MARKET,
        "PSV", ReferenceClassification.MARKET,
    )


@pytest.mark.parametrize(
    ("field", "side", "code"),
    [
        ("Network Point Name Exit", "exit", "unknown_exit_reference"),
        ("Network Point Name Entry", "entry", "unknown_entry_reference"),
    ],
)
def test_unknown_reference_is_auditable(
    tmp_path: Path, field: str, side: str, code: str
) -> None:
    row = {**BASE, "Network Point Name Entry": ""}
    row[field] = "Unknown Source Value"
    row["Direction"] = "Exit" if side == "exit" else "Entry"
    if side == "exit":
        row["Network Point ID Exit"] = "EXIT-ID"
    result = import_prisma_export(write_csv(tmp_path, [row]))
    issue = result.issues[0]
    assert result.rows == []
    assert (issue.source_row_number, issue.status, issue.reason_code) == (
        2, PrismaImportStatus.REJECTED, code
    )
    assert (issue.field_name, issue.side, issue.source_value) == (
        field, side, "Unknown Source Value"
    )


def test_bundle_missing_required_sides_cannot_be_enriched(tmp_path: Path) -> None:
    row = {
        **BASE,
        "Direction": "Exit/Entry",
        "Network Point Name Entry": "",
        "Network Point Name Exit": "",
        "Network Point Name Exit/Entry": "Combined point",
        "Network Point ID Exit/Entry": "BUNDLE-ID",
    }
    result = import_prisma_export(write_csv(tmp_path, [row]))
    assert result.rows == []
    issue = result.issues[0]
    assert issue.reason_code is PrismaEnrichmentReasonCode.MISSING_REQUIRED_EXIT_REFERENCE
    assert (issue.field_name, issue.side, issue.source_value) == (
        "Network Point Name Exit", "exit", ""
    )


@pytest.mark.parametrize(("direction", "required_field", "irrelevant_field", "expected"), [
    ("Entry", "Network Point Name Entry", "Network Point Name Exit", "entry"),
    ("Exit", "Network Point Name Exit", "Network Point Name Entry", "exit"),
])
def test_irrelevant_populated_side_is_ignored_without_changing_direction(
    tmp_path: Path, direction: str, required_field: str, irrelevant_field: str, expected: str
) -> None:
    row = {
        **BASE,
        "Direction": direction,
        required_field: "VGS Storage Hub (4290)",
        irrelevant_field: "Contradictory unknown side",
    }
    if direction == "Exit":
        row["Network Point ID Exit"] = "EXIT-ID"
    result = import_prisma_export(write_csv(tmp_path, [row]))
    assert result.rejected_count == 0
    enriched = result.rows[0]
    assert enriched["direction"] == expected
    assert enriched["network_point"] == "VGS Storage Hub (4290)"
    assert result.enriched_records[0].raw_row[irrelevant_field] == "Contradictory unknown side"


@pytest.mark.parametrize(("direction", "field", "code"), [
    ("Entry", "Network Point Name Entry", PrismaEnrichmentReasonCode.MISSING_REQUIRED_ENTRY_REFERENCE),
    ("Exit", "Network Point Name Exit", PrismaEnrichmentReasonCode.MISSING_REQUIRED_EXIT_REFERENCE),
])
def test_missing_direction_required_side_is_typed_and_auditable(
    tmp_path: Path, direction: str, field: str, code: PrismaEnrichmentReasonCode
) -> None:
    row = {**BASE, "Direction": direction, field: ""}
    result = import_prisma_export(write_csv(tmp_path, [row]))
    issue = result.issues[0]
    assert result.rows == []
    assert issue.reason_code is code
    assert (issue.field_name, issue.side, issue.source_value) == (
        field, "entry" if direction == "Entry" else "exit", ""
    )


def test_duplicate_and_conflicting_aliases_are_rejected() -> None:
    aliases = (ReferenceAlias("Same", ReferenceSide.EXIT),)
    with pytest.raises(ValueError, match="Conflicting or duplicate"):
        PrismaReferenceCatalog((
            PrismaReference("One", ReferenceClassification.MARKET, aliases),
            PrismaReference("Two", ReferenceClassification.STORAGE, aliases),
        ))


def test_duplicate_aliases_within_one_entry_are_rejected() -> None:
    aliases = (
        ReferenceAlias("Same", ReferenceSide.EXIT),
        ReferenceAlias(" same ", ReferenceSide.EXIT),
    )
    with pytest.raises(ValueError, match="Conflicting or duplicate"):
        PrismaReferenceCatalog((
            PrismaReference("One", ReferenceClassification.MARKET, aliases),
        ))


def test_duplicate_canonical_name_cannot_hide_behind_whitespace() -> None:
    with pytest.raises(ValueError, match="surrounding whitespace"):
        PrismaReferenceCatalog((
            PrismaReference("One", ReferenceClassification.MARKET, ()),
            PrismaReference(" One ", ReferenceClassification.STORAGE, ()),
        ))


@pytest.mark.parametrize("value", ["Arnoldstein", "Arnoldstein Exit extra", "noldstein Exit"])
def test_no_fuzzy_or_substring_matching(value: str) -> None:
    assert DEFAULT_PRISMA_REFERENCES.lookup(value, ReferenceSide.EXIT) is None


def test_original_source_value_and_physical_line_are_preserved_in_issue(tmp_path: Path) -> None:
    original = "  Not A Known Hub  "
    result = import_prisma_export(
        write_csv(tmp_path, [{**BASE, "Network Point Name Entry": original}])
    )
    issue = result.issues[0]
    assert issue.source_row_number == 2
    assert issue.source_value == original


def test_rows_and_issues_remain_in_source_order_deterministically(tmp_path: Path) -> None:
    rows = [
        BASE,
        {**BASE, "Auction ID": "2", "Network Point Name Entry": "Unknown B"},
        {**BASE, "Auction ID": "3", "Network Point Name Entry": "Unknown A"},
    ]
    first = import_prisma_export(write_csv(tmp_path, rows))
    second = import_prisma_export(write_csv(tmp_path, rows))
    assert first == second
    assert [issue.source_row_number for issue in first.issues] == [3, 4]
