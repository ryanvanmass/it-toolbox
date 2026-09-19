from it_toolbox.core import ftp_client
from it_toolbox.widgets.ftp_browser_widget import FtpBrowserWidget


class _FakeSession:
    kind = "sftp"

    def __init__(self, entries_by_path, home="/home/alice"):
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

    def connect(self):
        self.connected = True

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
    assert "docs" in browser._remote_pane._table.item(0, 0).text()


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
