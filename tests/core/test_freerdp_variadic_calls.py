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
