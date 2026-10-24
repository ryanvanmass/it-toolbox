import ctypes

import pytest

try:
    from it_toolbox.core.rdp import freerdp_client
except OSError:  # FreeRDP3 isn't installed on this machine
    pytest.skip("FreeRDP3 libraries not installed", allow_module_level=True)


def test_pubsub_subscribe_leaves_the_handler_variadic():
    # PubSub_Subscribe(pubSub, EventName, ...): the handler must stay out of
    # argtypes so ctypes passes it the variadic way. On Apple Silicon that
    # means on the stack, and typing it as a fixed argument crashed RDP
    # connects there (issue #115).
    assert len(freerdp_client._winpr_lib.PubSub_Subscribe.argtypes) == 2


def test_libraries_are_loaded_cdecl_so_variadic_calls_are_allowed():
    # WinDLL marks every function stdcall, and ctypes then rejects calls
    # with more arguments than argtypes, so the variadic PubSub_Subscribe
    # above failed every Windows connect with "this function takes 2
    # arguments (3 given)". FreeRDP exports are cdecl on every platform.
    for lib in (freerdp_client._core_lib, freerdp_client._client_lib, freerdp_client._winpr_lib):
        assert type(lib) is ctypes.CDLL
