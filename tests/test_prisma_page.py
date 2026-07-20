from unittest.mock import Mock

import pytest

from auction_csv import AuctionCsvRecord
from prisma_page import (
    LivePrismaStatusAdapter, PrismaAuctionAmbiguousError,
    PrismaAuctionMatchError, PrismaAuctionNotFoundError, PrismaAuctionRow,
    PrismaAuthenticationRequiredError, PrismaInvalidSessionError,
    PrismaPageReader, PrismaPageStructureError, PrismaPageUnavailableError,
    PrismaSessionValidator,
    PrismaStatusParseError, match_auction_row, normalize_page_text,
    normalize_prisma_status, parse_auction_rows,
)


class SessionLocator:
    def __init__(self, visible=False):
        self.first = self
        self.visible = visible

    def count(self):
        return int(self.visible)

    def is_visible(self):
        return self.visible


class SessionPage:
    def __init__(self, url, *, public=False, auth=False, ready_after=0, consent=False):
        self.url = url
        self.public = public
        self.auth = auth
        self.ready_after = ready_after
        self.polls = 0
        self.consent = consent

    def locator(self, selector):
        assert selector == "input[type='password']"
        return SessionLocator(self.auth)

    def get_by_role(self, role, name=None):
        pattern = getattr(name, "pattern", "")
        if role == "heading" and "authentication" in pattern:
            return SessionLocator(self.auth)
        if role == "button" and "in$" in pattern:
            return SessionLocator(self.auth)
        if role in ("heading", "button", "table"):
            return SessionLocator(self.public and self.polls >= self.ready_after)
        raise AssertionError(role)

    def wait_for_timeout(self, milliseconds):
        self.polls += 1


PUBLIC_URL = (
    "https://app.prisma-capacity.eu/reporting/auctions/"
    "short-and-long-term-auctions"
)


def validator():
    item = PrismaSessionValidator()
    item.TIMEOUT_MS = 20
    item.POLL_MS = 1
    return item


def test_public_auctions_page_and_harmless_consent_are_accepted():
    state = validator().validate(SessionPage(PUBLIC_URL, public=True, consent=True))
    assert state.classification == "public-auctions"


def test_delayed_public_readiness_is_not_authentication_failure():
    state = validator().validate(SessionPage(PUBLIC_URL, public=True, ready_after=2))
    assert state.classification == "public-auctions"


def test_login_redirect_is_typed_authentication_required():
    with pytest.raises(PrismaAuthenticationRequiredError):
        validator().validate(SessionPage("https://app.prisma-capacity.eu/login?token=secret"))


def test_login_dom_is_detected_when_url_looks_public():
    with pytest.raises(PrismaAuthenticationRequiredError):
        validator().validate(SessionPage(PUBLIC_URL, auth=True))


def test_unexpected_page_is_typed_invalid_session():
    with pytest.raises(PrismaInvalidSessionError):
        validator().validate(SessionPage("https://example.com/error?password=secret"))


@pytest.mark.parametrize("raw_url", [
    None,
    123,
    "",
    "   ",
    "https://[invalid-host/path?token=representative",
])
def test_malformed_or_non_string_page_url_is_typed_invalid_session(raw_url):
    with pytest.raises(
        PrismaInvalidSessionError,
        match="session location is invalid or unavailable",
    ) as error:
        validator().validate(SessionPage(raw_url))

    assert "representative" not in str(error.value)


def test_safe_location_removes_queries_fragments_and_user_information():
    location = PrismaSessionValidator.safe_location(
        "https://user:password@app.prisma-capacity.eu/login?token=secret#cookie=value"
    )
    assert location == "https://app.prisma-capacity.eu/login"
    assert all(value not in location for value in ("user", "password", "token", "secret", "cookie"))


def record(auction_id: str = "62247546") -> AuctionCsvRecord:
    return AuctionCsvRecord(
        auction_id, "https://example.com", "1", "Auction", "Completed",
        "Open", 30, True,
    )


@pytest.mark.parametrize(("raw", "expected"), [
    (" Open ", "Open"),
    ("IN\nPROGRESS", "In Progress"),
    ("Finished", "Completed"),
    ("completed", "Completed"),
    ("Canceled", "Cancelled"),
])
def test_raw_status_normalization(raw, expected):
    assert normalize_prisma_status(raw) == expected


def test_page_text_normalization_collapses_browser_whitespace():
    assert normalize_page_text("  Auction\n\t  ID ") == "Auction ID"


@pytest.mark.parametrize("raw", ["", "   ", "Closing soon", "Finished successfully"])
def test_malformed_or_unsupported_status_is_rejected(raw):
    with pytest.raises(PrismaStatusParseError):
        normalize_prisma_status(raw)


def test_rows_are_parsed_by_header_name_not_column_position():
    rows = parse_auction_rows(
        ["State", "Marketed Capacity", "Auction ID"],
        [["Finished", "1000", " 62247546 "]],
    )
    assert rows == [PrismaAuctionRow("62247546", "Finished")]


