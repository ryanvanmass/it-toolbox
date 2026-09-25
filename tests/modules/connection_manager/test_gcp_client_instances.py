import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from it_toolbox.modules.connection_manager import gcp_client


class _FakeCredentials:
    token = "fake-token"


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json = json_data
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._json


def test_start_instance_posts_to_start_endpoint(monkeypatch):
    calls = []

    def fake_post(url, headers, params, json, timeout):
        calls.append((url, headers, json))
        return _FakeResponse(json_data={"status": "RUNNING"})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    gcp_client.start_instance(_FakeCredentials(), "proj", "us-central1-a", "my-vm")

    (url, headers, body) = calls[0]
    assert url.endswith("/projects/proj/zones/us-central1-a/instances/my-vm/start")
    assert headers["Authorization"] == "Bearer fake-token"
    assert headers["X-Goog-User-Project"] == "proj"
    assert body is None


def test_stop_instance_posts_to_stop_endpoint(monkeypatch):
    calls = []

    def fake_post(url, headers, params, json, timeout):
        calls.append(url)
        return _FakeResponse(json_data={"status": "STOPPING"})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    gcp_client.stop_instance(_FakeCredentials(), "proj", "us-central1-a", "my-vm")

    assert calls[0].endswith("/projects/proj/zones/us-central1-a/instances/my-vm/stop")


def test_stop_instance_force_sets_no_graceful_shutdown_param(monkeypatch):
    calls = []

    def fake_post(url, headers, params, json, timeout):
        calls.append((url, params))
        return _FakeResponse(json_data={"status": "STOPPING"})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    gcp_client.stop_instance(_FakeCredentials(), "proj", "us-central1-a", "my-vm", force=True)

    (url, params) = calls[0]
    assert url.endswith("/projects/proj/zones/us-central1-a/instances/my-vm/stop")
    assert params == {"noGracefulShutdown": "true"}


def test_stop_instance_without_force_sends_no_params(monkeypatch):
    calls = []

    def fake_post(url, headers, params, json, timeout):
        calls.append(params)
        return _FakeResponse(json_data={"status": "STOPPING"})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    gcp_client.stop_instance(_FakeCredentials(), "proj", "us-central1-a", "my-vm")

    assert calls == [None]


def test_start_instance_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        gcp_client.requests,
        "post",
        lambda url, headers, params, json, timeout: _FakeResponse(
            status_code=400, text="bad request"
        ),
    )

    try:
        gcp_client.start_instance(_FakeCredentials(), "proj", "us-central1-a", "my-vm")
        raise AssertionError("expected GcpApiError")
    except gcp_client.GcpApiError:
        pass


def _aggregated_list_response(instance_overrides):
    instance = {
        "name": "my-vm",
        "status": "RUNNING",
        "networkInterfaces": [{"name": "nic0"}],
    }
    instance.update(instance_overrides)
    return _FakeResponse(
        json_data={"items": {"zones/us-central1-a": {"instances": [instance]}}}
    )


def test_list_instances_detects_windows_from_boot_disk_license(monkeypatch):
    response = _aggregated_list_response(
        {
            "disks": [
                {
                    "boot": True,
                    "licenses": [
                        "https://www.googleapis.com/compute/v1/projects/windows-cloud/"
                        "global/licenses/windows-server-2022-dc"
                    ],
                }
            ]
        }
    )
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: response)

    (instance,) = gcp_client.list_instances(_FakeCredentials(), "proj")

    assert instance.os_hint == "windows"


def test_list_instances_detects_linux_from_boot_disk_license(monkeypatch):
    response = _aggregated_list_response(
        {
            "disks": [
                {
                    "boot": True,
                    "licenses": [
                        "https://www.googleapis.com/compute/v1/projects/debian-cloud/"
                        "global/licenses/debian-11-bullseye"
                    ],
                }
            ]
        }
    )
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: response)

    (instance,) = gcp_client.list_instances(_FakeCredentials(), "proj")

    assert instance.os_hint == "linux"


def test_list_instances_os_hint_none_when_no_boot_disk(monkeypatch):
    response = _aggregated_list_response({"disks": [{"boot": False, "licenses": ["x"]}]})
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: response)

    (instance,) = gcp_client.list_instances(_FakeCredentials(), "proj")

    assert instance.os_hint is None


def test_list_instances_os_hint_none_when_no_disks(monkeypatch):
    response = _aggregated_list_response({})
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: response)

    (instance,) = gcp_client.list_instances(_FakeCredentials(), "proj")

    assert instance.os_hint is None


def test_os_hint_from_disks_directly():
    assert gcp_client._os_hint_from_disks([]) is None
    assert gcp_client._os_hint_from_disks([{"boot": True, "licenses": []}]) is None
    assert (
        gcp_client._os_hint_from_disks([{"boot": True, "licenses": [".../windows-11-dc"]}])
        == "windows"
    )
    assert (
        gcp_client._os_hint_from_disks([{"boot": True, "licenses": [".../ubuntu-2204-lts"]}])
        == "linux"
    )
    # A non-boot disk is ignored even if it has licenses.
    assert (
        gcp_client._os_hint_from_disks(
            [{"boot": False, "licenses": [".../windows-11-dc"]}, {"boot": True, "licenses": []}]
        )
        is None
    )


