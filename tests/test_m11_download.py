import hashlib
import threading
from datetime import date
from pathlib import Path

import pytest

import mini_download
from csv_contracts import PRISMA_EXPORT_COLUMNS
from mini_domain import MiniDateRange
from mini_download import (
    OFFICIAL_FILENAME,
    MiniDownloadCancelledError,
    MiniDownloadChangedDomError,
    MiniDownloadCleanupError,
    MiniDownloadContractError,
    MiniDownloadDuplicateSubmissionError,
    MiniDownloadEmptyError,
    MiniDownloadFilesystemError,
    MiniDownloadLimitedError,
    MiniDownloadMissingError,
    MiniDownloadPageClosedError,
    MiniDownloadPartialError,
    MiniDownloadTimeoutError,
    MiniDownloadUnexpectedFilenameError,
    MiniPrismaCsvDownloader,
)


class TimeoutError(Exception):
    pass


def official_csv() -> bytes:
    return (";".join(PRISMA_EXPORT_COLUMNS) + "\r\n").encode("cp1252")


class StepClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        self.value += 0.001
        return self.value


class FakeDownload:
    def __init__(
        self,
        content=None,
        *,
        filename=OFFICIAL_FILENAME,
        failure=None,
        save_error=None,
        after_save=None,
        extra_artifact=False,
    ):
        self.suggested_filename = filename
        self.content = official_csv() if content is None else content
        self.reported_failure = failure
        self.save_error = save_error
        self.after_save = after_save
        self.extra_artifact = extra_artifact
        self.cancelled = 0

    def failure(self):
        return self.reported_failure

    def save_as(self, path):
        if self.save_error:
            raise self.save_error
        destination = Path(path)
        destination.write_bytes(self.content)
        if self.extra_artifact:
            (destination.parent / "unexpected.crdownload").write_bytes(b"partial")
        if self.after_save:
            self.after_save()

    def cancel(self):
        self.cancelled += 1


class FakeLocator:
    def __init__(self, *, visible=True, text="", after_click=None):
        self.visible = visible
        self.text = text
        self.after_click = after_click
        self.clicks = 0

    def wait_for(self, **_kwargs):
        if not self.visible:
            raise TimeoutError("missing")

    def is_visible(self, **_kwargs):
        return self.visible

    def inner_text(self, **_kwargs):
        return self.text

    def click(self, **_kwargs):
        self.clicks += 1
        if self.after_click:
            self.after_click()


class FakePage:
    DIALOG_SELECTOR = '[role="dialog"][data-dialog][data-open="true"]'
    MAIN_ACTION_SELECTOR = (
        'button:has(svg[data-icon="file-csv"])'
        ':not([role="dialog"][data-dialog][data-open="true"] *)'
    )
    CONFIRM_ACTION_SELECTOR = (
        '[role="dialog"][data-dialog][data-open="true"] '
        'button[data-sentry-component="MonolithDownload"]'
        ':has(svg[data-icon="file-csv"])'
    )

    def __init__(
        self, download=None, *, warning=None, confirmation=True,
        emit_on="main", closed=False, event_error=None,
    ):
        self.download = download
        self.warning = warning
        self.emit_on = emit_on
        self.closed = closed
        self.event_error = event_error
        self.listeners = []
        self.removed = []
        self.main = FakeLocator(after_click=lambda: self._emit("main"))
        self.dialog = FakeLocator(visible=warning is not None, text=warning or "")
        self.confirm = FakeLocator(
            visible=confirmation, after_click=lambda: self._emit("confirm")
        )

    def on(self, event, callback):
        assert event == "download"
        self.listeners.append(callback)

    def remove_listener(self, event, callback):
        assert event == "download"
        self.listeners.remove(callback)
        self.removed.append(callback)

    def locator(self, selector):
        if selector == self.MAIN_ACTION_SELECTOR:
            return self.main
        if selector == self.DIALOG_SELECTOR:
            return self.dialog
        if selector == self.CONFIRM_ACTION_SELECTOR:
            return self.confirm
        raise AssertionError(selector)

    def wait_for_event(self, event, **_kwargs):
        assert event == "download"
        if self.event_error:
            raise self.event_error
        observed = self._emit("wait")
        if observed is not None:
            return observed
        raise TimeoutError("no download")

    def is_closed(self):
        return self.closed

    def _emit(self, stage):
        if self.download is not None and self.emit_on == stage:
            download, self.download = self.download, None
            for callback in tuple(self.listeners):
                callback(download)
            return download
        return None


def requested_range():
    return MiniDateRange(date(2026, 7, 1), date(2026, 7, 21))


def subject(tmp_path, **kwargs):
    return MiniPrismaCsvDownloader(
        tmp_path / "temporary-downloads", timeout_ms=4, poll_ms=1,
        clock=StepClock(), operation_id_factory=lambda: "operation-1", **kwargs,
    )


def test_normal_download_accepts_only_official_contract_and_binds_immutable_metadata(tmp_path):
    page = FakePage(FakeDownload())
    result = subject(tmp_path).download(page, requested_range(), threading.Event())

    assert result.path.read_bytes() == official_csv()
    assert result.path.parent.parent == (tmp_path / "temporary-downloads").resolve()
    assert result.requested_range == requested_range()
    assert result.request.source_name == OFFICIAL_FILENAME
    assert result.request.size_bytes == len(official_csv())
    assert result.request.sha256 == hashlib.sha256(official_csv()).hexdigest()
    assert page.main.clicks == 1
    assert page.removed


