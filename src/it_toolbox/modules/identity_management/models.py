from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    """A JumpCloud-managed device (their term is "system"). List responses
    only populate the first few fields; os_version/serial_number/
    agent_version are backfilled by a get_device() detail call.
    """

    id: str
    display_name: str
    os: str
    hostname: str = ""
    os_version: str = ""
    serial_number: str = ""
    agent_version: str = ""
    last_contact: str = ""
    active: bool = True


@dataclass(frozen=True)
class User:
    id: str
    username: str
    email: str
    first_name: str = ""
    last_name: str = ""
    suspended: bool = False
