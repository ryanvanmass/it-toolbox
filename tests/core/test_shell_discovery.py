import os
import stat
import subprocess

from it_toolbox.core import shell_discovery


def _make_executable(path):
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# -- POSIX --------------------------------------------------------------


def test_posix_includes_existing_executable_entries_from_etc_shells(monkeypatch, tmp_path):
    bash = tmp_path / "bash"
    _make_executable(bash)

    shells_file = tmp_path / "shells"
    shells_file.write_text(f"# comment\n\n{bash}\n")

    monkeypatch.setattr(shell_discovery, "_POSIX_SHELLS_PATH", shells_file)
    monkeypatch.setattr(shell_discovery.shutil, "which", lambda name: None)

    shells = shell_discovery._discover_posix_shells()

    assert shells == [shell_discovery.Shell(name="bash", argv=(str(bash),))]


def test_posix_skips_nonexistent_and_non_executable_entries(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist"
    not_executable = tmp_path / "not-executable"
    not_executable.write_text("nope")  # no exec bit

    shells_file = tmp_path / "shells"
    shells_file.write_text(f"{missing}\n{not_executable}\n")

    monkeypatch.setattr(shell_discovery, "_POSIX_SHELLS_PATH", shells_file)
    monkeypatch.setattr(shell_discovery.shutil, "which", lambda name: None)

    assert shell_discovery._discover_posix_shells() == []


def test_posix_dedupes_by_resolved_path(monkeypatch, tmp_path):
    # A symlink pointing at the same real binary should not produce two
    # entries — exactly the /bin -> /usr/bin situation on modern distros.
    real_bash = tmp_path / "real_bash"
    _make_executable(real_bash)
    symlink = tmp_path / "bash_symlink"
    symlink.symlink_to(real_bash)

    shells_file = tmp_path / "shells"
    shells_file.write_text(f"{real_bash}\n{symlink}\n")

    monkeypatch.setattr(shell_discovery, "_POSIX_SHELLS_PATH", shells_file)
    monkeypatch.setattr(shell_discovery.shutil, "which", lambda name: None)

    shells = shell_discovery._discover_posix_shells()

    assert len(shells) == 1
    assert shells[0].argv == (str(real_bash),)


def test_posix_supplements_with_which_results_not_in_etc_shells(monkeypatch, tmp_path):
    shells_file = tmp_path / "shells"
    shells_file.write_text("")

    zsh = tmp_path / "zsh"
    _make_executable(zsh)

    monkeypatch.setattr(shell_discovery, "_POSIX_SHELLS_PATH", shells_file)
    monkeypatch.setattr(
        shell_discovery.shutil, "which", lambda name: str(zsh) if name == "zsh" else None
    )

    shells = shell_discovery._discover_posix_shells()

    assert shells == [shell_discovery.Shell(name="zsh", argv=(str(zsh),))]


def test_posix_results_sorted_by_name(monkeypatch, tmp_path):
    shells_file = tmp_path / "shells"
    shells_file.write_text("")

    paths = {}
    for name in ("zsh", "bash", "fish"):
        p = tmp_path / name
        _make_executable(p)
        paths[name] = str(p)

    monkeypatch.setattr(shell_discovery, "_POSIX_SHELLS_PATH", shells_file)
    monkeypatch.setattr(shell_discovery.shutil, "which", lambda name: paths.get(name))

    shells = shell_discovery._discover_posix_shells()

    assert [s.name for s in shells] == ["bash", "fish", "zsh"]


def test_missing_etc_shells_falls_back_to_which_only(monkeypatch, tmp_path):
    monkeypatch.setattr(shell_discovery, "_POSIX_SHELLS_PATH", tmp_path / "does-not-exist")
    bash = tmp_path / "bash"
    _make_executable(bash)
    monkeypatch.setattr(
        shell_discovery.shutil, "which", lambda name: str(bash) if name == "bash" else None
    )

    shells = shell_discovery._discover_posix_shells()

    assert shells == [shell_discovery.Shell(name="bash", argv=(str(bash),))]


# -- Windows --------------------------------------------------------------


def test_windows_always_includes_cmd_and_powershell(monkeypatch):
    monkeypatch.setattr(shell_discovery.shutil, "which", lambda name: None)

    shells = shell_discovery._discover_windows_shells()

    assert shell_discovery.Shell(name="Command Prompt", argv=("cmd.exe",)) in shells
    assert shell_discovery.Shell(name="Windows PowerShell", argv=("powershell.exe",)) in shells


def test_windows_includes_pwsh_when_found(monkeypatch):
    monkeypatch.setattr(
        shell_discovery.shutil,
        "which",
        lambda name: r"C:\Program Files\PowerShell\7\pwsh.exe" if name == "pwsh" else None,
    )

    shells = shell_discovery._discover_windows_shells()

    assert shell_discovery.Shell(
        name="PowerShell 7", argv=(r"C:\Program Files\PowerShell\7\pwsh.exe",)
    ) in shells


def test_windows_finds_git_bash_via_which(monkeypatch):
    git_bash_path = r"C:\Program Files\Git\bin\bash.exe"
    monkeypatch.setattr(
        shell_discovery.shutil, "which", lambda name: git_bash_path if name == "bash" else None
    )

    shells = shell_discovery._discover_windows_shells()

    assert shell_discovery.Shell(name="Git Bash", argv=(git_bash_path,)) in shells


def test_windows_ignores_non_git_bash_on_path(monkeypatch):
    # e.g. a WSL/MSYS bash that happens to be on PATH but isn't Git's.
    # The two hardcoded Program Files fallback paths are real Windows
    # paths that don't exist on this (non-Windows) test machine either,
    # so no monkeypatching of the filesystem check is needed here.
    monkeypatch.setattr(
        shell_discovery.shutil,
        "which",
        lambda name: r"C:\msys64\usr\bin\bash.exe" if name == "bash" else None,
    )

    shells = shell_discovery._discover_windows_shells()

    assert not any(s.name == "Git Bash" for s in shells)


def test_windows_wsl_distros_parsed_from_utf16_output(monkeypatch):
    monkeypatch.setattr(shell_discovery, "_wsl_has_registered_distros", lambda: True)
    monkeypatch.setattr(
        shell_discovery.shutil, "which", lambda name: "wsl.exe" if name == "wsl.exe" else None
    )
    fake_output = "Ubuntu\r\ndebian\r\n".encode("utf-16-le")
    fake_output = b"\xff\xfe" + fake_output  # UTF-16LE BOM, as wsl.exe actually emits

    def fake_run(cmd, capture_output, timeout):
        assert cmd == ["wsl.exe", "-l", "-q"]
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=fake_output, stderr=b"")

    monkeypatch.setattr(shell_discovery.subprocess, "run", fake_run)

    shells = shell_discovery._discover_wsl_distros()

    assert shells == [
        shell_discovery.Shell(name="WSL: Ubuntu", argv=("wsl.exe", "-d", "Ubuntu")),
        shell_discovery.Shell(name="WSL: debian", argv=("wsl.exe", "-d", "debian")),
    ]


