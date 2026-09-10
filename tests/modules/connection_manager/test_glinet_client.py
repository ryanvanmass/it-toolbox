import pytest
import requests

from it_toolbox.modules.connection_manager import glinet_client
from it_toolbox.modules.connection_manager.models import GlinetHost

HOST = GlinetHost(name="Travel Router", url="https://192.168.8.1/rpc", username="root")


class _FakeApiGroup:
    def __init__(self, **methods):
        for name, fn in methods.items():
            setattr(self, name, fn)


class _FakeApiClient:
    def __init__(self, status=None, clients=None, wifi_config=None, set_config_calls=None,
                 reboot_calls=None):
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
    status = {
        "system": {"uptime": "1d", "lan_ip": "192.168.8.1", "cpu_temp": 45.5,
                    "memory": {"total": 1000, "free": 250}},
        "wifi": {"radio0": {"iface_name": "wifi0", "band": "2.4G", "ssid": "MyWifi", "up": True}},
        "service": {
            "wg_client": {"up": True}, "wg_server": {"up": False},
            "ovpn_client": {"up": False}, "ovpn_server": {"up": True},
        },
        "client": {"wireless_total": 3, "cable_total": 1},
    }
    _install_fake_glinet(monkeypatch, api_client=_FakeApiClient(status=status))

    overview = glinet_client.get_overview(HOST, "secret")

    assert overview.uptime == "1d"
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
    config = {
        "radio0": {
            "hwmode": "2.4G",
            "ifaces": [{"iface_name": "default_radio0", "ssid": "MyWifi", "enabled": True}],
        }
    }
    _install_fake_glinet(monkeypatch, api_client=_FakeApiClient(wifi_config=config))

    radios = glinet_client.get_wifi_config(HOST, "secret")

    assert len(radios) == 1
    assert radios[0].device == "radio0"
    assert radios[0].iface_name == "default_radio0"
    assert radios[0].band == "2.4G"
    assert radios[0].ssid == "MyWifi"
    assert radios[0].enabled is True


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