def test_warning_dialog_equal_counts_confirms_and_accepts_download(tmp_path):
    page = FakePage(
        FakeDownload(),
        warning="Warning\nDismiss popup\nYour download contains only 12 of 12 items.\nCSV",
        emit_on="confirm",
    )
    result = subject(tmp_path).download(page, requested_range(), threading.Event())

    assert (result.downloaded_count, result.total_count) == (12, 12)
    assert page.confirm.clicks == 1
    assert MiniPrismaCsvDownloader.CONFIRM_ACTION_SELECTOR == (
        '[role="dialog"][data-dialog][data-open="true"] '
        'button[data-sentry-component="MonolithDownload"]'
        ':has(svg[data-icon="file-csv"])'
    )


def test_limited_warning_download_fails_closed_and_removes_rejected_file(tmp_path):
    page = FakePage(
        FakeDownload(),
        warning=(
            "Warning\nDismiss popup\n"
            "Your download contains only 5000 of 5966 items.\nCSV"
        ),
        emit_on="confirm",
    )
    with pytest.raises(MiniDownloadLimitedError) as caught:
        subject(tmp_path).download(page, requested_range(), threading.Event())
    assert (caught.value.downloaded_count, caught.value.total_count) == (5000, 5966)
    assert not list((tmp_path / "temporary-downloads").iterdir())


@pytest.mark.parametrize(
    ("warning", "confirmation"),
    [
        ("Download is limited.", True),
        ("Your download contains only x of 12 items.", True),
        ("Your download contains only 13 of 12 items.", True),
        (
            "Warning\nYour download contains only 12 of 12 items.\n"
            "Your download contains only 12 of 12 items.\nCSV",
            True,
        ),
        (
            "Warning\nYour download contains only x of 12 items.\n"
            "Your download contains only 12 of 12 items.\nCSV",
            True,
        ),
        ("Your download contains only 12 of 12 items.", False),
    ],
)
def test_malformed_warning_or_missing_confirmed_action_is_changed_dom(
    tmp_path, warning, confirmation
):
    page = FakePage(
        FakeDownload(), warning=warning, confirmation=confirmation,
        emit_on="confirm",
    )
    with pytest.raises(MiniDownloadChangedDomError):
        subject(tmp_path).download(page, requested_range(), threading.Event())


@pytest.mark.parametrize(
    ("download", "error"),
    [
        (FakeDownload(filename="other.csv"), MiniDownloadUnexpectedFilenameError),
        (FakeDownload(content=b""), MiniDownloadEmptyError),
        (FakeDownload(failure="cancelled"), MiniDownloadPartialError),
        (FakeDownload(content=b"wrong,contract\r\n"), MiniDownloadContractError),
        (FakeDownload(extra_artifact=True), MiniDownloadPartialError),
        (FakeDownload(save_error=OSError("denied")), MiniDownloadFilesystemError),
    ],
)
def test_rejects_unexpected_empty_partial_wrong_contract_and_filesystem_failures(
    tmp_path, download, error
):
    with pytest.raises(error):
        subject(tmp_path).download(
            FakePage(download), requested_range(), threading.Event()
        )
    assert not list((tmp_path / "temporary-downloads").iterdir())


def test_missing_download_times_out_and_does_not_submit_twice(tmp_path):
    downloader = subject(tmp_path)
    page = FakePage(None)
    with pytest.raises(MiniDownloadTimeoutError):
        downloader.download(page, requested_range(), threading.Event())
    with pytest.raises(MiniDownloadDuplicateSubmissionError):
        downloader.download(FakePage(FakeDownload()), requested_range(), threading.Event())
    assert page.main.clicks == 1


def test_broken_download_event_boundary_is_typed_as_missing(tmp_path):
    page = FakePage(None, event_error=RuntimeError("event stream unavailable"))
    with pytest.raises(MiniDownloadMissingError):
        subject(tmp_path).download(page, requested_range(), threading.Event())


def test_cancellation_before_and_during_save_cleans_only_owned_operation(tmp_path):
    root = tmp_path / "temporary-downloads"
    root.mkdir()
    unrelated = root / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(MiniDownloadCancelledError):
        subject(tmp_path).download(FakePage(FakeDownload()), requested_range(), cancelled)
    assert unrelated.read_text(encoding="utf-8") == "keep"

    cancelled.clear()
    download = FakeDownload(after_save=cancelled.set)
    with pytest.raises(MiniDownloadCancelledError):
        subject(tmp_path).download(FakePage(download), requested_range(), cancelled)
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in root.iterdir()) == ["keep.txt"]
    assert download.cancelled == 1


def test_closed_page_is_typed_and_listener_is_removed(tmp_path):
    page = FakePage(None, closed=True)
    page.dialog.is_visible = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("target closed")
    )
    with pytest.raises(MiniDownloadPageClosedError):
        subject(tmp_path).download(page, requested_range(), threading.Event())
    assert page.removed


def test_destination_collision_fails_without_touching_existing_directory(tmp_path):
    operation = tmp_path / "temporary-downloads" / "operation-1"
    operation.mkdir(parents=True)
    sentinel = operation / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(MiniDownloadFilesystemError):
        subject(tmp_path).download(
            FakePage(FakeDownload()), requested_range(), threading.Event()
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_cleanup_failure_is_typed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mini_download.shutil, "rmtree",
        lambda _path: (_ for _ in ()).throw(OSError("locked")),
    )
    with pytest.raises(MiniDownloadCleanupError):
        subject(tmp_path).download(
            FakePage(FakeDownload(content=b"")), requested_range(), threading.Event()
        )
