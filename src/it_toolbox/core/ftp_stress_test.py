"""Load generator behind the FTP Server Test tool (General Tools): the
SFTP Server Test's engine (core/sftp_stress_test.py -- workers, random
operations, integrity checks, stats, cleanup) driven over FTP, or explicit
FTPS, through ftp_client.FtpSession instead of SFTP.
"""

from __future__ import annotations

import ftplib
import ssl
from dataclasses import dataclass

from it_toolbox.core.ftp_client import FtpClientError, FtpSession
from it_toolbox.core.sftp_stress_test import StressTest


@dataclass(frozen=True)
class FtpStressTestConfig:
    host: str
    port: int = 21
    username: str = ""
    password: str | None = None
    use_tls: bool = False  # explicit FTPS (AUTH TLS) for control and data
    workers: int = 4
    min_file_size: int = 1024
    max_file_size: int = 1024 * 1024
    remote_dir: str = ""  # "" = the login's starting directory
    cleanup: bool = True

    def session(self) -> FtpSession:
        return FtpSession(self.host, self.port, self.username, password=self.password or "", use_tls=self.use_tls)


def is_ftp_connection_lost(exc: Exception) -> bool:
    """FtpSession wraps every ftplib failure in FtpClientError; what it
    wraps says whether the control connection is still usable. 4xx/5xx
    replies to a command (no such file, permission denied, disk full)
    leave it usable -- except 421, the server closing the connection,
    and 530, the server no longer treating it as logged in.
    Socket/TLS errors, EOF and garbled replies don't."""
    cause = exc.__cause__ if isinstance(exc, FtpClientError) else exc
    if cause is None:
        return False
    if isinstance(cause, (ftplib.error_perm, ftplib.error_temp)):
        return str(cause)[:3] in ("421", "530")
    return isinstance(cause, (ftplib.error_reply, ftplib.error_proto, EOFError, OSError, ssl.SSLError))


class FtpStressTest(StressTest):
    folder_prefix = "it-toolbox-ftp-test"
    thread_prefix = "ftp-test-worker"
    is_connection_lost = staticmethod(is_ftp_connection_lost)
