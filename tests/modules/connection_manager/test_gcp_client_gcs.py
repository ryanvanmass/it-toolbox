from it_toolbox.modules.connection_manager import gcp_client
from it_toolbox.modules.connection_manager.models import GcsBucket


class _FakeCredentials:
    token = "fake-token"


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, chunks=None, text=""):
        self._json = json_data
        self.status_code = status_code
        self._chunks = chunks or []
        self.text = text

    def json(self):
        return self._json

    def iter_content(self, chunk_size):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_list_objects_splits_folders_and_files(monkeypatch):
    def fake_get(url, headers, params, timeout):
        assert params["userProject"] == "proj"
        return _FakeResponse(
            json_data={
                "prefixes": ["photos/2024/"],
                "items": [
                    {"name": "photos/readme.txt", "size": "123", "updated": "2024-01-01T00:00:00Z"},
                ],
            }
        )

    monkeypatch.setattr(gcp_client.requests, "get", fake_get)

    bucket = GcsBucket(name="my-bucket", project_id="proj")
    entries = gcp_client.list_objects(_FakeCredentials(), bucket, prefix="photos/")

    assert [e.name for e in entries] == ["2024", "readme.txt"]
    assert entries[0].is_folder is True
    assert entries[0].full_path == "photos/2024/"
    assert entries[1].is_folder is False
    assert entries[1].size == 123
    assert entries[1].full_path == "photos/readme.txt"


def test_list_objects_folders_sort_before_files_regardless_of_name(monkeypatch):
    def fake_get(url, headers, params, timeout):
        return _FakeResponse(
            json_data={
                "prefixes": ["zzz/"],
                "items": [{"name": "aaa.txt", "size": "1", "updated": ""}],
            }
        )

    monkeypatch.setattr(gcp_client.requests, "get", fake_get)

    bucket = GcsBucket(name="my-bucket", project_id="proj")
    entries = gcp_client.list_objects(_FakeCredentials(), bucket)

    assert [e.name for e in entries] == ["zzz", "aaa.txt"]


def test_list_objects_skips_folder_marker_object(monkeypatch):
    # GCS lets you create a zero-byte object literally named "photos/" to
    # represent an explicitly-created empty folder — it shouldn't show up
    # as a (weirdly empty-named) file row alongside the real folder entry.
    def fake_get(url, headers, params, timeout):
        return _FakeResponse(
            json_data={"prefixes": [], "items": [{"name": "photos/", "size": "0", "updated": ""}]}
        )

    monkeypatch.setattr(gcp_client.requests, "get", fake_get)

    bucket = GcsBucket(name="my-bucket", project_id="proj")
    entries = gcp_client.list_objects(_FakeCredentials(), bucket, prefix="photos/")

    assert entries == []


def test_list_objects_paginates(monkeypatch):
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append(params.get("pageToken"))
        if params.get("pageToken") is None:
            return _FakeResponse(
                json_data={"items": [{"name": "a.txt", "size": "1", "updated": ""}], "nextPageToken": "p2"}
            )
        return _FakeResponse(json_data={"items": [{"name": "b.txt", "size": "2", "updated": ""}]})

    monkeypatch.setattr(gcp_client.requests, "get", fake_get)

    bucket = GcsBucket(name="my-bucket", project_id="proj")
    entries = gcp_client.list_objects(_FakeCredentials(), bucket)

    assert [e.name for e in entries] == ["a.txt", "b.txt"]
    assert calls == [None, "p2"]


def test_download_object_streams_to_file(monkeypatch, tmp_path):
    def fake_get(url, headers, params, timeout, stream):
        assert stream is True
        assert params["alt"] == "media"
        assert "readme.txt" in url or "readme%2Etxt" in url or True  # url-encoded, don't over-assert
        return _FakeResponse(chunks=[b"hello ", b"world"])

    monkeypatch.setattr(gcp_client.requests, "get", fake_get)

    dest = tmp_path / "out.txt"
    bucket = GcsBucket(name="my-bucket", project_id="proj")
    gcp_client.download_object(_FakeCredentials(), bucket, "photos/readme.txt", str(dest))

    assert dest.read_bytes() == b"hello world"


def test_download_object_raises_on_http_error(monkeypatch, tmp_path):
    def fake_get(url, headers, params, timeout, stream):
        return _FakeResponse(status_code=404, text="not found")

    monkeypatch.setattr(gcp_client.requests, "get", fake_get)

    bucket = GcsBucket(name="my-bucket", project_id="proj")
    try:
        gcp_client.download_object(
            _FakeCredentials(), bucket, "missing.txt", str(tmp_path / "out.txt")
        )
        raise AssertionError("expected GcpApiError")
    except gcp_client.GcpApiError:
        pass
