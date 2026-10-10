import json
import shlex

import paramiko
import pytest

from it_toolbox.core import proftpd_manager as pm


def _server(**overrides):
    values = {"name": "nas", "host": "nas.lan", "username": "admin"}
    values.update(overrides)
    return pm.ProftpdServer(**values)


# -- ProftpdServer --------------------------------------------------------


def test_server_round_trips_through_dict():
    server = _server(port=2200, key_path="/k", docker_container="proftpd")
    assert pm.ProftpdServer.from_dict(server.to_dict()) == server


def test_server_from_dict_defaults_and_rejects_garbage():
    server = pm.ProftpdServer.from_dict({"name": "a", "host": "h", "username": "u", "port": None})
    assert server.port == pm.SSH_PORT and server.key_path is None and server.docker_container is None
    assert pm.ProftpdServer.from_dict({"name": "a"}) is None
    assert pm.ProftpdServer.from_dict({"name": "a", "host": "h", "username": "u", "port": "x"}) is None


# -- Live log parsing -------------------------------------------------------


def _line(*fields):
    return "\t".join(fields)


def test_live_log_format_is_tab_separated_with_free_text_last():
    fields = pm.LIVE_LOG_FORMAT.split("\t")
    assert fields[-2:] == ["%S", "%r"]
    assert f"LogFormat {pm.LIVE_LOG_FORMAT_NAME} \"{pm.LIVE_LOG_FORMAT}\"" in pm.LIVE_LOG_CONF
    assert f"ExtendedLog {pm.LIVE_LOG_PATH} ALL,CONNECT,EXIT" in pm.LIVE_LOG_CONF


def test_parse_live_line_command():
    event = pm.parse_live_line(
        _line("1791419672", "35", "10.0.0.5", "ftp", "alice", "226", "3",
              "Transfer complete", 'RETR a"b c.txt') + "\n"
    )
    assert event == pm.LiveEvent(
        timestamp=1791419672, pid=35, address="10.0.0.5", protocol="ftp", user="alice",
        code="226", bytes=3, response="Transfer complete", command='RETR a"b c.txt',
    )
    assert not event.is_session_event


def test_parse_live_line_session_event_and_dashes():
    event = pm.parse_live_line(_line("1", "35", "10.0.0.5", "ftp", "-", "-", "-", "-", ""))
    assert event.is_session_event
    assert (event.user, event.code, event.bytes, event.response) == (None, None, None, None)


def test_parse_live_line_keeps_tabs_inside_the_command():
    event = pm.parse_live_line(_line("1", "2", "a", "ftp", "u", "226", "0", "ok", "STOR a\tb"))
    assert event.command == "STOR a\tb"


@pytest.mark.parametrize("line", ["", "garbage", _line("x", "2", "a", "ftp", "u", "1", "0", "r", "c")])
def test_parse_live_line_rejects_other_lines(line):
    assert pm.parse_live_line(line) is None


def test_parse_ftpwho_json():
    text = json.dumps({
        "server": {"pid": 1},
        "connections": [
            {"pid": 47, "connected_since_ms": 1791419677000, "remote_address": "10.0.0.9",
             "user": "alice", "protocol": "ftp", "location": "/", "idling": True},
            {"pid": 48, "remote_name": "host", "protocol": "sftp", "idling": False,
             "command": "RETR", "command_args": "big.iso"},
            {"no_pid": True},
        ],
    })
    first, second = pm.parse_ftpwho_json(text)
    assert (first.pid, first.address, first.user, first.connected_since, first.idle) == (
        47, "10.0.0.9", "alice", 1791419677.0, True
    )
    assert (second.address, second.user, second.command) == ("host", None, "RETR big.iso")


def test_parse_ftpwho_json_rejects_non_json():
    with pytest.raises(pm.ProftpdError):
        pm.parse_ftpwho_json("no users connected")


# -- ProftpdConnection ---------------------------------------------------------


class _ScriptedConnection(pm.ProftpdConnection):
    """Replaces the SSH exec with a list of canned (status, out, err)
    results, recording each command line and stdin."""

    def __init__(self, server, results, **kwargs):
        super().__init__(server, **kwargs)
        self._client = object()
        self.results = list(results)
        self.calls = []

    def _exec_raw(self, command, stdin=b""):
        self.calls.append((command, stdin))
        return self.results.pop(0)


def test_root_needs_no_privilege_prefix():
    conn = _ScriptedConnection(_server(username="root"), [])
    conn._detect_privilege()
    assert conn.command_line(["ftpwho"]) == "ftpwho"