def test_wsl_not_installed_returns_empty_list(monkeypatch):
    monkeypatch.setattr(shell_discovery, "_wsl_has_registered_distros", lambda: True)
    monkeypatch.setattr(shell_discovery.shutil, "which", lambda name: None)

    assert shell_discovery._discover_wsl_distros() == []


def test_wsl_command_failure_returns_empty_list_not_raises(monkeypatch):
    monkeypatch.setattr(shell_discovery, "_wsl_has_registered_distros", lambda: True)
    monkeypatch.setattr(shell_discovery.shutil, "which", lambda name: "wsl.exe")

    def fake_run(cmd, capture_output, timeout):
        raise OSError("no such file")

    monkeypatch.setattr(shell_discovery.subprocess, "run", fake_run)

    assert shell_discovery._discover_wsl_distros() == []


def test_wsl_nonzero_exit_returns_empty_list(monkeypatch):
    monkeypatch.setattr(shell_discovery, "_wsl_has_registered_distros", lambda: True)
    monkeypatch.setattr(shell_discovery.shutil, "which", lambda name: "wsl.exe")

    def fake_run(cmd, capture_output, timeout):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout=b"", stderr=b"error")

    monkeypatch.setattr(shell_discovery.subprocess, "run", fake_run)

    assert shell_discovery._discover_wsl_distros() == []


def test_wsl_skips_invoking_wsl_exe_entirely_when_no_distros_are_registered(monkeypatch):
    # Regression test: wsl.exe ships as a stub in System32 on modern
    # Windows even when WSL was never set up, and merely running it in
    # that state triggers Windows' "install WSL now" flow — an elevated
    # operation that pops a UAC prompt — as a side effect of what should
    # be passive shell discovery on app launch. Confirmed live on a real
    # Windows machine with no WSL configured.
    monkeypatch.setattr(shell_discovery, "_wsl_has_registered_distros", lambda: False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("wsl.exe must not be invoked when no distros are registered")

    monkeypatch.setattr(shell_discovery.shutil, "which", fail_if_called)
    monkeypatch.setattr(shell_discovery.subprocess, "run", fail_if_called)

    assert shell_discovery._discover_wsl_distros() == []


def test_wsl_has_registered_distros_is_false_without_winreg(monkeypatch):
    # This dev/CI machine is never Windows, so the real (unmocked)
    # function must take its ImportError fallback and report no distros.
    assert shell_discovery._wsl_has_registered_distros() is False


# -- Top-level dispatch ---------------------------------------------------


def test_discover_shells_dispatches_on_platform(monkeypatch):
    monkeypatch.setattr(shell_discovery.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        shell_discovery, "_discover_windows_shells", lambda: ["windows-sentinel"]
    )
    monkeypatch.setattr(shell_discovery, "_discover_posix_shells", lambda: ["posix-sentinel"])

    assert shell_discovery.discover_shells() == ["windows-sentinel"]

    monkeypatch.setattr(shell_discovery.platform, "system", lambda: "Linux")
    assert shell_discovery.discover_shells() == ["posix-sentinel"]
