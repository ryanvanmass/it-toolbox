import json
import shlex

import pytest

from it_toolbox.core import remote_helper as rh


def _server(**overrides):
    values = {"name": "web", "host": "web.lan", "username": "admin"}
    values.update(overrides)
    return rh.RemoteServer(**values)


class _Connection(rh.RemoteHelperConnection):
    HELPER_PATHS = ("/usr/libexec/mod/helper", "/usr/local/libexec/mod/helper")
    MODULE_NAME = "cockpit-mod"


class _Scripted(_Connection):
    """Replaces the SSH exec with canned (status, out, err) results,
    recording each command line, stdin and timeout."""

    def __init__(self, server, results, **kwargs):
        super().__init__(server, **kwargs)
        self._client = object()
        self.results = list(results)
        self.calls = []

    def _exec_raw(self, command, stdin=b"", timeout=rh.DEFAULT_TIMEOUT):
        self.calls.append((command, stdin, timeout))
        return self.results.pop(0)


def test_server_round_trips_through_dict():
    server = _server(port=2200, key_path="/k")
    assert rh.RemoteServer.from_dict(server.to_dict()) == server
    assert server.target == "admin@web.lan:2200"


def test_server_from_dict_defaults_and_rejects_garbage():
    server = rh.RemoteServer.from_dict({"name": "a", "host": "h", "username": "u", "port": None})
    assert server.port == rh.SSH_PORT and server.key_path is None
    assert rh.RemoteServer.from_dict({"name": "a"}) is None
    assert rh.RemoteServer.from_dict({"name": "a", "host": "h", "username": "u", "port": "x"}) is None


def test_root_needs_no_privilege_prefix():
    conn = _Scripted(_server(username="root"), [])
    conn._detect_privilege()
    assert conn.command_line(["id"]) == "id"


def test_passwordless_sudo():
    conn = _Scripted(_server(), [(0, "", "")])
    conn._detect_privilege()
    assert conn.calls[0][0] == "sudo -n true"
    assert conn.command_line(["id", "-u"]) == "sudo -n -- id -u"


def test_sudo_without_password_asks_for_one():
    conn = _Scripted(_server(), [(1, "", "sudo: a password is required")])
    with pytest.raises(rh.SudoPasswordRequired) as info:
        conn._detect_privilege()
    assert not info.value.incorrect


def test_sudo_password_is_sent_first_on_stdin_and_checked():
    conn = _Scripted(_server(), [(1, "", ""), (0, "", "")], sudo_password="s3cret")
    conn._detect_privilege()
    command, stdin, _ = conn.calls[1]
    assert shlex.split(command) == ["sudo", "-k", "-S", "-p", "", "--", "true"]
    assert stdin == b"s3cret\n"


def test_wrong_sudo_password():
    conn = _Scripted(_server(), [(1, "", ""), (1, "", "")], sudo_password="nope")
    with pytest.raises(rh.SudoPasswordRequired) as info:
        conn._detect_privilege()
    assert info.value.incorrect


def test_find_helper_tries_paths_in_order():
    assert _Scripted(_server(username="root"), [(0, "", "")])._find_helper() == _Connection.HELPER_PATHS[0]
    assert _Scripted(_server(username="root"), [(1, "", ""), (0, "", "")])._find_helper() == \
        _Connection.HELPER_PATHS[1]
    assert _Scripted(_server(username="root"), [(1, "", ""), (1, "", "")])._find_helper() is None


def test_call_sends_json_args_and_returns_result():
    conn = _Scripted(_server(), [(0, json.dumps({"ok": 1}), "")])
    conn._privilege = ["sudo", "-n", "--"]
    conn.helper_path = _Connection.HELPER_PATHS[0]
    assert conn.call("thing", {"a": 1}, timeout=99) == {"ok": 1}
    command, stdin, timeout = conn.calls[0]
    assert shlex.split(command) == ["sudo", "-n", "--", _Connection.HELPER_PATHS[0], "thing"]
    assert json.loads(stdin) == {"a": 1}
    assert timeout == 99


def test_call_sends_the_sudo_password_before_the_json():
    conn = _Scripted(_server(), [(0, "{}", "")], sudo_password="pw")
    conn._sends_sudo_password = True
    conn.helper_path = "/h"
    conn.call("status")
    assert conn.calls[0][1] == b"pw\n{}"


def test_call_raises_the_helpers_error_message():
    conn = _Scripted(_server(username="root"), [(0, '{"error": "There is no site \'x\'"}', "")])
    conn.helper_path = "/h"
    with pytest.raises(rh.RemoteHelperError, match="no site"):
        conn.call("site-get", {"name": "x"})


def test_call_reports_non_json_output():
    conn = _Scripted(_server(username="root"), [(1, "", "python3: not found")])
    conn.helper_path = "/h"
    with pytest.raises(rh.RemoteHelperError, match="Could not run status: python3: not found"):
        conn.call("status")


def test_call_without_helper_names_the_module():
    conn = _Scripted(_server(username="root"), [])
    with pytest.raises(rh.RemoteHelperError, match="cockpit-mod helper isn't installed"):
        conn.call("status")