def test_passwordless_sudo():
    conn = _ScriptedConnection(_server(), [(0, "", "")])
    conn._detect_privilege()
    assert conn.calls == [("sudo -n true", b"")]
    assert conn.command_line(["ftpwho", "-o", "json"]) == "sudo -n -- ftpwho -o json"


def test_sudo_without_password_asks_for_one():
    conn = _ScriptedConnection(_server(), [(1, "", "sudo: a password is required")])
    with pytest.raises(pm.SudoPasswordRequired) as info:
        conn._detect_privilege()
    assert not info.value.incorrect


def test_sudo_password_is_sent_first_on_stdin_and_checked():
    conn = _ScriptedConnection(_server(), [(1, "", ""), (0, "", "")], sudo_password="s3cret")
    conn._detect_privilege()
    command, stdin = conn.calls[1]
    assert shlex.split(command) == ["sudo", "-k", "-S", "-p", "", "--", "true"]
    assert stdin == b"s3cret\n"


def test_wrong_sudo_password():
    conn = _ScriptedConnection(_server(), [(1, "", ""), (1, "", "")], sudo_password="nope")
    with pytest.raises(pm.SudoPasswordRequired) as info:
        conn._detect_privilege()
    assert info.value.incorrect


def test_docker_container_wraps_commands_but_not_host_ones():
    conn = _ScriptedConnection(_server(username="root", docker_container="proftpd"), [])
    assert conn.command_line(["ftpwho"]) == "docker exec -i proftpd ftpwho"
    assert conn.command_line(["ftpwho"], in_container=False) == "ftpwho"


def test_find_helper_prefers_the_cockpit_install():
    conn = _ScriptedConnection(_server(username="root"), [(0, "", "")])
    assert conn._find_helper() == pm.COCKPIT_HELPER_PATH

    conn = _ScriptedConnection(_server(username="root"), [(1, "", ""), (0, "", "")])
    assert conn._find_helper() == pm.BUNDLED_HELPER_PATH

    conn = _ScriptedConnection(_server(username="root"), [(1, "", ""), (1, "", "")])
    assert conn._find_helper() is None


def test_call_sends_json_args_and_returns_result():
    conn = _ScriptedConnection(
        _server(username="root"), [(0, json.dumps({"users": [{"username": "a"}]}), "")]
    )
    conn.helper_path = pm.COCKPIT_HELPER_PATH
    assert conn.list_users() == [{"username": "a"}]
    command, stdin = conn.calls[0]
    assert shlex.split(command) == [pm.COCKPIT_HELPER_PATH, "list-users"]
    assert json.loads(stdin) == {}


def test_call_raises_the_helpers_error_message():
    conn = _ScriptedConnection(_server(username="root"), [(0, '{"error": "User \'x\' does not exist."}', "")])
    conn.helper_path = pm.COCKPIT_HELPER_PATH
    with pytest.raises(pm.ProftpdError, match="does not exist"):
        conn.delete_user("x")


def test_call_reports_non_json_output():
    conn = _ScriptedConnection(_server(username="root"), [(2, "", "unknown subcommand")])
    conn.helper_path = pm.COCKPIT_HELPER_PATH
    with pytest.raises(pm.ProftpdError, match="unknown subcommand"):
        conn.status()


def test_call_without_helper():
    conn = _ScriptedConnection(_server(username="root"), [])
    with pytest.raises(pm.ProftpdError, match="isn't installed"):
        conn.status()


def test_update_user_omits_a_blank_password():
    conn = _ScriptedConnection(_server(username="root"), [(0, "{}", ""), (0, "{}", "")])
    conn.helper_path = pm.COCKPIT_HELPER_PATH
    conn.update_user("a", None, {"locked": True})
    conn.update_user("a", "newpass1", {})
    assert json.loads(conn.calls[0][1]) == {"username": "a", "locked": True}
    assert json.loads(conn.calls[1][1]) == {"username": "a", "password": "newpass1"}


def test_enable_live_log_pipes_the_config_into_the_script():
    conn = _ScriptedConnection(_server(username="root"), [(0, "", "")])
    conn.enable_live_log()
    command, stdin = conn.calls[0]
    argv = shlex.split(command)
    assert argv[:2] == ["sh", "-c"]
    assert f"cat > {pm.LIVE_LOG_CONF_PATH}" in argv[2]
    assert "proftpd --configtest" in argv[2]
    assert stdin == pm.LIVE_LOG_CONF.encode()


