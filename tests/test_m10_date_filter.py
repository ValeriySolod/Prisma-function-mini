import threading
from datetime import date

import pytest

from mini_browser import (
    MiniBrowserAuthenticationRequiredError,
    MiniBrowserCancelledError,
    MiniDateFilterApplyTimeoutError,
    MiniDateFilterRefreshError,
    MiniDateFilterSelectorError,
    MiniDateFilterTimestampError,
    MiniDateFilterValueError,
    MiniPrismaDateFilter,
)
from mini_domain import MiniDateRange
from prisma_page import PrismaAuthenticationRequiredError


class TimeoutError(Exception):
    pass


class FakeLocator:
    def __init__(
        self,
        *,
        visible=True,
        iso="2026-07-01T04:00:00.000Z",
        normalize=None,
        click_error=None,
        after_fill=None,
        after_click=None,
    ):
        self.visible = visible
        self.iso = iso
        self.normalize = normalize
        self.click_error = click_error
        self.after_fill = after_fill
        self.after_click = after_click
        self.value = ""
        self.fills = []
        self.clicks = 0

    def wait_for(self, **_kwargs):
        if not self.visible:
            raise TimeoutError("missing")

    def fill(self, value, **_kwargs):
        self.fills.append(value)
        self.value = self.normalize if self.normalize is not None else value
        if self.after_fill:
            self.after_fill()

    def input_value(self, **_kwargs):
        return self.value

    def get_attribute(self, name, **_kwargs):
        assert name == "data-test-iso-value"
        return self.iso

    def click(self, **_kwargs):
        self.clicks += 1
        if self.after_click:
            self.after_click()
        if self.click_error:
            raise self.click_error


class FakePage:
    def __init__(self, locators, *, refresh_error=None, refresh_callback=None):
        self.locators = locators
        self.refresh_error = refresh_error
        self.refresh_callback = refresh_callback
        self.selector_calls = []
        self.refresh_calls = 0

    def locator(self, selector):
        self.selector_calls.append(selector)
        return self.locators.get(selector, FakeLocator(visible=False))

    def wait_for_load_state(self, state, **_kwargs):
        assert state == "networkidle"
        self.refresh_calls += 1
        if self.refresh_callback:
            self.refresh_callback()
        if self.refresh_error:
            raise self.refresh_error


def make_page(**overrides):
    selectors = MiniPrismaDateFilter
    locators = {
        selectors.START_SELECTOR: FakeLocator(),
        selectors.END_SELECTOR: FakeLocator(iso="2026-07-21T04:00:00.000Z"),
        selectors.APPLY_SELECTOR: FakeLocator(),
        selectors.CONFIRMATION_SELECTOR: FakeLocator(),
    }
    locators.update(overrides)
    return FakePage(locators)


def adapter(**kwargs):
    return MiniPrismaDateFilter(timeout_ms=2, refresh_timeout_ms=2, poll_ms=1, **kwargs)


def requested_range():
    return MiniDateRange(date(2026, 7, 1), date(2026, 7, 21))


def test_enters_exact_boundaries_applies_and_confirms_without_to_tag():
    page = make_page()

    result = adapter().apply(page, requested_range(), threading.Event())

    assert result.start_value == "01.07.2026      06:00"
    assert result.end_value == "21.07.2026      06:00"
    assert page.locators[MiniPrismaDateFilter.START_SELECTOR].fills == [result.start_value]
    assert page.locators[MiniPrismaDateFilter.END_SELECTOR].fills == [result.end_value]
    assert page.locators[MiniPrismaDateFilter.APPLY_SELECTOR].clicks == 1
    assert page.refresh_calls == 1
    assert page.selector_calls == [
        '[data-testid="startOfAuctionFrom"]',
        '[data-testid="startOfAuctionTo"]',
        '[data-testid="submit-filters"]',
        '[data-testid="filter-startOfAuctionFrom"]',
    ]
    assert "filter-startOfAuctionTo" not in " ".join(page.selector_calls)


@pytest.mark.parametrize("bad_iso", [None, "", "not-an-iso", "2026-07-01T04:00:00"])
def test_rejects_missing_invalid_or_timezone_free_interpreted_iso(bad_iso):
    page = make_page(**{
        MiniPrismaDateFilter.START_SELECTOR: FakeLocator(iso=bad_iso),
    })
    with pytest.raises(MiniDateFilterTimestampError):
        adapter().apply(page, requested_range(), threading.Event())
    assert page.locators[MiniPrismaDateFilter.APPLY_SELECTOR].clicks == 0


def test_domain_rejects_inverted_range_before_browser_interaction():
    with pytest.raises(ValueError):
        MiniDateRange(date(2026, 7, 2), date(2026, 7, 1))


def test_adapter_rejects_parallel_date_contract_before_browser_interaction():
    page = make_page()
    with pytest.raises(TypeError):
        adapter().apply(page, (date(2026, 7, 1), date(2026, 7, 2)), threading.Event())
    assert page.selector_calls == []


