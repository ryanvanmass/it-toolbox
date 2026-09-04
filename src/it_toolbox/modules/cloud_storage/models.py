from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteConfig:
    """One remote already registered in rclone's own config file."""

    name: str
    type: str


@dataclass(frozen=True)
class ProviderOption:
    """One configurable field for a provider (backend) type, or the single
    question carried by a ConfigStep — same shape either way, since both
    come from the same rclone JSON option schema.
    """

    name: str
    help: str
    type: str  # rclone's declared type: "string", "bool", "int", etc.
    default: str
    required: bool
    is_password: bool
    advanced: bool
    exclusive: bool
    examples: tuple[tuple[str, str], ...] = ()  # (value, help) pairs


@dataclass(frozen=True)
class Provider:
    """One rclone backend type (s3, sftp, drive, local, ...) and its full
    set of configurable fields, as reported by `rclone config providers`.
    """

    name: str
    description: str
    options: tuple[ProviderOption, ...]


@dataclass(frozen=True)
class ConfigStep:
    """One step in rclone's non-interactive `config create`/`config update
    --continue` protocol. Most backends finish (done=True) after a single
    create call with all known fields supplied upfront; backends with
    extra interactive logic (OAuth token backends, mainly) instead return
    one more question (`option`) to answer via continue_config_step,
    possibly several times in a row before finishing.
    """

    done: bool
    state: str = ""
    option: ProviderOption | None = None


@dataclass(frozen=True)
class RcloneEntry:
    """One row in an `rclone lsjson` directory listing."""

    name: str
    path: str  # full path relative to the remote's root
    is_dir: bool
    size: int = 0
    modified: str = ""
