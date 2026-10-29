import ctypes

import pytest

try:
    from it_toolbox.core.rdp import freerdp_client
except OSError:  # FreeRDP3 isn't installed on this machine
    pytest.skip("FreeRDP3 libraries not installed", allow_module_level=True)


@pytest.fixture(autouse=True)
def _fresh_probe(monkeypatch):
    monkeypatch.setattr(freerdp_client, "_h264_decoder", None)


class _FakeSettingsLib:
    """Records freerdp_settings_set_bool calls by setting name."""

    def __init__(self, real):
        self._real = real
        self.enabled = set()
        self._names = {}

    def __getattr__(self, name):
        return getattr(self._real, name)

    def freerdp_settings_set_bool(self, settings, key, value):
        self.enabled.add(self._names[key])
        return 1


def _configure(monkeypatch, graphics_pipeline, h264, decoder):
    fake = _FakeSettingsLib(freerdp_client._core_lib)
    real_lookup = freerdp_client._settings_key_for_name

    def lookup(name):
        key = real_lookup(name)
        fake._names[key] = name
        return key

    monkeypatch.setattr(freerdp_client, "_core_lib", fake)
    monkeypatch.setattr(freerdp_client, "_settings_key_for_name", lookup)
    monkeypatch.setattr(freerdp_client, "h264_decoder", lambda: decoder)
    freerdp_client._configure_performance(None, graphics_pipeline, h264)
    return fake.enabled


_REAL_LIB = freerdp_client._core_lib
_WORKS = freerdp_client.H264Decoder(True, False, "decoding works")
_BROKEN = freerdp_client.H264Decoder(False, False, "this FreeRDP build has no H.264 decoder")
_H264_KEYS = {"FreeRDP_GfxH264", "FreeRDP_GfxAVC444", "FreeRDP_GfxAVC444v2"}


def test_h264_is_offered_only_with_the_pipeline_and_a_working_decoder(monkeypatch):
    assert _H264_KEYS <= _configure(monkeypatch, True, True, _WORKS)
    assert not _H264_KEYS & _configure(monkeypatch, True, True, _BROKEN)
    assert not _H264_KEYS & _configure(monkeypatch, True, False, _WORKS)
    assert _configure(monkeypatch, False, True, _WORKS) == set()


def test_probe_reports_a_build_without_a_decoder(monkeypatch):
    class _NoDecoder:
        def __getattr__(self, name):
            return getattr(_REAL_LIB, name)

        def h264_context_new(self, compressor):
            return None

    monkeypatch.setattr(freerdp_client, "_core_lib", _NoDecoder())

    decoder = freerdp_client.h264_decoder()

    assert not decoder.works and "no H.264 decoder" in decoder.detail


def test_probe_rejects_a_decoder_that_produces_the_wrong_picture(monkeypatch):
    class _GreyDecoder:
        def __getattr__(self, name):
            return getattr(_REAL_LIB, name)

        def avc420_decompress(self, context, data, size, pixels, fmt, stride, w, h, rects, n):
            ctypes.memset(pixels, 0x80, stride * h)
            return 1

    monkeypatch.setattr(freerdp_client, "_core_lib", _GreyDecoder())

    decoder = freerdp_client.h264_decoder()

    assert not decoder.works and "wrong picture" in decoder.detail