@pytest.mark.parametrize("headers", [
    ["Auction ID", "Marketed Capacity"],
    ["State", "Marketed Capacity"],
])
def test_missing_required_column_is_rejected(headers):
    with pytest.raises(PrismaPageStructureError, match="required column"):
        parse_auction_rows(headers, [])


def test_short_row_is_rejected():
    with pytest.raises(PrismaPageStructureError, match="required cells"):
        parse_auction_rows(["Auction ID", "State"], [["62247546"]])


def test_matching_uses_normalized_auction_id_deterministically():
    matched = match_auction_row(
        record(" AbC-1 "),
        [PrismaAuctionRow("abc-1", "Open"), PrismaAuctionRow("other", "Open")],
    )
    assert matched.auction_id == "abc-1"


def test_missing_match_is_explicit():
    with pytest.raises(PrismaAuctionNotFoundError, match="No live auction row"):
        match_auction_row(record("missing"), [PrismaAuctionRow("other", "Open")])


def test_ambiguous_match_is_explicit():
    with pytest.raises(PrismaAuctionAmbiguousError, match="Multiple live auction rows"):
        match_auction_row(
            record("A1"),
            [PrismaAuctionRow("A1", "Open"), PrismaAuctionRow(" a1 ", "Finished")],
        )


class RoleCollection:
    def __init__(self, items):
        self._items = items

    def count(self):
        return len(self._items)

    def nth(self, index):
        return self._items[index]

    def all(self):
        return self._items


class TextCollection:
    def __init__(self, texts):
        self._texts = texts

    def all_inner_texts(self):
        return self._texts


class Row:
    def __init__(self, cells):
        self.cells = cells

    def get_by_role(self, role):
        assert role == "cell"
        return TextCollection(self.cells)


class Table:
    def __init__(self, headers, rows):
        self.headers = headers
        self.rows = rows

    def wait_for(self, *, state, timeout):
        assert state == "visible" and timeout > 0

    def get_by_role(self, role):
        if role == "columnheader":
            return TextCollection(self.headers)
        if role == "row":
            return RoleCollection([Row(cells) for cells in self.rows])
        raise AssertionError(role)


class DomTextRow:
    def __init__(self, selector, texts):
        self.selector = selector
        self.texts = texts

    def locator(self, selector):
        assert selector in ("th", "td")
        return TextCollection(self.texts)


class DomLocator:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class LiveDomTable(Table):
    def locator(self, selector):
        if selector == "thead tr":
            return DomLocator([
                DomTextRow("th", ["", ""]),
                DomTextRow("th", self.headers),
            ])
        if selector == "tbody tr":
            return DomLocator([DomTextRow("td", cells) for cells in self.rows])
        raise AssertionError(selector)


class Page:
    def __init__(self, tables):
        self.tables = tables

    def get_by_role(self, role):
        assert role == "table"
        return RoleCollection(self.tables)


def test_mocked_page_successfully_extracts_and_normalizes_live_status():
    page = Page([Table(
        ["Auction ID", "Network Point", "State"],
        [[], ["62247546", "Zone UGS", "Finished"]],
    )])
    assert PrismaPageReader().read_status(page, record()) == "Completed"


def test_live_dom_uses_rendered_header_row_instead_of_empty_sorting_headers():
    page = Page([LiveDomTable(
        ["Start of Auction", "Auction ID", "Status"],
        [["20.07.2026, 09:00", "61550499", "Cancelled"]],
    )])

    assert PrismaPageReader().read_status(page, record("61550499")) == "Cancelled"


def test_page_without_table_fails_clearly():
    with pytest.raises(PrismaPageStructureError, match="No live auction table"):
        PrismaPageReader().read_status(Page([]), record())


def test_page_with_missing_required_header_is_structure_failure():
    page = Page([Table(["Auction ID", "Capacity"], [["62247546", "1000"]])])
    with pytest.raises(PrismaPageStructureError, match="required Auction ID and State"):
        PrismaPageReader().read_status(page, record())


def test_unreadable_status_cell_is_distinct_from_missing_auction():
    page = Page([Table(["Auction ID", "State"], [["62247546", ""]])])
    with pytest.raises(PrismaStatusParseError, match="empty status"):
        PrismaPageReader().read_status(page, record())


def test_page_with_unavailable_matching_row_fails_clearly():
    page = Page([Table(["Auction ID", "State"], [["other", "Open"]])])
    with pytest.raises(PrismaAuctionMatchError, match="No live auction row"):
        PrismaPageReader().read_status(page, record())


def test_page_inspection_failure_is_typed():
    page = Mock()
    page.get_by_role.side_effect = RuntimeError("page closed")
    with pytest.raises(PrismaPageUnavailableError, match="could not be inspected"):
        PrismaPageReader().read_status(page, record())


def test_monitoring_adapter_delegates_to_existing_browser_controller():
    controller = Mock()
    controller.read_live_auction_status.return_value = "Open"
    item = record()
    assert LivePrismaStatusAdapter(controller)(item) == "Open"
    controller.read_live_auction_status.assert_called_once_with(item)
