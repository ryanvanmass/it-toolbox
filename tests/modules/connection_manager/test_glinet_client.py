import pytest
import requests

from it_toolbox.modules.connection_manager import glinet_client
from it_toolbox.modules.connection_manager.models import GlinetHost

HOST = GlinetHost(name="Travel Router", url="https://192.168.8.1/rpc", username="root")


class _FakeApiGroup:
    def __init__(self, **methods):
        for name, fn in methods.items():
            setattr(self, name, fn)


def _status_or_raise(value):
    """Mirrors a real router: calling get_status() for a VPN type with
    no tunnel/config set up at all raises, rather than returning a
    clean "not configured" result -- `value=None` (the default, when a
    test doesn't care about that VPN type) simulates exactly that."""
    def fn():
        if value is None:
            raise RuntimeError("not configured")
        return value
    return fn


class _FakeApiClient:
    def __init__(self, status=None, clients=None, wifi_config=None, set_config_calls=None,
                 reboot_calls=None, wg_client_status=None, wg_server_status=None,
                 ovpn_client_status=None, ovpn_server_status=None):
        self.system = _FakeApiGroup(
            get_status=lambda: status or {},
            reboot=lambda params=None: (reboot_calls if reboot_calls is not None else []).append(
                params
            ),
        )
        self.clients = _FakeApiGroup(get_list=lambda: {"clients": clients or []})
        self.wifi = _FakeApiGroup(
            get_config=lambda: wifi_config or {},
            set_config=lambda params: (
                set_config_calls if set_config_calls is not None else []
            ).append(params),
        )
        self.wg_client = _FakeApiGroup(get_status=_status_or_raise(wg_client_status))
        self.wg_server = _FakeApiGroup(get_status=_status_or_raise(wg_server_status))
        self.ovpn_client = _FakeApiGroup(get_status=_status_or_raise(ovpn_client_status))
        self.ovpn_server = _FakeApiGroup(get_status=_status_or_raise(ovpn_server_status))


class _FakeGlInet:
    instances: list["_FakeGlInet"] = []

    def __init__(self, url, username, password, keep_alive, verify_ssl_certificate,
                 api_client=None, login_error=None):
        self.url = url
        self.username = username
        self.password = password
        self.keep_alive = keep_alive
        self.verify_ssl_certificate = verify_ssl_certificate
        self._api_client = api_client or _FakeApiClient()
        self._login_error = login_error
        self.logged_out = False
        _FakeGlInet.instances.append(self)

    def login(self):
        if self._login_error is not None:
            raise self._login_error
        return self

    def get_api_client(self):
        return self._api_client

    def logout(self):
        self.logged_out = True


def _install_fake_glinet(monkeypatch, **kwargs):
    _FakeGlInet.instances = []

    def factory(url, username, password, keep_alive, verify_ssl_certificate):
        return _FakeGlInet(url, username, password, keep_alive, verify_ssl_certificate, **kwargs)

    monkeypatch.setattr(glinet_client, "GlInet", factory)
    return _FakeGlInet


def test_is_available_true_when_glinet_importable(monkeypatch):
    monkeypatch.setattr(glinet_client, "GlInet", object())
    assert glinet_client.is_available() is True


def test_is_available_false_when_glinet_not_installed(monkeypatch):
    monkeypatch.setattr(glinet_client, "GlInet", None)
    assert glinet_client.is_available() is False


def test_raises_when_pyglinet_not_installed(monkeypatch):
    monkeypatch.setattr(glinet_client, "GlInet", None)

    with pytest.raises(glinet_client.GlinetApiError, match="isn't installed"):
        glinet_client.test_connection(HOST, "secret")


def test_call_always_uses_keep_alive_false(monkeypatch):
    fake_cls = _install_fake_glinet(monkeypatch)

    glinet_client.test_connection(HOST, "secret")

    assert len(fake_cls.instances) == 1
    assert fake_cls.instances[0].keep_alive is False
    assert fake_cls.instances[0].password == "secret"
    assert fake_cls.instances[0].url == HOST.url


def test_call_always_logs_out_on_success(monkeypatch):
    fake_cls = _install_fake_glinet(monkeypatch)

    glinet_client.test_connection(HOST, "secret")

    assert fake_cls.instances[0].logged_out is True


def test_call_logs_out_even_when_the_wrapped_call_raises(monkeypatch):
    def bad_status():
        raise RuntimeError("boom")

    api_client = _FakeApiClient()
    api_client.system.get_status = bad_status
    fake_cls = _install_fake_glinet(monkeypatch, api_client=api_client)

    with pytest.raises(RuntimeError):
        glinet_client.get_overview(HOST, "secret")

    assert fake_cls.instances[0].logged_out is True


