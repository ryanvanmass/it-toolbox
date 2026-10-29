"""A fake TrueNAS for tests: canned 25.04-shaped API results, and a real
TLS websocket server speaking the middleware's JSON-RPC 2.0 dialect
(login, calls, jobs via core.get_jobs, core.subscribe events).

    with FakeTrueNas(tmp_path) as nas:
        connection = TrueNasConnection(nas.url, nas.api_key, fingerprint=nas.fingerprint).open()
"""

import copy
import datetime
import hashlib
import json
import ssl
import threading
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from websockets.sync.server import serve

from it_toolbox.core import pinned_tls

API_KEY = "1-abcdefghijklmnopqrstuvwxyz"
MS = 1761696000000  # 2025-10-29T00:00Z, in the middleware's {"$date": ms} form


def _size(n):
    return {"value": str(n), "rawvalue": str(n), "parsed": n}


RESULTS = {
    "system.info": {
        "version": "25.04.2.1",
        "hostname": "nas01",
        "uptime_seconds": 93784.5,
        "physmem": 34359738368,
        "cores": 8,
        "loadavg": [0.42, 0.37, 0.3],
        "system_product": "TrueNAS Mini X+",
        "ecc_memory": True,
    },
    "alert.list": [
        {"uuid": "a1", "level": "WARNING", "klass": "SMART", "formatted": "Disk sdb: 8 reallocated sectors", "datetime": {"$date": MS}, "dismissed": False},
        {"uuid": "a2", "level": "INFO", "klass": "Update", "formatted": "An update is available", "datetime": {"$date": MS}, "dismissed": False},
        {"uuid": "a3", "level": "CRITICAL", "klass": "Old", "formatted": "Old problem", "datetime": {"$date": MS}, "dismissed": True},
    ],
    "pool.query": [
        {
            "id": 1,
            "name": "tank",
            "status": "ONLINE",
            "healthy": True,
            "size": 8000000000000,
            "allocated": 3000000000000,
            "free": 5000000000000,
            "scan": {"function": "SCRUB", "state": "FINISHED", "end_time": {"$date": MS}, "errors": 0},
            "topology": {
                "data": [
                    {
                        "name": "mirror-0",
                        "type": "MIRROR",
                        "status": "ONLINE",
                        "stats": {"read_errors": 0, "write_errors": 0, "checksum_errors": 0},
                        "children": [
                            {"name": "sda2", "disk": "sda", "type": "DISK", "status": "ONLINE", "stats": {}, "children": []},
                            {"name": "sdb2", "disk": "sdb", "type": "DISK", "status": "ONLINE", "stats": {"checksum_errors": 2}, "children": []},
                        ],
                    }
                ],
                "cache": [],
                "log": [],
            },
        }
    ],
    "disk.query": [
        {"identifier": "{serial}S1", "name": "sda", "serial": "S1", "model": "WDC WD80", "size": 8001563222016, "type": "HDD", "pool": "tank"},
        {"identifier": "{serial}S2", "name": "sdb", "serial": "S2", "model": "WDC WD80", "size": 8001563222016, "type": "HDD", "pool": "tank"},
    ],
    "disk.temperatures": {"sda": 34, "sdb": 37},
    "pool.dataset.query": [
        {"id": "tank", "pool": "tank", "type": "FILESYSTEM", "used": _size(3000), "available": _size(5000), "quota": _size(0), "compression": {"value": "LZ4"}, "encrypted": False, "locked": False, "mountpoint": "/mnt/tank"},
        {"id": "tank/media", "pool": "tank", "type": "FILESYSTEM", "used": _size(2000), "available": _size(5000), "quota": _size(10000), "compression": {"value": "LZ4"}, "encrypted": True, "locked": False, "mountpoint": "/mnt/tank/media"},
        {"id": "tank/vault", "pool": "tank", "type": "FILESYSTEM", "used": _size(10), "available": _size(5000), "quota": _size(0), "compression": {"value": "ZSTD"}, "encrypted": True, "locked": True, "mountpoint": "/mnt/tank/vault"},
    ],
    "pool.snapshot.query": [
        {"id": "tank/media@auto-2025-10-29", "dataset": "tank/media", "snapshot_name": "auto-2025-10-29", "properties": {"creation": {"parsed": {"$date": MS}}, "used": _size(1024), "referenced": _size(2048)}},
    ],
    "pool.snapshottask.query": [
        {"id": 1, "dataset": "tank/media", "recursive": True, "lifetime_value": 2, "lifetime_unit": "WEEK", "schedule": {"minute": "0", "hour": "*", "dom": "*", "month": "*", "dow": "*"}, "enabled": True, "state": {"state": "FINISHED", "datetime": {"$date": MS}}},
    ],
    "replication.query": [
        {"id": 3, "name": "media to backup", "direction": "PUSH", "transport": "SSH", "source_datasets": ["tank/media"], "target_dataset": "backup/media", "ssh_credentials": {"id": 7, "name": "backup-nas"}, "enabled": True, "schedule": {"minute": "0", "hour": "2", "dom": "*", "month": "*", "dow": "*"}, "state": {"state": "ERROR", "error": "No route to host", "datetime": {"$date": MS}}, "job": {"id": 41, "state": "FAILED", "error": "No route to host", "time_finished": {"$date": MS}}},
    ],
    "cloudsync.query": [
        {"id": 4, "description": "Photos to B2", "direction": "PUSH", "path": "/mnt/tank/media/photos", "credentials": {"id": 9, "name": "b2-main"}, "enabled": False, "schedule": {"minute": "0", "hour": "3", "dom": "*", "month": "*", "dow": "0"}, "job": None},
    ],
    "rsynctask.query": [],
    "pool.scrub.query": [
        {"id": 1, "pool": 1, "pool_name": "tank", "threshold": 35, "enabled": True, "schedule": {"minute": "0", "hour": "0", "dom": "*", "month": "*", "dow": "7"}},
    ],
    "smart.test.query": [
        {"id": 2, "type": "SHORT", "all_disks": True, "disks": [], "schedule": {"hour": "1", "dom": "*", "month": "*", "dow": "*"}},
    ],
    "keychaincredential.query": [
        {"id": 7, "name": "backup-nas", "type": "SSH_CREDENTIALS", "attributes": {"host": "10.0.0.9", "port": 22, "username": "root", "private_key": 6}},
        {"id": 6, "name": "backup-nas key", "type": "SSH_KEY_PAIR", "attributes": {"private_key": "-----BEGIN OPENSSH PRIVATE KEY-----SECRET", "public_key": "ssh-ed25519 AAAA"}},
    ],
    "cloudsync.credentials.query": [
        {"id": 9, "name": "b2-main", "provider": {"type": "B2", "account": "acct", "key": "SECRETKEY"}},
    ],
    "cloudsync.credentials.verify": {"valid": True},
    "sharing.smb.query": [
        {"id": 1, "name": "media", "path": "/mnt/tank/media", "enabled": True, "comment": "Family media"},
    ],
    "sharing.nfs.query": [
        {"id": 2, "path": "/mnt/tank/vms", "enabled": False, "comment": ""},
    ],
    "service.query": [
        {"service": "cifs", "state": "RUNNING", "enable": True},
        {"service": "nfs", "state": "STOPPED", "enable": False},
    ],
    "app.query": [
        {
            "name": "proftpd",
            "state": "RUNNING",
            "human_version": "1.3.8_1.0.2",
            "upgrade_available": True,
            "metadata": {"title": "ProFTPD"},
            "portals": {"Web UI": "http://0.0.0.0:9090/"},
            "active_workloads": {
                "used_ports": [{"container_port": 21, "protocol": "tcp", "host_ports": [{"host_port": 2121, "host_ip": "0.0.0.0"}]}],
                "container_details": [{"id": "c0ffee", "service_name": "proftpd", "image": "proftpd:1.3.8", "state": "running"}],
            },
        },
    ],
    "vm.query": [
        {"id": 1, "name": "homeassistant", "status": {"state": "RUNNING"}, "vcpus": 1, "cores": 2, "threads": 1, "memory": 4096, "autostart": True, "description": "HA OS"},
    ],
}

