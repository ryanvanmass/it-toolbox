import pytest

try:
    from it_toolbox.core.rdp import freerdp_client
except OSError:  # FreeRDP3 isn't installed on this machine
    pytest.skip("FreeRDP3 libraries not installed", allow_module_level=True)


def test_linux_candidates_use_the_versioned_soname():
    assert freerdp_client._library_candidates("freerdp3", "Linux") == ["libfreerdp3.so.3"]


def test_windows_candidates_try_with_and_without_lib_prefix():
    assert freerdp_client._library_candidates("winpr3", "Windows") == ["winpr3.dll", "libwinpr3.dll"]


def test_macos_candidates_try_homebrew_paths_before_bare_names():
    candidates = freerdp_client._library_candidates("freerdp-client3", "Darwin")

    assert candidates[:2] == [
        "/opt/homebrew/lib/libfreerdp-client3.3.dylib",
        "/opt/homebrew/lib/libfreerdp-client3.dylib",
    ]
    assert "/usr/local/lib/libfreerdp-client3.3.dylib" in candidates
    assert candidates[-2:] == ["libfreerdp-client3.3.dylib", "libfreerdp-client3.dylib"]