# -- reset_windows_password ---------------------------------------------------
#
# There is no Compute Engine REST method for this: it's a handshake with the
# Google guest agent inside the VM (windows-keys metadata in, an RSA-encrypted
# password back on serial port 4). _FakeGce stands in for both the API and the
# agent, so these tests exercise the real key encoding and decryption end to
# end rather than just checking a URL.


def _oaep_sha1():
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)


def _expire_on(minutes_from_now):
    moment = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _foreign_request(username, minutes_from_now):
    """Someone else's windows-keys entry, with a real (small) key so the fake
    agent can answer it."""
    numbers = rsa.generate_private_key(65537, 1024).public_key().public_numbers()

    def b64(value):
        return base64.b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).decode()

    return json.dumps(
        {
            "userName": username,
            "modulus": b64(numbers.n),
            "exponent": b64(numbers.e),
            "expireOn": _expire_on(minutes_from_now),
        }
    )


class _Clock:
    """Fake time so the polling loop runs instantly."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self):
        return self.now


class _FakeGce:
    def __init__(
        self,
        status="RUNNING",
        items=None,
        password="Sup3r-s3cret!",
        answer=True,
        error_message=None,
        serial="",
        chunk=None,
        quiet_polls=0,
        set_metadata_status=200,
    ):
        self.status = status
        self.items = items or []
        self.fingerprint = "fp-1"
        self.password = password
        self.answer = answer
        self.error_message = error_message
        self.serial = serial  # everything printed on serial port 4 so far
        self.chunk = chunk  # max characters returned per serial read
        self.quiet_polls = quiet_polls  # serial reads before the agent's output shows up
        self.set_metadata_status = set_metadata_status
        self.set_metadata_calls = []
        self.serial_reads = 0
        self._unprinted = ""

    def install(self, monkeypatch):
        monkeypatch.setattr(gcp_client.requests, "get", self.get)
        monkeypatch.setattr(gcp_client.requests, "post", self.post)

    def get(self, url, headers, params, timeout):
        assert headers["Authorization"] == "Bearer fake-token"
        assert headers["X-Goog-User-Project"] == "proj"
        if url.endswith("/serialPort"):
            assert params["port"] == 4
            self.serial_reads += 1
            if self.serial_reads > self.quiet_polls:
                self.serial += self._unprinted
                self._unprinted = ""
            start = params["start"]
            text = self.serial[start:]
            if self.chunk:
                text = text[: self.chunk]
            return _FakeResponse(json_data={"contents": text, "start": start, "next": start + len(text)})
        assert url.endswith("/projects/proj/zones/us-central1-a/instances/my-vm")
        return _FakeResponse(
            json_data={
                "status": self.status,
                "metadata": {
                    "fingerprint": self.fingerprint,
                    "items": json.loads(json.dumps(self.items)),
                },
            }
        )

    def post(self, url, headers, params, json, timeout):
        assert url.endswith("/projects/proj/zones/us-central1-a/instances/my-vm/setMetadata")
        self.set_metadata_calls.append(json)
        if self.set_metadata_status != 200:
            return _FakeResponse(status_code=self.set_metadata_status, text="denied")
        if json["fingerprint"] != self.fingerprint:
            return _FakeResponse(status_code=412, text="fingerprint mismatch")
        self.items = json["items"]
        self._guest_agent_reacts()
        return _FakeResponse(json_data={"kind": "compute#operation"})

    def _guest_agent_reacts(self):
        """Like the real agent: answer every unexpired windows-keys request by
        encrypting the password to *that request's* public key."""
        if not self.answer:
            return
        value = next((i["value"] for i in self.items if i["key"] == "windows-keys"), "")
        for line in value.splitlines():
            try:
                request = json.loads(line)
                expired = datetime.fromisoformat(request["expireOn"]) <= datetime.now(timezone.utc)
            except (ValueError, KeyError):
                continue
            if expired:
                continue
            if self.error_message:
                reply = {"userName": request["userName"], "modulus": request["modulus"],
                         "errorMessage": self.error_message}
            else:
                public_key = rsa.RSAPublicNumbers(
                    int.from_bytes(base64.b64decode(request["exponent"]), "big"),
                    int.from_bytes(base64.b64decode(request["modulus"]), "big"),
                ).public_key()
                encrypted = public_key.encrypt(self.password.encode(), _oaep_sha1())
                reply = {
                    "userName": request["userName"],
                    "modulus": request["modulus"],
                    "exponent": request["exponent"],
                    "passwordFound": True,
                    "encryptedPassword": base64.b64encode(encrypted).decode(),
                }
            self._unprinted += json.dumps(reply) + "\n"