#: Methods that start a job; the fake finishes it at once.
JOB_METHODS = {"pool.scrub", "app.start", "app.stop", "app.redeploy", "app.upgrade", "vm.stop", "service.control"}
#: Calls that just succeed.
OK_METHODS = {
    "alert.dismiss", "smart.test.manual_test", "pool.snapshot.create", "pool.snapshot.delete",
    "pool.snapshot.rollback", "pool.snapshot.clone", "pool.snapshottask.run", "replication.run",
    "cloudsync.sync", "rsynctask.run", "pool.scrub.run", "pool.snapshottask.update", "replication.update",
    "cloudsync.update", "rsynctask.update", "pool.scrub.update", "smart.test.update",
    "sharing.smb.update", "sharing.nfs.update", "vm.start", "vm.poweroff", "replication.list_datasets",
    "core.unsubscribe",
}

REALTIME_FIELDS = {
    "cpu": {"cpu": {"usage": 12.5}},
    "memory": {"physical_memory_total": 34359738368, "physical_memory_available": 17179869184},
    "zfs": {"arc_size": 8589934592},
    "interfaces": {"eno1": {"received_bytes_rate": 1048576, "sent_bytes_rate": 2048}},
    "disks": {"read_bytes": 4096, "write_bytes": 8192},
}


