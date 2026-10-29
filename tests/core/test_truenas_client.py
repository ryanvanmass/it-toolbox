import threading

import pytest
from truenas_fake import API_KEY, FakeTrueNas

from it_toolbox.core import pinned_tls
from it_toolbox.core import truenas_client as tc


@pytest.fixture
def nas(tmp_path):
    with FakeTrueNas(tmp_path) as server:
        yield server


def connect(nas, **kwargs):
    options = {"api_key": API_KEY, "verify_ssl": False, "fingerprint": nas.fingerprint, **kwargs}
    return tc.TrueNasConnection(nas.url, options["api_key"], options["verify_ssl"], options["fingerprint"]).open()


def test_websocket_url():
    assert tc.websocket_url("https://nas.lan:443") == "wss://nas.lan:443/api/current"
    assert tc.websocket_url("https://nas.lan") == "wss://nas.lan/api/current"


def test_parse_version():
    assert tc.parse_version("TrueNAS-25.04.2.1") == (25, 4)
    assert tc.parse_version("25.10.0") == (25, 10)
    assert tc.parse_version("") is None


def test_open_logs_in_and_reads_system_info(nas):
    connection = connect(nas)
    try:
        assert connection.version == (25, 4)
        assert connection.system_info["hostname"] == "nas01"
        assert nas.methods_called()[:2] == ["auth.login_with_api_key", "system.info"]
    finally:
        connection.close()


def test_repr_never_shows_the_key(nas):
    connection = tc.TrueNasConnection(nas.url, API_KEY, fingerprint=nas.fingerprint)
    assert API_KEY not in repr(connection)


def test_wrong_key_is_an_auth_error(nas):
    with pytest.raises(tc.TrueNasAuthError):
        connect(nas, api_key="wrong")


def test_changed_certificate_is_refused_before_the_key_is_sent(nas):
    with pytest.raises(pinned_tls.CertificateMismatchError):
        connect(nas, fingerprint="AA:BB")
    assert nas.calls == []


def test_no_fingerprint_and_no_verification_is_refused(nas):
    with pytest.raises(tc.TrueNasError):
        connect(nas, fingerprint=None)


def test_http_url_is_refused_so_the_key_is_never_sent_in_the_clear():
    with pytest.raises(tc.TrueNasError, match="HTTPS"):
        tc.TrueNasConnection("http://nas.lan", API_KEY, fingerprint="AA").open()


def test_verify_ssl_rejects_a_self_signed_certificate(nas):
    with pytest.raises(tc.TrueNasError):
        connect(nas, verify_ssl=True, fingerprint=None)


def test_too_old_release_is_unsupported(tmp_path):
    with FakeTrueNas(tmp_path, version="24.10.2") as old:
        with pytest.raises(tc.TrueNasUnsupportedError, match="25.04"):
            connect(old)


def test_missing_api_endpoint_is_unsupported(nas, monkeypatch):
    monkeypatch.setattr(tc, "websocket_url", lambda url: url.replace("https", "wss") + "/websocket")
    with pytest.raises(tc.TrueNasUnsupportedError):
        connect(nas)


def test_api_error_carries_errname_and_method(nas):
    nas.errors["pool.query"] = {"code": -32001, "message": "x", "data": {"errname": "EPERM", "reason": "Not authorized"}}
    connection = connect(nas)
    try:
        with pytest.raises(tc.TrueNasApiError) as raised:
            connection.call("pool.query")
        assert raised.value.method == "pool.query"
        assert raised.value.is_permission_error
        assert str(raised.value) == "Not authorized"
    finally:
        connection.close()


def test_validation_errors_name_their_fields(nas):
    nas.errors["pool.snapshot.create"] = {
        "code": -32602,
        "message": "Invalid params",
        "data": {"errname": "EINVAL", "reason": "[EINVAL] bad", "extra": [["snapshot_create.name", "already exists", 22]]},
    }
    connection = connect(nas)
    try:
        with pytest.raises(tc.TrueNasApiError, match="snapshot_create.name: already exists"):
            connection.call("pool.snapshot.create", {})
    finally:
        connection.close()


def test_missing_method_is_detected(nas):
    connection = connect(nas)
    try:
        with pytest.raises(tc.TrueNasApiError) as raised:
            connection.call("no.such.method")
        assert raised.value.is_method_missing
    finally:
        connection.close()


def test_concurrent_calls_get_their_own_replies(nas):
    connection = connect(nas)
    results = {}

    def call(method):
        results[method] = connection.call(method)

    threads = [threading.Thread(target=call, args=(m,)) for m in ("pool.query", "vm.query", "app.query", "disk.query")]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        assert results["vm.query"][0]["name"] == "homeassistant"
        assert results["pool.query"][0]["name"] == "tank"
        assert results["app.query"][0]["name"] == "proftpd"
    finally:
        connection.close()


def test_call_job_waits_and_reports_progress(nas):
    connection = connect(nas)
    progress = []
    try:
        connection.call_job("pool.scrub", 1, "START", on_progress=lambda p, d: progress.append((p, d)))
        assert progress == [(100, "done")]
        assert ("core.get_jobs", [[["id", "=", 100]]]) in nas.calls
    finally:
        connection.close()


def test_failed_job_raises_with_its_error(nas):
    nas.failed_jobs["app.upgrade"] = "Image pull failed"
    connection = connect(nas)
    try:
        with pytest.raises(tc.TrueNasJobError, match="Image pull failed"):
            connection.call_job("app.upgrade", "proftpd", {})
    finally:
        connection.close()


def test_subscribe_delivers_events_and_unsubscribes(nas):
    connection = connect(nas)
    received = threading.Event()
    events = []

    def on_event(msg, fields):
        events.append((msg, fields))
        received.set()

    try:
        stop = connection.subscribe("reporting.realtime", on_event)
        assert received.wait(5)
        assert events[0][1]["cpu"]["cpu"]["usage"] == 12.5
        stop()
        assert ("core.unsubscribe", ["sub-reporting.realtime"]) in nas.calls
    finally:
        connection.close()


def test_calls_after_close_fail_cleanly(nas):
    connection = connect(nas)
    connection.close()
    with pytest.raises(tc.TrueNasError):
        connection.call("pool.query")


def test_test_connection_summary(nas):
    assert tc.test_connection(nas.url, API_KEY, False, nas.fingerprint) == "TrueNAS 25.04.2.1, nas01"