class _FakeAccessDeniedError(Exception):
    pass


def test_pyglinet_exceptions_wrap_into_glinet_api_error(monkeypatch):
    monkeypatch.setattr(glinet_client, "_PYGLINET_ERRORS", (_FakeAccessDeniedError,))
    _install_fake_glinet(monkeypatch, login_error=_FakeAccessDeniedError("bad credentials"))

    with pytest.raises(glinet_client.GlinetApiError, match="bad credentials"):
        glinet_client.test_connection(HOST, "wrongpassword")


def test_connection_error_wraps_into_glinet_api_error(monkeypatch):
    _install_fake_glinet(monkeypatch, login_error=ConnectionError("unreachable"))

    with pytest.raises(glinet_client.GlinetApiError, match="unreachable"):
        glinet_client.test_connection(HOST, "secret")


def test_requests_exception_wraps_into_glinet_api_error(monkeypatch):
    _install_fake_glinet(monkeypatch, login_error=requests.ConnectionError("dns failure"))

    with pytest.raises(glinet_client.GlinetApiError, match="dns failure"):
        glinet_client.test_connection(HOST, "secret")


def test_get_overview_parses_status_response(monkeypatch):
    # Shape grounded in pyglinet's own bundled api_description.json
    # out_example for system.get_status -- wifi/client are lists, not
    # dicts keyed by name (see glinet_client.py's module docstring for
    # how this was discovered against a real router). VPN up/down comes
    # from each type's own dedicated get_status() (see
    # test_vpn_status_up_* below), not this generic status blob.
    status = {
        "system": {"uptime": 111, "lan_ip": "192.168.8.1",
                    "cpu": {"temperature": 45.5},
                    "memory_total": 1000, "memory_free": 250},
        "wifi": [{"name": "default_radio0", "band": "2.4G", "ssid": "MyWifi", "up": True}],
        "client": [{"wireless_total": 3, "cable_total": 1}],
    }
    _install_fake_glinet(monkeypatch, api_client=_FakeApiClient(
        status=status,
        wg_client_status={"status": 1},
        wg_server_status={"server": {"status": 0}},
        ovpn_client_status={"status": 0},
        ovpn_server_status={"status": 1},
    ))

    overview = glinet_client.get_overview(HOST, "secret")

    assert overview.uptime == "1m 51s"
    assert overview.lan_ip == "192.168.8.1"
    assert overview.cpu_temp == 45.5
    assert overview.memory_used_pct == 75.0
    assert overview.wireless_client_count == 3
    assert overview.cable_client_count == 1
    assert overview.wifi_radios[0].ssid == "MyWifi"
    assert overview.wifi_radios[0].enabled is True
    assert overview.wg_client_up is True
    assert overview.wg_server_up is False
    assert overview.ovpn_client_up is False
    assert overview.ovpn_server_up is True


def test_vpn_status_up_true_when_connected():
    api_client = _FakeApiClient(wg_client_status={"status": 1})
    assert glinet_client._vpn_status_up(api_client, "wg_client") is True


@pytest.mark.parametrize("status", [0, 2])
def test_vpn_status_up_false_when_not_connected(status):
    api_client = _FakeApiClient(ovpn_client_status={"status": status})
    assert glinet_client._vpn_status_up(api_client, "ovpn_client") is False


def test_vpn_status_up_reads_wg_server_nested_status():
    # wg_server.get_status()'s status lives under "server", unlike the
    # other three VPN types' get_status(), which put it at the top level.
    api_client = _FakeApiClient(wg_server_status={"server": {"status": 1}})
    assert glinet_client._vpn_status_up(api_client, "wg_server") is True


def test_vpn_status_up_false_when_type_is_not_configured_at_all():
    # get_status() raises for a VPN type with no tunnel/config at all --
    # confirmed against a real router that a client tunnel not present
    # in the generic system.get_status() service list doesn't mean the
    # dedicated endpoint fails the same way, so this is a defensive
    # fallback, not the expected path for a configured-but-down tunnel.
    api_client = _FakeApiClient()
    assert glinet_client._vpn_status_up(api_client, "wg_client") is False