def self_signed(tmp_path, name="localhost"):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / f"{name}.crt", tmp_path / f"{name}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    return cert_path, key_path, pinned_tls.format_fingerprint(hashlib.sha256(der).digest())


class FakeTrueNas:
    def __init__(self, tmp_path, version="25.04.2.1", api_key=API_KEY):
        self.results = copy.deepcopy(RESULTS)
        self.results["system.info"]["version"] = version
        self.api_key = api_key
        self.calls: list[tuple[str, list]] = []
        self.errors: dict[str, dict] = {}  # method -> JSON-RPC error object
        self.failed_jobs: dict[str, str] = {}  # method -> job error
        self._jobs: dict[int, dict] = {}
        self._cert, self._key, self.fingerprint = self_signed(tmp_path)
        self._server = None
        self.url = ""

    def __enter__(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self._cert, self._key)
        self._server = serve(self._handle, "127.0.0.1", 0, ssl=context, process_request=self._route)
        port = self._server.socket.getsockname()[1]
        self.url = f"https://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.02)  # let serve_forever start before a quick test shuts it down
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._thread.join(5)

    def methods_called(self):
        return [method for method, _ in self.calls]

    @staticmethod
    def _route(connection, request):
        if request.path != "/api/current":
            return connection.respond(404, "Not Found\n")
        return None

    def _handle(self, ws):
        logged_in = False
        for raw in ws:
            message = json.loads(raw)
            method, params, request_id = message["method"], message.get("params", []), message["id"]
            self.calls.append((method, params))

            def reply(result=None, error=None):
                body = {"jsonrpc": "2.0", "id": request_id}
                body["error" if error else "result"] = error or result
                ws.send(json.dumps(body))

            if method == "auth.login_with_api_key":
                logged_in = params == [self.api_key]
                reply(logged_in)
                continue
            if not logged_in:
                reply(error={"code": -32001, "message": "Not authenticated", "data": {"errname": "EACCES", "reason": "Not authenticated"}})
                continue
            if method in self.errors:
                reply(error=self.errors[method])
            elif method == "core.get_jobs":
                job_id = params[0][0][2]
                reply([self._jobs[job_id]] if job_id in self._jobs else [])
            elif method == "core.subscribe":
                reply(f"sub-{params[0]}")
                if params[0] == "reporting.realtime":
                    fields = REALTIME_FIELDS
                else:
                    fields = {"data": "line one\n"}
                ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "method": "collection_update",
                    "params": {"msg": "added", "collection": params[0], "fields": fields},
                }))
            elif method in JOB_METHODS:
                job_id = len(self._jobs) + 100
                failed = self.failed_jobs.get(method)
                self._jobs[job_id] = {
                    "id": job_id,
                    "state": "FAILED" if failed else "SUCCESS",
                    "error": failed,
                    "progress": {"percent": 100, "description": "done"},
                    "result": None,
                }
                reply(job_id)
            elif method in self.results:
                reply(self.results[method])
            elif method in OK_METHODS:
                reply(True)
            else:
                reply(error={"code": -32601, "message": "Method does not exist"})