def _reset(fake, monkeypatch, clock=None, **kwargs):
    fake.install(monkeypatch)
    clock = clock or _Clock()
    return gcp_client.reset_windows_password(
        _FakeCredentials(),
        "proj",
        "us-central1-a",
        "my-vm",
        username="alice",
        _sleep=clock.sleep,
        _monotonic=clock.monotonic,
        **kwargs,
    )


def _our_windows_key_line(fake):
    value = next(i["value"] for i in fake.items if i["key"] == "windows-keys")
    return json.loads(value.splitlines()[-1])


def test_reset_windows_password_round_trips_through_the_guest_agent(monkeypatch):
    fake = _FakeGce(password="Sup3r-s3cret!")

    username, password = _reset(fake, monkeypatch)

    assert (username, password) == ("alice", "Sup3r-s3cret!")


def test_reset_windows_password_sends_a_well_formed_windows_keys_request(monkeypatch):
    fake = _FakeGce()

    _reset(fake, monkeypatch)

    (call,) = fake.set_metadata_calls
    assert call["fingerprint"] == "fp-1"
    request = _our_windows_key_line(fake)
    assert set(request) == {"userName", "modulus", "exponent", "expireOn"}
    assert request["userName"] == "alice"
    assert request["exponent"] == "AQAB"  # 65537
    assert int.from_bytes(base64.b64decode(request["modulus"]), "big").bit_length() == 2048
    expires = datetime.fromisoformat(request["expireOn"])
    remaining = expires - datetime.now(timezone.utc)
    assert timedelta(minutes=4) < remaining <= timedelta(minutes=5)


def test_reset_windows_password_merges_into_existing_metadata(monkeypatch):
    live = _foreign_request("bob", minutes_from_now=3)
    expired = _foreign_request("carol", minutes_from_now=-10)
    fake = _FakeGce(
        items=[
            {"key": "startup-script", "value": "echo hi"},
            {"key": "windows-keys", "value": "\n".join([live, expired, "not json"])},
        ]
    )

    username, password = _reset(fake, monkeypatch)

    assert (username, password) == ("alice", "Sup3r-s3cret!")
    by_key = {item["key"]: item["value"] for item in fake.items}
    assert by_key["startup-script"] == "echo hi"
    lines = by_key["windows-keys"].splitlines()
    # someone else's pending request survives, the expired one is dropped, the
    # unparseable line isn't ours to delete, and ours is appended last
    assert lines[0] == live
    assert "not json" in lines
    assert not any('"carol"' in line for line in lines)
    assert json.loads(lines[-1])["userName"] == "alice"


def test_reset_windows_password_keeps_polling_until_the_agent_answers(monkeypatch):
    fake = _FakeGce(quiet_polls=2)
    clock = _Clock()

    username, password = _reset(fake, monkeypatch, clock=clock)

    assert password == "Sup3r-s3cret!"
    assert fake.serial_reads == 3
    assert clock.sleeps == [gcp_client.WINDOWS_PASSWORD_POLL_INTERVAL_SEC] * 2


def test_reset_windows_password_picks_its_own_answer_out_of_the_noise(monkeypatch):
    # Other requests' answers (which we can't decrypt) and console noise share
    # serial port 4; only the line carrying our modulus counts.
    fake = _FakeGce(
        items=[{"key": "windows-keys", "value": _foreign_request("bob", minutes_from_now=3)}],
        serial='boot noise\n{"modulus": "someone-else", "encryptedPassword": "AAAA"}\nnot json {\n',
    )

    assert _reset(fake, monkeypatch) == ("alice", "Sup3r-s3cret!")


def test_reset_windows_password_handles_an_answer_split_across_reads(monkeypatch):
    fake = _FakeGce(chunk=40)

    assert _reset(fake, monkeypatch) == ("alice", "Sup3r-s3cret!")
    assert fake.serial_reads > 3  # the reply really did arrive in pieces


def test_reset_windows_password_reports_an_agent_error(monkeypatch):
    fake = _FakeGce(error_message="account name is not allowed")

    with pytest.raises(gcp_client.GcpApiError, match="couldn't reset the password.*not allowed"):
        _reset(fake, monkeypatch)


def test_reset_windows_password_refuses_a_stopped_instance(monkeypatch):
    fake = _FakeGce(status="TERMINATED")

    with pytest.raises(gcp_client.GcpApiError, match="TERMINATED"):
        _reset(fake, monkeypatch)

    assert fake.set_metadata_calls == []  # nothing was written to the VM


def test_reset_windows_password_times_out_when_the_agent_never_answers(monkeypatch):
    fake = _FakeGce(answer=False)
    clock = _Clock()

    with pytest.raises(gcp_client.GcpApiError, match="didn't answer within 10 seconds"):
        _reset(fake, monkeypatch, clock=clock, timeout=10, poll_interval=3)

    assert clock.now >= 10


def test_reset_windows_password_surfaces_a_metadata_permission_error(monkeypatch):
    fake = _FakeGce(set_metadata_status=403)

    with pytest.raises(gcp_client.GcpApiError, match="403"):
        _reset(fake, monkeypatch)