def test_enable_live_log_reports_a_config_error():
    conn = _ScriptedConnection(_server(username="root"), [(1, "", "fatal: unknown directive")])
    with pytest.raises(pm.ProftpdError, match="unknown directive"):
        conn.enable_live_log()


def test_live_log_enabled_checks_the_conf_file():
    conn = _ScriptedConnection(_server(username="root"), [(0, "", ""), (1, "", "")])
    assert conn.live_log_enabled() is True
    assert conn.live_log_enabled() is False


def test_kick_session_passes_the_pid_as_an_argument():
    conn = _ScriptedConnection(_server(username="root"), [(0, "", ""), (1, "", "")])
    conn.kick_session(47)
    argv = shlex.split(conn.calls[0][0])
    assert argv[0:2] == ["sh", "-c"] and argv[-1] == "47"
    with pytest.raises(pm.ProftpdError, match="already ended"):
        conn.kick_session(48)


def test_list_sessions_reports_a_missing_ftpwho():
    conn = _ScriptedConnection(_server(username="root"), [(127, "", "ftpwho: not found")])
    with pytest.raises(pm.ProftpdError, match="not found"):
        conn.list_sessions()


def test_install_bundled_helper_ships_all_three_files():
    conn = _ScriptedConnection(_server(username="root"), [(0, "", "")])
    assert conn.install_bundled_helper() == pm.BUNDLED_HELPER_PATH
    payload = json.loads(conn.calls[0][1])
    assert sorted(payload) == sorted(pm.BUNDLED_HELPER_FILES)
    assert conn.helper_path == pm.BUNDLED_HELPER_PATH


def test_bundled_helper_files_exist():
    for name in pm.BUNDLED_HELPER_FILES:
        assert (pm.BUNDLED_HELPER_SOURCE / name).is_file()


def test_install_bundled_helper_refused_for_a_container():
    conn = _ScriptedConnection(_server(username="root", docker_container="c"), [])
    with pytest.raises(pm.ProftpdError):
        conn.install_bundled_helper()


class _FakeChannel:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.command = None
        self.sent = b""
        self.closed = False

    def settimeout(self, _):
        pass

    def exec_command(self, command):
        self.command = command

    def sendall(self, data):
        self.sent += data

    def recv(self, _):
        chunk = self.chunks.pop(0) if self.chunks else b""
        if isinstance(chunk, Exception):
            raise chunk
        return chunk

    def shutdown_write(self):
        pass

    def close(self):
        self.closed = True


class _FakeClient:
    def __init__(self, channel):
        self.channel = channel

    def get_transport(self):
        return self

    def open_session(self):
        return self.channel


def test_follow_live_log_splits_lines_across_chunks():
    channel = _FakeChannel([b"one\ntw", TimeoutError(), b"o\nthree\n", b""])
    conn = pm.ProftpdConnection(_server(), sudo_password="pw")
    conn._client = _FakeClient(channel)
    conn._privilege = ["sudo", "-k", "-S", "-p", "", "--"]
    conn._sends_sudo_password = True
    batches = []

    conn.follow_live_log(batches.append, lambda: False)

    assert batches == [["one"], ["two", "three"]]
    assert channel.sent == b"pw\n"
    assert "tail -n" in channel.command and pm.LIVE_LOG_PATH in channel.command
    assert channel.closed


def test_follow_live_log_stops_when_asked():
    channel = _FakeChannel([b"a\n"] * 100)
    conn = pm.ProftpdConnection(_server(username="root"))
    conn._client = _FakeClient(channel)
    seen = []

    conn.follow_live_log(seen.extend, lambda: len(seen) >= 3)

    assert seen == ["a", "a", "a"]
    assert channel.closed


def test_connect_maps_auth_failures(monkeypatch):
    def fake_connect(self, *args, **kwargs):
        raise paramiko.AuthenticationException("nope")

    monkeypatch.setattr(paramiko.SSHClient, "connect", fake_connect)
    with pytest.raises(pm.LoginPasswordRequired):
        pm.ProftpdConnection(_server()).connect()

    def fake_connect_key(self, *args, **kwargs):
        raise paramiko.PasswordRequiredException("encrypted key")

    monkeypatch.setattr(paramiko.SSHClient, "connect", fake_connect_key)
    with pytest.raises(pm.KeyPassphraseRequired):
        pm.ProftpdConnection(_server(key_path="/k")).connect()
