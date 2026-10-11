"""Machines managed from the Cockpit module, and which of the user's
Cockpit modules each one has.

A machine is one saved SSH login. The Cockpit sidebar lists, under each
machine, a child for every manager whose module helper was found there
(ProFTPD, Hosting, Scheduler), the way Connection Manager lists a GCP
project's VMs and buckets. Detection is one SSH login plus one root shell
script that tests each helper path, so a machine with several modules
needs only one connection (and at most one set of password prompts).

The managers themselves still take their own server dataclasses (see
core/proftpd_manager, hosting_manager, scheduler_manager);
CockpitMachine.server_for() builds the right one.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from it_toolbox.core import hosting_manager as hm
from it_toolbox.core import proftpd_manager as pm
from it_toolbox.core import scheduler_manager as sm
from it_toolbox.core.remote_helper import SSH_PORT, RemoteHelperConnection, RemoteHelperError, RemoteServer

COCKPIT_PORT = 9090

PROFTPD = "proftpd"
HOSTING = "hosting"
SCHEDULER = "scheduler"
#: Sidebar order of the tools under a machine.
TOOL_IDS = (PROFTPD, HOSTING, SCHEDULER)
TOOL_NAMES = {
    PROFTPD: "ProFTPD Manager",
    HOSTING: "Hosting Manager",
    SCHEDULER: "Scheduler Manager",
}
#: Detection result for ProFTPD itself installed without any helper: the
#: ProFTPD Manager can install its bundled helper (see
#: ProftpdConnection.install_bundled_helper), so the tool is still listed.
PROFTPD_NO_HELPER = "proftpd-no-helper"


@dataclass
class CockpitMachine(RemoteServer):
    """A saved machine. `tools` is the last detection result (TOOL_IDS,
    plus PROFTPD_NO_HELPER), kept so the tree shows a machine's tools at
    startup without connecting; None until the first detection.
    proftpd_container is the cockpit-proftpd container (TrueNAS app) the
    ProFTPD Manager reaches through `docker exec`, if any."""

    proftpd_container: str | None = None
    tools: list[str] | None = field(default=None, compare=False)

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "proftpd_container": self.proftpd_container,
            "tools": self.tools,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CockpitMachine | None:
        base = RemoteServer.from_dict(data)
        if base is None:
            return None
        tools = data.get("tools")
        return cls(
            name=base.name,
            host=base.host,
            username=base.username,
            port=base.port,
            key_path=base.key_path,
            proftpd_container=data.get("proftpd_container") or None,
            tools=[str(t) for t in tools] if isinstance(tools, list) else None,
        )

    @property
    def key(self) -> tuple[str, str, int]:
        """What makes two saved entries the same machine."""
        return (self.username, self.host.lower(), self.port)

    @property
    def cockpit_url(self) -> str:
        return f"https://{self.host}:{COCKPIT_PORT}/"

    def server_for(self, tool: str):
        """The server object the given tool's manager widget takes."""
        common = dict(
            name=self.name, host=self.host, username=self.username, port=self.port, key_path=self.key_path
        )
        if tool == PROFTPD:
            return pm.ProftpdServer(**common, docker_container=self.proftpd_container)
        if tool == HOSTING:
            return hm.HostingServer(**common)
        if tool == SCHEDULER:
            return sm.SchedulerServer(**common)
        raise ValueError(f"Unknown Cockpit tool {tool!r}")


def detect_script(machine: CockpitMachine) -> str:
    """The root shell script that prints one tool id per line for each
    module helper installed on the machine."""
    proftpd_paths = (pm.COCKPIT_HELPER_PATH, pm.BUNDLED_HELPER_PATH)
    proftpd_test = " || ".join(f"[ -x {p} ]" for p in proftpd_paths)
    proftpd_installed = "command -v proftpd >/dev/null 2>&1"
    if machine.proftpd_container:
        prefix = shlex.join(["docker", "exec", machine.proftpd_container, "sh", "-c"])
        proftpd_test = f"{prefix} {shlex.quote(proftpd_test)}"
        proftpd_installed = f"{prefix} {shlex.quote(proftpd_installed)}"
    return "\n".join(
        [
            f"if {proftpd_test}; then echo {PROFTPD}; "
            f"elif {proftpd_installed}; then echo {PROFTPD_NO_HELPER}; fi",
            f"[ -x {hm.HELPER_PATH} ] && echo {HOSTING}",
            f"[ -x {sm.HELPER_PATH} ] && echo {SCHEDULER}",
            "true",
        ]
    )


def parse_detected(output: str) -> list[str]:
    found = {line.strip() for line in output.splitlines()}
    tools = [tool for tool in TOOL_IDS if tool in found]
    if PROFTPD not in found and PROFTPD_NO_HELPER in found:
        tools.append(PROFTPD_NO_HELPER)
    return tools


class MachineConnection(RemoteHelperConnection):
    """Logs in and becomes root like any manager connection, without
    looking for a particular helper; detect_tools() then checks for all
    of them in one go."""

    MODULE_NAME = "Cockpit"

    def detect_tools(self) -> list[str]:
        status, out, err = self.run(["sh", "-c", detect_script(self.server)])
        if status != 0:
            raise RemoteHelperError(f"Couldn't check {self.server.host} for Cockpit modules: {err.strip()}")
        return parse_detected(out)


def detect_tools(machine: CockpitMachine, **credentials) -> list[str]:
    """Blocking: connect, detect, disconnect. Raises the connection's
    UnknownHostKeyError / *Required errors for the caller to prompt on."""
    connection = MachineConnection(machine, **credentials)
    connection.connect()
    try:
        return connection.detect_tools()
    finally:
        connection.close()


def has_tool(machine: CockpitMachine, tool: str) -> bool:
    tools = machine.tools or []
    return tool in tools or (tool == PROFTPD and PROFTPD_NO_HELPER in tools)


def migrate_tool_servers(proftpd: list[dict], hosting: list[dict], scheduler: list[dict]) -> list[CockpitMachine]:
    """Merges the managers' old per-tool server lists into machines, one
    per user@host:port. Each machine starts out listing the tools it was
    saved under, until its first detection says otherwise."""
    machines: dict[tuple, CockpitMachine] = {}
    for tool, entries in ((PROFTPD, proftpd), (HOSTING, hosting), (SCHEDULER, scheduler)):
        for data in entries:
            server = RemoteServer.from_dict(data)
            if server is None:
                continue
            machine = CockpitMachine(
                name=server.name,
                host=server.host,
                username=server.username,
                port=server.port or SSH_PORT,
                key_path=server.key_path,
                tools=[],
            )
            machine = machines.setdefault(machine.key, machine)
            machine.key_path = machine.key_path or server.key_path
            if tool == PROFTPD:
                machine.proftpd_container = machine.proftpd_container or data.get("docker_container") or None
            if tool not in machine.tools:
                machine.tools.append(tool)
    for machine in machines.values():
        machine.tools.sort(key=TOOL_IDS.index)
    return list(machines.values())
