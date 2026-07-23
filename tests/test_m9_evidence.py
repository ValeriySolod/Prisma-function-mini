from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "m9"


class InputCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[dict[str, str | None]] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "input":
            self.inputs.append(dict(attrs))


def _inputs(filename: str) -> dict[str, dict[str, str | None]]:
    parser = InputCollector()
    parser.feed((EVIDENCE / filename).read_text(encoding="utf-8"))
    controls = {
        attributes["data-testid"]: attributes
        for attributes in parser.inputs
        if attributes.get("data-testid")
    }
    assert len(controls) == len(parser.inputs) == 2
    return controls


def test_m9_evidence_preserves_only_confirmed_date_controls() -> None:
    expected = {
        "startOfAuctionFrom": {
            "name": "startOfAuctionFrom",
            "value": "01.07.2026      06:00",
            "data-test-iso-value": "2026-07-01T04:00:00.000Z",
        },
        "startOfAuctionTo": {
            "name": "startOfAuctionTo",
            "value": "21.07.2026      06:00",
            "data-test-iso-value": "2026-07-21T04:00:00.000Z",
        },
    }

    for filename in ("prisma_filters_before.html", "prisma_filters_after.html"):
        controls = _inputs(filename)
        assert controls.keys() == expected.keys()
        for test_id, attributes in expected.items():
            assert {
                key: controls[test_id][key] for key in attributes
            } == attributes
            assert controls[test_id]["placeholder"] == "DD.MM.YYYY      HH:mm"
            assert controls[test_id]["data-test-error"] == "false"


def test_m9_documents_prohibit_prisma_capacity_automation() -> None:
    evidence_readme = (EVIDENCE / "README.md").read_text(encoding="utf-8")
    specification = (ROOT / "TECHNICAL_SPECIFICATION.md").read_text(encoding="utf-8")
    workflow = (ROOT / "workflow_m.md").read_text(encoding="utf-8")

    assert "does not set a" in evidence_readme
    assert "PRISMA Capacity filter" in evidence_readme
    assert "must not configure or depend on a PRISMA Capacity filter" in specification
    assert "must not automate a PRISMA Capacity filter" in workflow
    assert "explicitly verified authoritative CSV field and semantics" in evidence_readme