@pytest.mark.parametrize(
    "selector",
    [
        MiniPrismaDateFilter.START_SELECTOR,
        MiniPrismaDateFilter.END_SELECTOR,
        MiniPrismaDateFilter.APPLY_SELECTOR,
    ],
)
def test_missing_required_entry_or_apply_selector_is_typed(selector):
    page = make_page(**{selector: FakeLocator(visible=False)})
    with pytest.raises(MiniDateFilterSelectorError):
        adapter().apply(page, requested_range(), threading.Event())


def test_missing_confirmation_is_apply_timeout_and_does_not_resubmit():
    page = make_page(**{
        MiniPrismaDateFilter.CONFIRMATION_SELECTOR: FakeLocator(visible=False),
    })
    subject = adapter()
    with pytest.raises(MiniDateFilterApplyTimeoutError):
        subject.apply(page, requested_range(), threading.Event())
    with pytest.raises(MiniDateFilterRefreshError, match="duplicate"):
        subject.apply(page, requested_range(), threading.Event())
    assert page.locators[MiniPrismaDateFilter.APPLY_SELECTOR].clicks == 1


def test_concurrent_execution_allows_only_one_filter_submission():
    click_started = threading.Event()
    release_click = threading.Event()

    def block_click():
        click_started.set()
        assert release_click.wait(1)

    page = make_page(**{
        MiniPrismaDateFilter.APPLY_SELECTOR: FakeLocator(after_click=block_click),
    })
    subject = adapter()
    outcomes = []

    def run():
        try:
            outcomes.append(subject.apply(page, requested_range(), threading.Event()))
        except Exception as exc:
            outcomes.append(exc)

    first = threading.Thread(target=run)
    second = threading.Thread(target=run)
    first.start()
    assert click_started.wait(1)
    second.start()
    release_click.set()
    first.join(1)
    second.join(1)

    assert not first.is_alive() and not second.is_alive()
    assert page.locators[MiniPrismaDateFilter.APPLY_SELECTOR].clicks == 1
    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, MiniDateFilterRefreshError) for item in outcomes) == 1


@pytest.mark.parametrize("selector", [
    MiniPrismaDateFilter.START_SELECTOR,
    MiniPrismaDateFilter.END_SELECTOR,
])
def test_rejected_or_normalized_away_value_is_typed_before_apply(selector):
    page = make_page(**{selector: FakeLocator(normalize="01.07.2026 06:00")})
    with pytest.raises(MiniDateFilterValueError):
        adapter().apply(page, requested_range(), threading.Event())
    assert page.locators[MiniPrismaDateFilter.APPLY_SELECTOR].clicks == 0


def test_apply_timeout_is_typed_and_uncertain_submission_is_not_repeated():
    page = make_page(**{
        MiniPrismaDateFilter.APPLY_SELECTOR: FakeLocator(click_error=TimeoutError("slow")),
    })
    subject = adapter()
    with pytest.raises(MiniDateFilterApplyTimeoutError):
        subject.apply(page, requested_range(), threading.Event())
    with pytest.raises(MiniDateFilterRefreshError, match="duplicate"):
        subject.apply(page, requested_range(), threading.Event())
    assert page.locators[MiniPrismaDateFilter.APPLY_SELECTOR].clicks == 1


def test_refresh_timeout_and_failure_are_typed_after_single_submission():
    timeout_page = make_page()
    timeout_page.refresh_error = TimeoutError("still loading")
    with pytest.raises(MiniDateFilterRefreshError, match="in time"):
        adapter().apply(timeout_page, requested_range(), threading.Event())
    assert timeout_page.locators[MiniPrismaDateFilter.APPLY_SELECTOR].clicks == 1

    failure_page = make_page()
    failure_page.refresh_error = RuntimeError("request failed")
    with pytest.raises(MiniDateFilterRefreshError, match="failed"):
        adapter().apply(failure_page, requested_range(), threading.Event())


def test_authentication_loss_during_wait_is_typed():
    def lost(_page):
        raise PrismaAuthenticationRequiredError("login")

    page = make_page(**{
        MiniPrismaDateFilter.START_SELECTOR: FakeLocator(visible=False),
    })
    with pytest.raises(MiniBrowserAuthenticationRequiredError):
        adapter(authentication_probe=lost).apply(page, requested_range(), threading.Event())


@pytest.mark.parametrize("stage", ["before", "between", "before-apply", "refresh"])
def test_cancellation_is_responsive_at_each_filter_stage(stage):
    cancel = threading.Event()
    if stage == "before":
        cancel.set()
    start = FakeLocator(after_fill=cancel.set if stage == "between" else None)
    end = FakeLocator(
        iso="2026-07-21T04:00:00.000Z",
        after_fill=cancel.set if stage == "before-apply" else None,
    )
    page = make_page(**{
        MiniPrismaDateFilter.START_SELECTOR: start,
        MiniPrismaDateFilter.END_SELECTOR: end,
    })
    if stage == "refresh":
        page.refresh_error = TimeoutError("busy")
        page.refresh_callback = cancel.set

    with pytest.raises(MiniBrowserCancelledError):
        adapter().apply(page, requested_range(), cancel)

    if stage in {"before", "between", "before-apply"}:
        assert page.locators[MiniPrismaDateFilter.APPLY_SELECTOR].clicks == 0
