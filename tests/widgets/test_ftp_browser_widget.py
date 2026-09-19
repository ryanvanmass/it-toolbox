import threading
import time

from it_toolbox.core import ftp_client
from it_toolbox.widgets.ftp_browser_widget import FtpBrowserWidget


class _FakeSession:
    kind = "sftp"

    def __init__(self, entries_by_path, home="/home/alice", fail_connect_with=None):
        self._entries_by_path = entries_by_path
        self._home = home
        self.connected = False
        self.closed = False
        self.uploaded = []
        self.downloaded = []
        self.mkdirs = []
        self.renames = []
        self.removed = []
        self.rmdirs = []
        self.trusted_host_keys = []
        # Raised by connect() until trust_host_key() has been called --
        # simulates paramiko's real "unknown host key" -> retry flow
        # without a real SSH connection.
        self._fail_connect_with = fail_connect_with

    def connect(self):
        if self._fail_connect_with is not None:
            raise self._fail_connect_with
        self.connected = True

    def trust_host_key(self, hostname, key):
        self.trusted_host_keys.append((hostname, key))
        self._fail_connect_with = None

    def home_dir(self):
        return self._home

    def list_dir(self, path):
        return self._entries_by_path[path]

    def join(self, base, name):
        return f"{base.rstrip('/')}/{name}"

    def parent(self, path):
        return path.rsplit("/", 1)[0] or "/"

    def upload(self, local_path, remote_path, progress=None):
        self.uploaded.append((local_path, remote_path))
        if progress:
            progress(1, 1)

    def download(self, remote_path, local_path, progress=None):
        self.downloaded.append((remote_path, local_path))
        with open(local_path, "wb") as f:
            f.write(b"data")
        if progress:
            progress(1, 1)

    def mkdir(self, path):
        self.mkdirs.append(path)

    def rmdir(self, path):
        self.rmdirs.append(path)

    def remove(self, path):
        self.removed.append(path)

    def rename(self, old, new):
        self.renames.append((old, new))

    def close(self):
        self.closed = True


def _make_browser(qtbot, entries_by_path, home="/home/alice"):
    session = _FakeSession(entries_by_path, home=home)
    browser = FtpBrowserWidget(session, "my-box")
    qtbot.addWidget(browser)
    return browser, session