def test_get_overview_handles_client_as_a_bare_dict_too(monkeypatch):
    # The API's own schema docs describe "client" as a single object even
    # though the concrete example wraps it in a list -- accept either.
    status = {
        "system": {},
        "wifi": [], "service": [],
        "client": {"wireless_total": 2, "cable_total": 0},
    }
    _install_fake_glinet(monkeypatch, api_client=_FakeApiClient(status=status))

    overview = glinet_client.get_overview(HOST, "secret")

    assert overview.wireless_client_count == 2
    assert overview.cable_client_count == 0


@pytest.mark.parametrize(("seconds", "expected"), [
    (0, "0s"),
    (45, "45s"),
    (111, "1m 51s"),
    (862.15, "14m 22s"),  # the fractional-seconds shape seen from a real router
    (3661, "1h 1m 1s"),
    (90000, "1d 1h 0m 0s"),
    (None, ""),
    ("garbage", ""),
])
def test_format_uptime(seconds, expected):
    assert glinet_client._format_uptime(seconds) == expected


def test_list_clients_parses_and_sorts(monkeypatch):
    clients = [
        {"mac": "aa:bb", "name": "zeta-phone", "ip": "192.168.8.10", "online": True, "vendor": "Acme"},
        {"mac": "cc:dd", "name": "alpha-laptop", "ip": "192.168.8.11", "online": False},
    ]
    _install_fake_glinet(monkeypatch, api_client=_FakeApiClient(clients=clients))

    result = glinet_client.list_clients(HOST, "secret")

    assert [c.name for c in result] == ["alpha-laptop", "zeta-phone"]
    assert result[1].vendor == "Acme"
    assert result[1].online is True
    assert result[0].online is False


def test_get_wifi_config_parses_bands_and_ifaces(monkeypatch):
    # Shape grounded in pyglinet's bundled api_description.json
    # out_example for wifi.get_config -- band configs live under a
    # top-level "res" list, and each iface's identifier is "name", not
    # "iface_name" (see glinet_client.py's module docstring).
    config = {
        "res": [
            {
                "device": "radio0",
                # "band" and "hwmode" are deliberately given different
                # values here -- a prior version of this parser read
                # "hwmode" for the radio's band by mistake, which this
                # test would not have caught if both fields held the
                # same value.
                "band": "2.4G",
                "hwmode": "11ac/ax",
                "ifaces": [
                    {"name": "default_radio0", "ssid": "MyWifi", "enabled": True, "guest": False},
                    {"name": "guest_radio0", "ssid": "MyWifi-Guest", "enabled": True, "guest": True},
                ],
            }
        ]
    }
    _install_fake_glinet(monkeypatch, api_client=_FakeApiClient(wifi_config=config))

    radios = glinet_client.get_wifi_config(HOST, "secret")

    assert len(radios) == 2
    assert radios[0].device == "radio0"
    assert radios[0].iface_name == "default_radio0"
    assert radios[0].band == "2.4G"
    assert radios[0].ssid == "MyWifi"
    assert radios[0].enabled is True
    assert radios[0].guest is False
    assert radios[1].guest is True


def test_set_wifi_config_sends_expected_params(monkeypatch):
    set_calls = []
    _install_fake_glinet(monkeypatch, api_client=_FakeApiClient(set_config_calls=set_calls))

    glinet_client.set_wifi_config(
        HOST, "secret", device="radio0", iface_name="default_radio0",
        ssid="NewName", key="newpass", enabled=True,
    )

    assert set_calls == [
        {"device": "radio0", "iface_name": "default_radio0", "ssid": "NewName",
         "enabled": True, "key": "newpass"}
    ]


def test_set_wifi_config_omits_key_when_not_provided(monkeypatch):
    set_calls = []
    _install_fake_glinet(monkeypatch, api_client=_FakeApiClient(set_config_calls=set_calls))

    glinet_client.set_wifi_config(
        HOST, "secret", device="radio0", iface_name="default_radio0",
        ssid="NewName", key=None, enabled=True,
    )

    assert "key" not in set_calls[0]


def test_reboot_calls_system_reboot(monkeypatch):
    reboot_calls = []
    _install_fake_glinet(monkeypatch, api_client=_FakeApiClient(reboot_calls=reboot_calls))

    glinet_client.reboot(HOST, "secret")

    assert reboot_calls == [None]


def test_reboot_passes_delay(monkeypatch):
    reboot_calls = []
    _install_fake_glinet(monkeypatch, api_client=_FakeApiClient(reboot_calls=reboot_calls))

    glinet_client.reboot(HOST, "secret", delay=30)

    assert reboot_calls == [{"delay": 30}]