class _ConcurrencySensingSession(_FakeSession):
    """Detects if any two of its methods ever run concurrently on
    different threads -- proves the recursive-download queue never lets
    the remote-tree scan run in parallel with another job touching the
    same session (a real SFTP/FTP connection isn't safe for that)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._busy = False
        self._guard_lock = threading.Lock()
        self.concurrent_access_detected = False

    def _guarded(self, fn, *args, **kwargs):
        with self._guard_lock:
            if self._busy:
                self.concurrent_access_detected = True
            self._busy = True
        try:
            time.sleep(0.02)  # widen the window so a real race would be caught
            return fn(*args, **kwargs)
        finally:
            with self._guard_lock:
                self._busy = False

    def list_dir(self, path):
        return self._guarded(super().list_dir, path)

    def download(self, remote_path, local_path, progress=None):
        return self._guarded(super().download, remote_path, local_path, progress=progress)

    def upload(self, local_path, remote_path, progress=None):
        return self._guarded(super().upload, local_path, remote_path, progress=progress)

    def mkdir(self, path):
        return self._guarded(super().mkdir, path)


def test_browser_connects_and_loads_home_directory(qtbot):
    entries = {
        "/home/alice": [
            ftp_client.FileEntry(name="docs", is_dir=True),
            ftp_client.FileEntry(name="readme.txt", is_dir=False, size=10),
        ]
    }
    browser, session = _make_browser(qtbot, entries)

    qtbot.waitUntil(lambda: session.connected, timeout=2000)
    qtbot.waitUntil(lambda: browser._remote_pane._table.rowCount() == 2, timeout=2000)

    assert browser._remote_path == "/home/alice"


def test_unknown_host_key_prompts_and_retries_on_accept(qtbot, monkeypatch):
    import paramiko

    import it_toolbox.widgets.ftp_browser_widget as module

    key = paramiko.RSAKey.generate(1024)
    error = ftp_client.UnknownHostKeyError("10.0.0.5", key)
    session = _FakeSession({"/home/alice": []}, fail_connect_with=error)
    monkeypatch.setattr(module.QMessageBox, "question", staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.Yes))

    browser = FtpBrowserWidget(session, "my-box")
    qtbot.addWidget(browser)

    qtbot.waitUntil(lambda: session.trusted_host_keys == [("10.0.0.5", key)], timeout=2000)
    qtbot.waitUntil(lambda: session.connected, timeout=2000)


def test_unknown_host_key_declined_leaves_session_disconnected(qtbot, monkeypatch):
    import paramiko

    import it_toolbox.widgets.ftp_browser_widget as module

    key = paramiko.RSAKey.generate(1024)
    error = ftp_client.UnknownHostKeyError("10.0.0.5", key)
    session = _FakeSession({"/home/alice": []}, fail_connect_with=error)
    monkeypatch.setattr(module.QMessageBox, "question", staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.No))

    browser = FtpBrowserWidget(session, "my-box")
    qtbot.addWidget(browser)

    qtbot.waitUntil(lambda: "cancelled" in browser._status_label.text(), timeout=2000)
    assert session.trusted_host_keys == []
    assert session.connected is False


def test_double_clicking_a_remote_folder_navigates_into_it(qtbot):
    entries = {
        "/home/alice": [ftp_client.FileEntry(name="docs", is_dir=True)],
        "/home/alice/docs": [ftp_client.FileEntry(name="a.txt", is_dir=False, size=1)],
    }
    browser, session = _make_browser(qtbot, entries)
    qtbot.waitUntil(lambda: browser._remote_pane._table.rowCount() == 1, timeout=2000)

    browser._on_remote_item_activated(0)

    assert browser._remote_path == "/home/alice/docs"

    def _shows_a_txt() -> bool:
        item = browser._remote_pane._table.item(0, 0)
        return item is not None and item.text() == "a.txt"

    qtbot.waitUntil(_shows_a_txt, timeout=2000)


def test_double_clicking_a_remote_file_downloads_it_to_the_local_pane(qtbot, tmp_path):
    entries = {
        "/home/alice": [ftp_client.FileEntry(name="a.txt", is_dir=False, size=4)],
    }
    browser, session = _make_browser(qtbot, entries)
    browser._local_path = str(tmp_path)
    qtbot.waitUntil(lambda: browser._remote_pane._table.rowCount() == 1, timeout=2000)

    browser._on_remote_item_activated(0)

    qtbot.waitUntil(lambda: len(session.downloaded) == 1, timeout=2000)
    assert session.downloaded[0] == ("/home/alice/a.txt", str(tmp_path / "a.txt"))
    assert (tmp_path / "a.txt").read_bytes() == b"data"


def test_double_clicking_a_local_file_uploads_it_to_the_remote_pane(qtbot, tmp_path):
    entries = {"/home/alice": []}
    browser, session = _make_browser(qtbot, entries)
    qtbot.waitUntil(lambda: browser._remote_path == "/home/alice", timeout=2000)
    local_file = tmp_path / "b.txt"
    local_file.write_text("hi")
    browser._local_path = str(tmp_path)
    browser._reload_local()

    row = next(
        r
        for r in range(browser._local_pane._table.rowCount())
        if browser._local_pane._table.item(r, 0).text() == "b.txt"
    )
    browser._on_local_item_activated(row)

    qtbot.waitUntil(lambda: len(session.uploaded) == 1, timeout=2000)
    assert session.uploaded[0] == (str(local_file), "/home/alice/b.txt")


def test_new_remote_folder_calls_mkdir_and_reloads(qtbot, monkeypatch):
    import it_toolbox.widgets.ftp_browser_widget as module

    entries = {"/home/alice": []}
    browser, session = _make_browser(qtbot, entries)
    qtbot.waitUntil(lambda: browser._remote_path == "/home/alice", timeout=2000)
    monkeypatch.setattr(module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("newdir", True)))

    browser._new_remote_folder()

    qtbot.waitUntil(lambda: session.mkdirs == ["/home/alice/newdir"], timeout=2000)


def test_delete_remote_recursive_removes_children_then_directory(qtbot):
    entries = {
        "/home/alice": [ftp_client.FileEntry(name="docs", is_dir=True)],
        "/home/alice/docs": [ftp_client.FileEntry(name="a.txt", is_dir=False, size=1)],
    }
    browser, session = _make_browser(qtbot, entries)

    browser._delete_remote_recursive("/home/alice/docs", is_dir=True)

    assert session.removed == ["/home/alice/docs/a.txt"]
    assert session.rmdirs == ["/home/alice/docs"]


def test_uploading_a_folder_recursively_creates_remote_dirs_and_uploads_files(qtbot, tmp_path):
    (tmp_path / "folder" / "sub").mkdir(parents=True)
    (tmp_path / "folder" / "a.txt").write_text("a")
    (tmp_path / "folder" / "sub" / "b.txt").write_text("b")

    browser, session = _make_browser(qtbot, {"/home/alice": []})
    qtbot.waitUntil(lambda: browser._remote_path == "/home/alice", timeout=2000)

    browser._upload_paths([str(tmp_path / "folder")])

    qtbot.waitUntil(
        lambda: not browser._pending_transfers and not browser._transfer_in_progress, timeout=3000
    )

    # The subdirectory's create-folder job must land in the queue before
    # its own contents get uploaded into it.
    assert session.mkdirs == ["/home/alice/folder", "/home/alice/folder/sub"]
    assert (str(tmp_path / "folder" / "a.txt"), "/home/alice/folder/a.txt") in session.uploaded
    assert (
        str(tmp_path / "folder" / "sub" / "b.txt"),
        "/home/alice/folder/sub/b.txt",
    ) in session.uploaded


def test_downloading_a_folder_recursively_creates_local_dirs_and_downloads_files(qtbot, tmp_path):
    entries = {
        "/home/alice": [ftp_client.FileEntry(name="folder", is_dir=True)],
        "/home/alice/folder": [
            ftp_client.FileEntry(name="sub", is_dir=True),
            ftp_client.FileEntry(name="a.txt", is_dir=False, size=1),
        ],
        "/home/alice/folder/sub": [ftp_client.FileEntry(name="b.txt", is_dir=False, size=1)],
    }
    browser, session = _make_browser(qtbot, entries)
    qtbot.waitUntil(lambda: browser._remote_pane._table.rowCount() == 1, timeout=2000)
    browser._local_path = str(tmp_path)

    folder_entry = browser._remote_pane.entry_at(0)
    browser._download_entries([folder_entry])

    qtbot.waitUntil(
        lambda: not browser._pending_transfers and not browser._transfer_in_progress, timeout=3000
    )

    assert (tmp_path / "folder").is_dir()
    assert (tmp_path / "folder" / "sub").is_dir()
    assert (tmp_path / "folder" / "a.txt").read_bytes() == b"data"
    assert (tmp_path / "folder" / "sub" / "b.txt").read_bytes() == b"data"


def test_downloading_a_folder_and_a_file_together_never_touches_the_session_concurrently(qtbot):
    entries = {
        "/home/alice": [
            ftp_client.FileEntry(name="folder", is_dir=True),
            ftp_client.FileEntry(name="other.txt", is_dir=False, size=1),
        ],
        "/home/alice/folder": [ftp_client.FileEntry(name="a.txt", is_dir=False, size=1)],
    }
    session = _ConcurrencySensingSession(entries)
    browser = FtpBrowserWidget(session, "my-box")
    qtbot.addWidget(browser)
    qtbot.waitUntil(lambda: browser._remote_pane._table.rowCount() == 2, timeout=2000)

    row_entries = [browser._remote_pane.entry_at(r) for r in range(2)]
    folder_entry = next(e for e in row_entries if e.is_dir)
    file_entry = next(e for e in row_entries if not e.is_dir)

    browser._download_entries([folder_entry, file_entry])

    qtbot.waitUntil(
        lambda: not browser._pending_transfers and not browser._transfer_in_progress, timeout=3000
    )
    assert session.concurrent_access_detected is False


def test_uploading_a_folder_with_multiple_files_never_touches_the_session_concurrently(qtbot, tmp_path):
    # Regression test: a completed job used to trigger _reload_remote()
    # (a fresh session.list_dir call) and dispatch the *next* queued
    # job's own session call back to back, with nothing ordering them --
    # for a single manually-triggered transfer nothing was ever still
    # queued by the time it finished, so this was invisible, but a
    # multi-file recursive upload enqueues jobs up front and hits it for
    # real (confirmed live against a real sshd before this fix).
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "a.txt").write_text("a")
    (tmp_path / "folder" / "b.txt").write_text("b")

    session = _ConcurrencySensingSession({"/home/alice": []})
    browser = FtpBrowserWidget(session, "my-box")
    qtbot.addWidget(browser)
    qtbot.waitUntil(lambda: browser._remote_path == "/home/alice", timeout=2000)

    browser._upload_paths([str(tmp_path / "folder")])

    qtbot.waitUntil(
        lambda: not browser._pending_transfers and not browser._transfer_in_progress, timeout=3000
    )
    assert session.concurrent_access_detected is False
    assert len(session.uploaded) == 2


def test_expand_button_hides_panes_and_grows_the_queue(qtbot):
    entries = {"/home/alice": []}
    browser, session = _make_browser(qtbot, entries)

    assert browser._panes_container.isHidden() is False
    assert browser._queue_expand_button.text() == "Expand"

    browser._on_toggle_queue_expanded()

    assert browser._panes_container.isHidden() is True
    assert browser._queue_table.maximumHeight() > 1000
    assert browser._queue_expand_button.text() == "Collapse"

    browser._on_toggle_queue_expanded()

    assert browser._panes_container.isHidden() is False
    assert browser._queue_table.maximumHeight() == 160
    assert browser._queue_expand_button.text() == "Expand"


def test_close_session_closes_the_underlying_connection(qtbot):
    entries = {"/home/alice": []}
    browser, session = _make_browser(qtbot, entries)

    browser.close_session()

    qtbot.waitUntil(lambda: session.closed, timeout=2000)


def test_ftp_kind_hides_permissions_column(qtbot):
    class _FakeFtpSession(_FakeSession):
        kind = "ftp"

    session = _FakeFtpSession({"/home/alice": []})
    browser = FtpBrowserWidget(session, "my-box")
    qtbot.addWidget(browser)

    assert browser._remote_pane._table.columnCount() == 3
