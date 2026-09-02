# -*- coding: utf-8 -*-
#
# AUTO-GENERATED — do not hand-edit. Regenerate with:
#   python scripts/generate_freerdp_bindings.py (see that file's docstring
#   for one-time setup). Generated from FreeRDP3's freerdp/freerdp.h and
#   freerdp/client.h against a matching libwinpr3-devel install, targeting
#   an x86_64 Linux ABI (WORD_SIZE=8, POINTER_SIZE=8, LONGDOUBLE_SIZE=16).
#
import ctypes


class AsDictMixin:
    @classmethod
    def as_dict(cls, self):
        result = {}
        if not isinstance(self, AsDictMixin):
            # not a structure, assume it's already a python object
            return self
        if not hasattr(cls, "_fields_"):
            return result
        # sys.version_info >= (3, 5)
        # for (field, *_) in cls._fields_:  # noqa
        for field_tuple in cls._fields_:  # noqa
            field = field_tuple[0]
            if field.startswith('PADDING_'):
                continue
            value = getattr(self, field)
            type_ = type(value)
            if hasattr(value, "_length_") and hasattr(value, "_type_"):
                # array
                type_ = type_._type_
                if hasattr(type_, 'as_dict'):
                    value = [type_.as_dict(v) for v in value]
                else:
                    value = [i for i in value]
            elif hasattr(value, "contents") and hasattr(value, "_type_"):
                # pointer
                try:
                    if not hasattr(type_, "as_dict"):
                        value = value.contents
                    else:
                        type_ = type_._type_
                        value = type_.as_dict(value.contents)
                except ValueError:
                    # nullptr
                    value = None
            elif isinstance(value, AsDictMixin):
                # other structure
                value = type_.as_dict(value)
            result[field] = value
        return result


class Structure(ctypes.Structure, AsDictMixin):

    def __init__(self, *args, **kwds):
        # We don't want to use positional arguments fill PADDING_* fields

        args = dict(zip(self.__class__._field_names_(), args))
        args.update(kwds)
        super(Structure, self).__init__(**args)

    @classmethod
    def _field_names_(cls):
        if hasattr(cls, '_fields_'):
            return (f[0] for f in cls._fields_ if not f[0].startswith('PADDING'))
        else:
            return ()

    @classmethod
    def get_type(cls, field):
        for f in cls._fields_:
            if f[0] == field:
                return f[1]
        return None

    @classmethod
    def bind(cls, bound_fields):
        fields = {}
        for name, type_ in cls._fields_:
            if hasattr(type_, "restype"):
                if name in bound_fields:
                    if bound_fields[name] is None:
                        fields[name] = type_()
                    else:
                        # use a closure to capture the callback from the loop scope
                        fields[name] = (
                            type_((lambda callback: lambda *args: callback(*args))(
                                bound_fields[name]))
                        )
                    del bound_fields[name]
                else:
                    # default callback implementation (does nothing)
                    try:
                        default_ = type_(0).restype().value
                    except TypeError:
                        default_ = None
                    fields[name] = type_((
                        lambda default_: lambda *args: default_)(default_))
            else:
                # not a callback function, use default initialization
                if name in bound_fields:
                    fields[name] = bound_fields[name]
                    del bound_fields[name]
                else:
                    fields[name] = type_()
        if len(bound_fields) != 0:
            raise ValueError(
                "Cannot bind the following unknown callback(s) {}.{}".format(
                    cls.__name__, bound_fields.keys()
            ))
        return cls(**fields)


class Union(ctypes.Union, AsDictMixin):
    pass



c_int128 = ctypes.c_ubyte*16
c_uint128 = c_int128
void = None
if ctypes.sizeof(ctypes.c_longdouble) == 16:
    c_long_double_t = ctypes.c_longdouble
else:
    c_long_double_t = ctypes.c_ubyte*16

def string_cast(char_pointer, encoding='utf-8', errors='strict'):
    value = ctypes.cast(char_pointer, ctypes.c_char_p).value
    if value is not None and encoding is not None:
        value = value.decode(encoding, errors=errors)
    return value


def char_pointer_cast(string, encoding='utf-8'):
    if encoding is not None:
        try:
            string = string.encode(encoding)
        except AttributeError:
            # In Python3, bytes has no encode attribute
            pass
    string = ctypes.c_char_p(string)
    return ctypes.cast(string, ctypes.POINTER(ctypes.c_char))



class FunctionFactoryStub:
    def __getattr__(self, _):
      return ctypes.CFUNCTYPE(lambda y:y)

# libraries['FIXME_STUB'] explanation
# As you did not list (-l libraryname.so) a library that exports this function
# This is a non-working stub instead. 
# You can either re-run clan2py with -l /path/to/library.so
# Or manually fix this by comment the ctypes.CDLL loading
_libraries = {}
_libraries['FIXME_STUB'] = FunctionFactoryStub() #  ctypes.CDLL('FIXME_STUB')


class struct_rdp_rdp(Structure):
    pass

rdpRdp = struct_rdp_rdp
class struct_rdp_rail(Structure):
    pass

rdpRail = struct_rdp_rail
class struct_rdp_cache(Structure):
    pass

rdpCache = struct_rdp_cache
class struct_rdp_client_context(Structure):
    pass

class struct_ainput_client_context(Structure):
    pass

class struct_s_rdpei_client_context(Structure):
    pass

class struct_s_encomsp_client_context(Structure):
    pass

class struct_MIBClientWrapper(Structure):
    pass

class struct_rdp_context(Structure):
    pass

class struct_rdp_freerdp(Structure):
    pass

class struct_rdp_freerdp_peer(Structure):
    pass

class struct_s_wPubSub(Structure):
    pass

class struct_rdp_gdi(Structure):
    pass

class struct_rdp_channels(Structure):
    pass

class struct_rdp_graphics(Structure):
    pass

class struct_rdp_input(Structure):
    pass

class struct_rdp_update(Structure):
    pass

class struct_rdp_settings(Structure):
    pass

class struct_rdp_metrics(Structure):
    pass

class struct_rdp_codecs(Structure):
    pass

class struct_rdp_autodetect(Structure):
    pass

class struct_stream_dump_context(Structure):
    pass

class struct_s_wLog(Structure):
    pass

struct_rdp_context._pack_ = 1 # source:False
struct_rdp_context._fields_ = [
    ('instance', ctypes.POINTER(struct_rdp_freerdp)),
    ('peer', ctypes.POINTER(struct_rdp_freerdp_peer)),
    ('ServerMode', ctypes.c_int32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('LastError', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('paddingA', ctypes.c_uint64 * 12),
    ('argc', ctypes.c_int32),
    ('PADDING_2', ctypes.c_ubyte * 4),
    ('argv', ctypes.POINTER(ctypes.POINTER(ctypes.c_char))),
    ('pubSub', ctypes.POINTER(struct_s_wPubSub)),
    ('channelErrorEvent', ctypes.POINTER(None)),
    ('channelErrorNum', ctypes.c_uint32),
    ('PADDING_3', ctypes.c_ubyte * 4),
    ('errorDescription', ctypes.POINTER(ctypes.c_char)),
    ('paddingB', ctypes.c_uint64 * 10),
    ('rdp', ctypes.POINTER(struct_rdp_rdp)),
    ('gdi', ctypes.POINTER(struct_rdp_gdi)),
    ('rail', ctypes.POINTER(struct_rdp_rail)),
    ('cache', ctypes.POINTER(struct_rdp_cache)),
    ('channels', ctypes.POINTER(struct_rdp_channels)),
    ('graphics', ctypes.POINTER(struct_rdp_graphics)),
    ('input', ctypes.POINTER(struct_rdp_input)),
    ('update', ctypes.POINTER(struct_rdp_update)),
    ('settings', ctypes.POINTER(struct_rdp_settings)),
    ('metrics', ctypes.POINTER(struct_rdp_metrics)),
    ('codecs', ctypes.POINTER(struct_rdp_codecs)),
    ('autodetect', ctypes.POINTER(struct_rdp_autodetect)),
    ('paddingC1', ctypes.c_uint64 * 1),
    ('disconnectUltimatum', ctypes.c_int32),
    ('PADDING_4', ctypes.c_ubyte * 4),
    ('paddingC', ctypes.c_uint64 * 18),
    ('dump', ctypes.POINTER(struct_stream_dump_context)),
    ('log', ctypes.POINTER(struct_s_wLog)),
    ('paddingD', ctypes.c_uint64 * 30),
    ('paddingE', ctypes.c_uint64 * 32),
]

class struct_FreeRDP_TouchContact(Structure):
    pass

struct_FreeRDP_TouchContact._pack_ = 1 # source:False
struct_FreeRDP_TouchContact._fields_ = [
    ('id', ctypes.c_int32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('count', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('x', ctypes.c_int32),
    ('PADDING_2', ctypes.c_ubyte * 4),
    ('y', ctypes.c_int32),
    ('PADDING_3', ctypes.c_ubyte * 4),
    ('flags', ctypes.c_uint32),
    ('PADDING_4', ctypes.c_ubyte * 4),
    ('pressure', ctypes.c_uint32),
    ('PADDING_5', ctypes.c_ubyte * 4),
]

class struct_pen_device(Structure):
    pass

struct_pen_device._pack_ = 1 # source:False
struct_pen_device._fields_ = [
    ('deviceid', ctypes.c_int32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('flags', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('max_pressure', ctypes.c_double),
    ('hovering', ctypes.c_int32),
    ('PADDING_2', ctypes.c_ubyte * 4),
    ('pressed', ctypes.c_int32),
    ('PADDING_3', ctypes.c_ubyte * 4),
    ('last_x', ctypes.c_int32),
    ('PADDING_4', ctypes.c_ubyte * 4),
    ('last_y', ctypes.c_int32),
    ('PADDING_5', ctypes.c_ubyte * 4),
]

struct_rdp_client_context._pack_ = 1 # source:False
struct_rdp_client_context._fields_ = [
    ('context', struct_rdp_context),
    ('thread', ctypes.POINTER(None)),
    ('ainput', ctypes.POINTER(struct_ainput_client_context)),
    ('rdpei', ctypes.POINTER(struct_s_rdpei_client_context)),
    ('lastX', ctypes.c_int32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('lastY', ctypes.c_int32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('mouse_grabbed', ctypes.c_int32),
    ('PADDING_2', ctypes.c_ubyte * 4),
    ('encomsp', ctypes.POINTER(struct_s_encomsp_client_context)),
    ('controlToggle', ctypes.c_int32),
    ('PADDING_3', ctypes.c_ubyte * 4),
    ('contacts', struct_FreeRDP_TouchContact * 10),
    ('pens', struct_pen_device * 10),
    ('mibClientWrapper', ctypes.POINTER(struct_MIBClientWrapper)),
    ('pressed_buttons', ctypes.c_int32 * 5),
    ('PADDING_4', ctypes.c_ubyte * 4),
    ('reserved', ctypes.c_uint64 * 113),
]

rdpClientContext = struct_rdp_client_context
class struct_rdp_client_entry_points_v1(Structure):
    pass

struct_rdp_client_entry_points_v1._pack_ = 1 # source:False
struct_rdp_client_entry_points_v1._fields_ = [
    ('Size', ctypes.c_uint32),
    ('Version', ctypes.c_uint32),
    ('settings', ctypes.POINTER(struct_rdp_settings)),
    ('GlobalInit', ctypes.CFUNCTYPE(ctypes.c_int32)),
    ('GlobalUninit', ctypes.CFUNCTYPE(None)),
    ('ContextSize', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('ClientNew', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(struct_rdp_context))),
    ('ClientFree', ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(struct_rdp_context))),
    ('ClientStart', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context))),
    ('ClientStop', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context))),
]

RDP_CLIENT_ENTRY_POINTS_V1 = struct_rdp_client_entry_points_v1
RDP_CLIENT_ENTRY_POINTS = struct_rdp_client_entry_points_v1

# values for enumeration 'rdp_auth_reason'
rdp_auth_reason__enumvalues = {
    0: 'AUTH_NLA',
    1: 'AUTH_TLS',
    2: 'AUTH_RDP',
    3: 'GW_AUTH_HTTP',
    4: 'GW_AUTH_RDG',
    5: 'GW_AUTH_RPC',
    6: 'AUTH_SMARTCARD_PIN',
    7: 'AUTH_RDSTLS',
    8: 'AUTH_FIDO_PIN',
}
AUTH_NLA = 0
AUTH_TLS = 1
AUTH_RDP = 2
GW_AUTH_HTTP = 3
GW_AUTH_RDG = 4
GW_AUTH_RPC = 5
AUTH_SMARTCARD_PIN = 6
AUTH_RDSTLS = 7
AUTH_FIDO_PIN = 8
rdp_auth_reason = ctypes.c_uint32 # enum
class struct_rdp_heartbeat(Structure):
    pass

class struct_SmartcardCertInfo_st(Structure):
    pass


# values for enumeration 'AccessTokenType'
AccessTokenType__enumvalues = {
    0: 'ACCESS_TOKEN_TYPE_AAD',
    1: 'ACCESS_TOKEN_TYPE_AVD',
}
ACCESS_TOKEN_TYPE_AAD = 0
ACCESS_TOKEN_TYPE_AVD = 1
AccessTokenType = ctypes.c_uint32 # enum
struct_rdp_freerdp._pack_ = 1 # source:False
struct_rdp_freerdp._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('pClientEntryPoints', ctypes.POINTER(struct_rdp_client_entry_points_v1)),
    ('paddingA', ctypes.c_uint64 * 14),
    ('paddingX', ctypes.c_uint64 * 4),
    ('heartbeat', ctypes.POINTER(struct_rdp_heartbeat)),
    ('paddingB', ctypes.c_uint64 * 11),
    ('ContextSize', ctypes.c_uint64),
    ('ContextNew', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(struct_rdp_context))),
    ('ContextFree', ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(struct_rdp_context))),
    ('paddingC', ctypes.c_uint64 * 12),
    ('ConnectionCallbackState', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('PreConnect', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp))),
    ('PostConnect', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp))),
    ('Authenticate', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)))),
    ('VerifyCertificate', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.c_int32)),
    ('VerifyChangedCertificate', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char))),
    ('VerifyX509Certificate', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint64, ctypes.POINTER(ctypes.c_char), ctypes.c_uint16, ctypes.c_uint32)),
    ('LogonErrorInfo', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_uint32, ctypes.c_uint32)),
    ('PostDisconnect', ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_rdp_freerdp))),
    ('GatewayAuthenticate', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)))),
    ('PresentGatewayMessage', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint16))),
    ('Redirect', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp))),
    ('LoadChannels', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp))),
    ('PostFinalDisconnect', ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_rdp_freerdp))),
    ('paddingD', ctypes.c_uint64 * 3),
    ('SendChannelData', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_uint16, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint64)),
    ('ReceiveChannelData', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_uint16, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint64)),
    ('VerifyCertificateEx', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.c_uint16, ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.c_uint32)),
    ('VerifyChangedCertificateEx', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.c_uint16, ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.c_uint32)),
    ('SendChannelPacket', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_uint16, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint64)),
    ('AuthenticateEx', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), rdp_auth_reason)),
    ('ChooseSmartcard', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.POINTER(struct_SmartcardCertInfo_st)), ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int32)),
    ('GetAccessToken', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), AccessTokenType, ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.c_uint64)),
    ('RetryDialog', ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.c_uint64, ctypes.POINTER(None))),
    ('paddingE', ctypes.c_uint64 * 7),
]

class struct_GDI_DC(Structure):
    pass

class struct_gdi_bitmap(Structure):
    pass

class struct_s_rdpgfx_client_context(Structure):
    pass

class struct_s_VideoClientContext(Structure):
    pass

class struct_s_geometry_client_context(Structure):
    pass

class struct_gdi_palette(Structure):
    pass

struct_gdi_palette._pack_ = 1 # source:False
struct_gdi_palette._fields_ = [
    ('format', ctypes.c_uint32),
    ('palette', ctypes.c_uint32 * 256),
]

struct_rdp_gdi._pack_ = 1 # source:False
struct_rdp_gdi._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('width', ctypes.c_int32),
    ('height', ctypes.c_int32),
    ('stride', ctypes.c_uint32),
    ('dstFormat', ctypes.c_uint32),
    ('cursor_x', ctypes.c_uint32),
    ('cursor_y', ctypes.c_uint32),
    ('hdc', ctypes.POINTER(struct_GDI_DC)),
    ('primary', ctypes.POINTER(struct_gdi_bitmap)),
    ('drawing', ctypes.POINTER(struct_gdi_bitmap)),
    ('bitmap_size', ctypes.c_uint32),
    ('bitmap_stride', ctypes.c_uint32),
    ('primary_buffer', ctypes.POINTER(ctypes.c_ubyte)),
    ('palette', struct_gdi_palette),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('image', ctypes.POINTER(struct_gdi_bitmap)),
    ('free', ctypes.CFUNCTYPE(None, ctypes.POINTER(None))),
    ('inGfxFrame', ctypes.c_int32),
    ('graphicsReset', ctypes.c_int32),
    ('suppressOutput', ctypes.c_int32),
    ('outputSurfaceId', ctypes.c_uint16),
    ('PADDING_1', ctypes.c_ubyte * 2),
    ('frameId', ctypes.c_uint32),
    ('PADDING_2', ctypes.c_ubyte * 4),
    ('gfx', ctypes.POINTER(struct_s_rdpgfx_client_context)),
    ('video', ctypes.POINTER(struct_s_VideoClientContext)),
    ('geometry', ctypes.POINTER(struct_s_geometry_client_context)),
    ('log', ctypes.POINTER(struct_s_wLog)),
]

class struct_GDIOBJECT(Structure):
    pass

class struct_GDI_BRUSH(Structure):
    pass

class struct_GDI_RGN(Structure):
    pass

class struct_GDI_PEN(Structure):
    pass

class struct_GDI_WND(Structure):
    pass

struct_GDI_DC._pack_ = 1 # source:False
struct_GDI_DC._fields_ = [
    ('selectedObject', ctypes.POINTER(struct_GDIOBJECT)),
    ('format', ctypes.c_uint32),
    ('bkColor', ctypes.c_uint32),
    ('textColor', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('brush', ctypes.POINTER(struct_GDI_BRUSH)),
    ('clip', ctypes.POINTER(struct_GDI_RGN)),
    ('pen', ctypes.POINTER(struct_GDI_PEN)),
    ('hwnd', ctypes.POINTER(struct_GDI_WND)),
    ('drawMode', ctypes.c_int32),
    ('bkMode', ctypes.c_int32),
]

struct_GDIOBJECT._pack_ = 1 # source:False
struct_GDIOBJECT._fields_ = [
    ('objectType', ctypes.c_ubyte),
]

class struct_GDI_BITMAP(Structure):
    pass

struct_GDI_BRUSH._pack_ = 1 # source:False
struct_GDI_BRUSH._fields_ = [
    ('objectType', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte * 3),
    ('style', ctypes.c_int32),
    ('pattern', ctypes.POINTER(struct_GDI_BITMAP)),
    ('color', ctypes.c_uint32),
    ('nXOrg', ctypes.c_int32),
    ('nYOrg', ctypes.c_int32),
    ('PADDING_1', ctypes.c_ubyte * 4),
]

struct_GDI_BITMAP._pack_ = 1 # source:False
struct_GDI_BITMAP._fields_ = [
    ('objectType', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte * 3),
    ('format', ctypes.c_uint32),
    ('width', ctypes.c_int32),
    ('height', ctypes.c_int32),
    ('scanline', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('data', ctypes.POINTER(ctypes.c_ubyte)),
    ('free', ctypes.CFUNCTYPE(None, ctypes.POINTER(None))),
]

struct_GDI_RGN._pack_ = 1 # source:False
struct_GDI_RGN._fields_ = [
    ('objectType', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte * 3),
    ('x', ctypes.c_int32),
    ('y', ctypes.c_int32),
    ('w', ctypes.c_int32),
    ('h', ctypes.c_int32),
    ('null', ctypes.c_int32),
]

struct_GDI_PEN._pack_ = 1 # source:False
struct_GDI_PEN._fields_ = [
    ('objectType', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte * 3),
    ('style', ctypes.c_uint32),
    ('width', ctypes.c_int32),
    ('posX', ctypes.c_int32),
    ('posY', ctypes.c_int32),
    ('color', ctypes.c_uint32),
    ('format', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('palette', ctypes.POINTER(struct_gdi_palette)),
]

struct_GDI_WND._pack_ = 1 # source:False
struct_GDI_WND._fields_ = [
    ('count', ctypes.c_uint32),
    ('ninvalid', ctypes.c_int32),
    ('invalid', ctypes.POINTER(struct_GDI_RGN)),
    ('cinvalid', ctypes.POINTER(struct_GDI_RGN)),
]

class struct_rdp_bitmap(Structure):
    pass

struct_rdp_bitmap._pack_ = 1 # source:False
struct_rdp_bitmap._fields_ = [
    ('size', ctypes.c_uint64),
    ('New', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_bitmap))),
    ('Free', ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_bitmap))),
    ('Paint', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_bitmap))),
    ('Decompress', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_bitmap), ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32)),
    ('SetSurface', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_bitmap), ctypes.c_int32)),
    ('paddingA', ctypes.c_uint32 * 10),
    ('left', ctypes.c_uint32),
    ('top', ctypes.c_uint32),
    ('right', ctypes.c_uint32),
    ('bottom', ctypes.c_uint32),
    ('width', ctypes.c_uint32),
    ('height', ctypes.c_uint32),
    ('format', ctypes.c_uint32),
    ('flags', ctypes.c_uint32),
    ('length', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('data', ctypes.POINTER(ctypes.c_ubyte)),
    ('key64', ctypes.c_uint64),
    ('paddingB', ctypes.c_uint32 * 5),
    ('compressed', ctypes.c_int32),
    ('ephemeral', ctypes.c_int32),
    ('paddingC', ctypes.c_uint32 * 30),
    ('PADDING_1', ctypes.c_ubyte * 4),
]

struct_gdi_bitmap._pack_ = 1 # source:False
struct_gdi_bitmap._fields_ = [
    ('_p', struct_rdp_bitmap),
    ('hdc', ctypes.POINTER(struct_GDI_DC)),
    ('bitmap', ctypes.POINTER(struct_GDI_BITMAP)),
    ('org_bitmap', ctypes.POINTER(struct_GDI_BITMAP)),
]

class struct_RDPGFX_RESET_GRAPHICS_PDU(Structure):
    pass

class struct_RDPGFX_START_FRAME_PDU(Structure):
    pass

class struct_RDPGFX_END_FRAME_PDU(Structure):
    pass

class struct_RDPGFX_SURFACE_COMMAND(Structure):
    pass

class struct_RDPGFX_DELETE_ENCODING_CONTEXT_PDU(Structure):
    pass

class struct_RDPGFX_CREATE_SURFACE_PDU(Structure):
    pass

class struct_RDPGFX_DELETE_SURFACE_PDU(Structure):
    pass

class struct_RDPGFX_SOLID_FILL_PDU(Structure):
    pass

class struct_RDPGFX_SURFACE_TO_SURFACE_PDU(Structure):
    pass

class struct_RDPGFX_SURFACE_TO_CACHE_PDU(Structure):
    pass

class struct_RDPGFX_CACHE_TO_SURFACE_PDU(Structure):
    pass

class struct_RDPGFX_CACHE_IMPORT_OFFER_PDU(Structure):
    pass

class struct_RDPGFX_CACHE_IMPORT_REPLY_PDU(Structure):
    pass

class struct_PERSISTENT_CACHE_ENTRY(Structure):
    pass

class struct_RDPGFX_EVICT_CACHE_ENTRY_PDU(Structure):
    pass

class struct_RDPGFX_MAP_SURFACE_TO_OUTPUT_PDU(Structure):
    pass

class struct_RDPGFX_MAP_SURFACE_TO_SCALED_OUTPUT_PDU(Structure):
    pass

class struct_RDPGFX_MAP_SURFACE_TO_WINDOW_PDU(Structure):
    pass

class struct_RDPGFX_MAP_SURFACE_TO_SCALED_WINDOW_PDU(Structure):
    pass

class struct_RDPGFX_CAPS_ADVERTISE_PDU(Structure):
    pass

class struct_RDPGFX_CAPS_CONFIRM_PDU(Structure):
    pass

class struct_RDPGFX_FRAME_ACKNOWLEDGE_PDU(Structure):
    pass

class struct_RDPGFX_QOE_FRAME_ACKNOWLEDGE_PDU(Structure):
    pass

class struct_RECTANGLE_16(Structure):
    pass

class struct_gdi_gfx_surface(Structure):
    pass

class struct_RTL_CRITICAL_SECTION(Structure):
    pass

struct_RTL_CRITICAL_SECTION._pack_ = 1 # source:False
struct_RTL_CRITICAL_SECTION._fields_ = [
    ('DebugInfo', ctypes.POINTER(None)),
    ('LockCount', ctypes.c_int32),
    ('RecursionCount', ctypes.c_int32),
    ('OwningThread', ctypes.POINTER(None)),
    ('LockSemaphore', ctypes.POINTER(None)),
    ('SpinCount', ctypes.c_uint64),
]

struct_s_rdpgfx_client_context._pack_ = 1 # source:False
struct_s_rdpgfx_client_context._fields_ = [
    ('handle', ctypes.POINTER(None)),
    ('custom', ctypes.POINTER(None)),
    ('ResetGraphics', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_RESET_GRAPHICS_PDU))),
    ('StartFrame', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_START_FRAME_PDU))),
    ('EndFrame', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_END_FRAME_PDU))),
    ('SurfaceCommand', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_SURFACE_COMMAND))),
    ('DeleteEncodingContext', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_DELETE_ENCODING_CONTEXT_PDU))),
    ('CreateSurface', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_CREATE_SURFACE_PDU))),
    ('DeleteSurface', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_DELETE_SURFACE_PDU))),
    ('SolidFill', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_SOLID_FILL_PDU))),
    ('SurfaceToSurface', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_SURFACE_TO_SURFACE_PDU))),
    ('SurfaceToCache', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_SURFACE_TO_CACHE_PDU))),
    ('CacheToSurface', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_CACHE_TO_SURFACE_PDU))),
    ('CacheImportOffer', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_CACHE_IMPORT_OFFER_PDU))),
    ('CacheImportReply', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_CACHE_IMPORT_REPLY_PDU))),
    ('ImportCacheEntry', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.c_uint16, ctypes.POINTER(struct_PERSISTENT_CACHE_ENTRY))),
    ('ExportCacheEntry', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.c_uint16, ctypes.POINTER(struct_PERSISTENT_CACHE_ENTRY))),
    ('EvictCacheEntry', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_EVICT_CACHE_ENTRY_PDU))),
    ('MapSurfaceToOutput', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_MAP_SURFACE_TO_OUTPUT_PDU))),
    ('MapSurfaceToScaledOutput', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_MAP_SURFACE_TO_SCALED_OUTPUT_PDU))),
    ('MapSurfaceToWindow', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_MAP_SURFACE_TO_WINDOW_PDU))),
    ('MapSurfaceToScaledWindow', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_MAP_SURFACE_TO_SCALED_WINDOW_PDU))),
    ('GetSurfaceIds', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(ctypes.POINTER(ctypes.c_uint16)), ctypes.POINTER(ctypes.c_uint16))),
    ('SetSurfaceData', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.c_uint16, ctypes.POINTER(None))),
    ('GetSurfaceData', ctypes.CFUNCTYPE(ctypes.POINTER(None), ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.c_uint16)),
    ('SetCacheSlotData', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.c_uint16, ctypes.POINTER(None))),
    ('GetCacheSlotData', ctypes.CFUNCTYPE(ctypes.POINTER(None), ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.c_uint16)),
    ('OnOpen', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32))),
    ('OnClose', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context))),
    ('CapsAdvertise', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_CAPS_ADVERTISE_PDU))),
    ('CapsConfirm', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_CAPS_CONFIRM_PDU))),
    ('FrameAcknowledge', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_FRAME_ACKNOWLEDGE_PDU))),
    ('QoeFrameAcknowledge', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_RDPGFX_QOE_FRAME_ACKNOWLEDGE_PDU))),
    ('UpdateSurfaces', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context))),
    ('UpdateSurfaceArea', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.c_uint16, ctypes.c_uint32, ctypes.POINTER(struct_RECTANGLE_16))),
    ('UpdateWindowFromSurface', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.POINTER(struct_gdi_gfx_surface))),
    ('MapWindowForSurface', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.c_uint16, ctypes.c_uint64)),
    ('UnmapWindowForSurface', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpgfx_client_context), ctypes.c_uint64)),
    ('mux', struct_RTL_CRITICAL_SECTION),
    ('codecs', ctypes.POINTER(struct_rdp_codecs)),
]

class struct_MONITOR_DEF(Structure):
    pass

struct_RDPGFX_RESET_GRAPHICS_PDU._pack_ = 1 # source:False
struct_RDPGFX_RESET_GRAPHICS_PDU._fields_ = [
    ('width', ctypes.c_uint32),
    ('height', ctypes.c_uint32),
    ('monitorCount', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('monitorDefArray', ctypes.POINTER(struct_MONITOR_DEF)),
]

struct_MONITOR_DEF._pack_ = 1 # source:False
struct_MONITOR_DEF._fields_ = [
    ('left', ctypes.c_int32),
    ('top', ctypes.c_int32),
    ('right', ctypes.c_int32),
    ('bottom', ctypes.c_int32),
    ('flags', ctypes.c_uint32),
]

struct_RDPGFX_START_FRAME_PDU._pack_ = 1 # source:False
struct_RDPGFX_START_FRAME_PDU._fields_ = [
    ('timestamp', ctypes.c_uint32),
    ('frameId', ctypes.c_uint32),
]

struct_RDPGFX_END_FRAME_PDU._pack_ = 1 # source:False
struct_RDPGFX_END_FRAME_PDU._fields_ = [
    ('frameId', ctypes.c_uint32),
]

struct_RDPGFX_SURFACE_COMMAND._pack_ = 1 # source:False
struct_RDPGFX_SURFACE_COMMAND._fields_ = [
    ('surfaceId', ctypes.c_uint32),
    ('codecId', ctypes.c_uint32),
    ('contextId', ctypes.c_uint32),
    ('format', ctypes.c_uint32),
    ('left', ctypes.c_uint32),
    ('top', ctypes.c_uint32),
    ('right', ctypes.c_uint32),
    ('bottom', ctypes.c_uint32),
    ('width', ctypes.c_uint32),
    ('height', ctypes.c_uint32),
    ('length', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('data', ctypes.POINTER(ctypes.c_ubyte)),
    ('extra', ctypes.POINTER(None)),
]

struct_RDPGFX_DELETE_ENCODING_CONTEXT_PDU._pack_ = 1 # source:False
struct_RDPGFX_DELETE_ENCODING_CONTEXT_PDU._fields_ = [
    ('surfaceId', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('codecContextId', ctypes.c_uint32),
]

struct_RDPGFX_CREATE_SURFACE_PDU._pack_ = 1 # source:False
struct_RDPGFX_CREATE_SURFACE_PDU._fields_ = [
    ('surfaceId', ctypes.c_uint16),
    ('width', ctypes.c_uint16),
    ('height', ctypes.c_uint16),
    ('pixelFormat', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte),
]

struct_RDPGFX_DELETE_SURFACE_PDU._pack_ = 1 # source:False
struct_RDPGFX_DELETE_SURFACE_PDU._fields_ = [
    ('surfaceId', ctypes.c_uint16),
]

class struct_RDPGFX_COLOR32(Structure):
    pass

struct_RDPGFX_COLOR32._pack_ = 1 # source:False
struct_RDPGFX_COLOR32._fields_ = [
    ('B', ctypes.c_ubyte),
    ('G', ctypes.c_ubyte),
    ('R', ctypes.c_ubyte),
    ('XA', ctypes.c_ubyte),
]

struct_RDPGFX_SOLID_FILL_PDU._pack_ = 1 # source:False
struct_RDPGFX_SOLID_FILL_PDU._fields_ = [
    ('surfaceId', ctypes.c_uint16),
    ('fillPixel', struct_RDPGFX_COLOR32),
    ('fillRectCount', ctypes.c_uint16),
    ('fillRects', ctypes.POINTER(struct_RECTANGLE_16)),
]

struct_RECTANGLE_16._pack_ = 1 # source:False
struct_RECTANGLE_16._fields_ = [
    ('left', ctypes.c_uint16),
    ('top', ctypes.c_uint16),
    ('right', ctypes.c_uint16),
    ('bottom', ctypes.c_uint16),
]

class struct_RDPGFX_POINT16(Structure):
    pass

struct_RDPGFX_SURFACE_TO_SURFACE_PDU._pack_ = 1 # source:False
struct_RDPGFX_SURFACE_TO_SURFACE_PDU._fields_ = [
    ('surfaceIdSrc', ctypes.c_uint16),
    ('surfaceIdDest', ctypes.c_uint16),
    ('rectSrc', struct_RECTANGLE_16),
    ('destPtsCount', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('destPts', ctypes.POINTER(struct_RDPGFX_POINT16)),
]

struct_RDPGFX_POINT16._pack_ = 1 # source:False
struct_RDPGFX_POINT16._fields_ = [
    ('x', ctypes.c_uint16),
    ('y', ctypes.c_uint16),
]

struct_RDPGFX_SURFACE_TO_CACHE_PDU._pack_ = 1 # source:False
struct_RDPGFX_SURFACE_TO_CACHE_PDU._fields_ = [
    ('surfaceId', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 6),
    ('cacheKey', ctypes.c_uint64),
    ('cacheSlot', ctypes.c_uint16),
    ('rectSrc', struct_RECTANGLE_16),
    ('PADDING_1', ctypes.c_ubyte * 6),
]

struct_RDPGFX_CACHE_TO_SURFACE_PDU._pack_ = 1 # source:False
struct_RDPGFX_CACHE_TO_SURFACE_PDU._fields_ = [
    ('cacheSlot', ctypes.c_uint16),
    ('surfaceId', ctypes.c_uint16),
    ('destPtsCount', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('destPts', ctypes.POINTER(struct_RDPGFX_POINT16)),
]

class struct_RDPGFX_CACHE_ENTRY_METADATA(Structure):
    pass

struct_RDPGFX_CACHE_ENTRY_METADATA._pack_ = 1 # source:False
struct_RDPGFX_CACHE_ENTRY_METADATA._fields_ = [
    ('cacheKey', ctypes.c_uint64),
    ('bitmapLength', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

struct_RDPGFX_CACHE_IMPORT_OFFER_PDU._pack_ = 1 # source:False
struct_RDPGFX_CACHE_IMPORT_OFFER_PDU._fields_ = [
    ('cacheEntriesCount', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 6),
    ('cacheEntries', struct_RDPGFX_CACHE_ENTRY_METADATA * 5462),
]

struct_RDPGFX_CACHE_IMPORT_REPLY_PDU._pack_ = 1 # source:False
struct_RDPGFX_CACHE_IMPORT_REPLY_PDU._fields_ = [
    ('importedEntriesCount', ctypes.c_uint16),
    ('cacheSlots', ctypes.c_uint16 * 5462),
]

struct_PERSISTENT_CACHE_ENTRY._pack_ = 1 # source:False
struct_PERSISTENT_CACHE_ENTRY._fields_ = [
    ('key64', ctypes.c_uint64),
    ('width', ctypes.c_uint16),
    ('height', ctypes.c_uint16),
    ('size', ctypes.c_uint32),
    ('flags', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('data', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_RDPGFX_EVICT_CACHE_ENTRY_PDU._pack_ = 1 # source:False
struct_RDPGFX_EVICT_CACHE_ENTRY_PDU._fields_ = [
    ('cacheSlot', ctypes.c_uint16),
]

struct_RDPGFX_MAP_SURFACE_TO_OUTPUT_PDU._pack_ = 1 # source:False
struct_RDPGFX_MAP_SURFACE_TO_OUTPUT_PDU._fields_ = [
    ('surfaceId', ctypes.c_uint16),
    ('reserved', ctypes.c_uint16),
    ('outputOriginX', ctypes.c_uint32),
    ('outputOriginY', ctypes.c_uint32),
]

struct_RDPGFX_MAP_SURFACE_TO_SCALED_OUTPUT_PDU._pack_ = 1 # source:False
struct_RDPGFX_MAP_SURFACE_TO_SCALED_OUTPUT_PDU._fields_ = [
    ('surfaceId', ctypes.c_uint16),
    ('reserved', ctypes.c_uint16),
    ('outputOriginX', ctypes.c_uint32),
    ('outputOriginY', ctypes.c_uint32),
    ('targetWidth', ctypes.c_uint32),
    ('targetHeight', ctypes.c_uint32),
]

struct_RDPGFX_MAP_SURFACE_TO_WINDOW_PDU._pack_ = 1 # source:False
struct_RDPGFX_MAP_SURFACE_TO_WINDOW_PDU._fields_ = [
    ('surfaceId', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 6),
    ('windowId', ctypes.c_uint64),
    ('mappedWidth', ctypes.c_uint32),
    ('mappedHeight', ctypes.c_uint32),
]

struct_RDPGFX_MAP_SURFACE_TO_SCALED_WINDOW_PDU._pack_ = 1 # source:False
struct_RDPGFX_MAP_SURFACE_TO_SCALED_WINDOW_PDU._fields_ = [
    ('surfaceId', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 6),
    ('windowId', ctypes.c_uint64),
    ('mappedWidth', ctypes.c_uint32),
    ('mappedHeight', ctypes.c_uint32),
    ('targetWidth', ctypes.c_uint32),
    ('targetHeight', ctypes.c_uint32),
]

class struct_RDPGFX_CAPSET(Structure):
    pass

struct_RDPGFX_CAPS_ADVERTISE_PDU._pack_ = 1 # source:False
struct_RDPGFX_CAPS_ADVERTISE_PDU._fields_ = [
    ('capsSetCount', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 6),
    ('capsSets', ctypes.POINTER(struct_RDPGFX_CAPSET)),
]

struct_RDPGFX_CAPSET._pack_ = 1 # source:False
struct_RDPGFX_CAPSET._fields_ = [
    ('version', ctypes.c_uint32),
    ('length', ctypes.c_uint32),
    ('flags', ctypes.c_uint32),
]

struct_RDPGFX_CAPS_CONFIRM_PDU._pack_ = 1 # source:False
struct_RDPGFX_CAPS_CONFIRM_PDU._fields_ = [
    ('capsSet', ctypes.POINTER(struct_RDPGFX_CAPSET)),
]

struct_RDPGFX_FRAME_ACKNOWLEDGE_PDU._pack_ = 1 # source:False
struct_RDPGFX_FRAME_ACKNOWLEDGE_PDU._fields_ = [
    ('queueDepth', ctypes.c_uint32),
    ('frameId', ctypes.c_uint32),
    ('totalFramesDecoded', ctypes.c_uint32),
]

struct_RDPGFX_QOE_FRAME_ACKNOWLEDGE_PDU._pack_ = 1 # source:False
struct_RDPGFX_QOE_FRAME_ACKNOWLEDGE_PDU._fields_ = [
    ('frameId', ctypes.c_uint32),
    ('timestamp', ctypes.c_uint32),
    ('timeDiffSE', ctypes.c_uint16),
    ('timeDiffEDR', ctypes.c_uint16),
]

class struct_S_RFX_CONTEXT(Structure):
    pass

class struct_S_NSC_CONTEXT(Structure):
    pass

class struct_S_H264_CONTEXT(Structure):
    pass

class struct_S_CLEAR_CONTEXT(Structure):
    pass

class struct_S_PROGRESSIVE_CONTEXT(Structure):
    pass

class struct_S_BITMAP_PLANAR_CONTEXT(Structure):
    pass

class struct_S_BITMAP_INTERLEAVED_CONTEXT(Structure):
    pass

struct_rdp_codecs._pack_ = 1 # source:False
struct_rdp_codecs._fields_ = [
    ('ThreadingFlags', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('rfx', ctypes.POINTER(struct_S_RFX_CONTEXT)),
    ('nsc', ctypes.POINTER(struct_S_NSC_CONTEXT)),
    ('h264', ctypes.POINTER(struct_S_H264_CONTEXT)),
    ('clear', ctypes.POINTER(struct_S_CLEAR_CONTEXT)),
    ('progressive', ctypes.POINTER(struct_S_PROGRESSIVE_CONTEXT)),
    ('planar', ctypes.POINTER(struct_S_BITMAP_PLANAR_CONTEXT)),
    ('interleaved', ctypes.POINTER(struct_S_BITMAP_INTERLEAVED_CONTEXT)),
]

class struct_s_VideoClientContextPriv(Structure):
    pass

class struct_VideoSurface(Structure):
    pass

struct_s_VideoClientContext._pack_ = 1 # source:False
struct_s_VideoClientContext._fields_ = [
    ('handle', ctypes.POINTER(None)),
    ('custom', ctypes.POINTER(None)),
    ('priv', ctypes.POINTER(struct_s_VideoClientContextPriv)),
    ('setGeometry', ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_s_VideoClientContext), ctypes.POINTER(struct_s_geometry_client_context))),
    ('timer', ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_s_VideoClientContext), ctypes.c_uint64)),
    ('createSurface', ctypes.CFUNCTYPE(ctypes.POINTER(struct_VideoSurface), ctypes.POINTER(struct_s_VideoClientContext), ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32)),
    ('showSurface', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_s_VideoClientContext), ctypes.POINTER(struct_VideoSurface), ctypes.c_uint32, ctypes.c_uint32)),
    ('deleteSurface', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_s_VideoClientContext), ctypes.POINTER(struct_VideoSurface))),
]

class struct_s_wHashTable(Structure):
    pass

class struct_S_MAPPED_GEOMETRY(Structure):
    pass

struct_s_geometry_client_context._pack_ = 1 # source:False
struct_s_geometry_client_context._fields_ = [
    ('geometries', ctypes.POINTER(struct_s_wHashTable)),
    ('handle', ctypes.POINTER(None)),
    ('custom', ctypes.POINTER(None)),
    ('MappedGeometryAdded', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_s_geometry_client_context), ctypes.POINTER(struct_S_MAPPED_GEOMETRY))),
    ('remoteVersion', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

class struct_FREERDP_RGNDATA(Structure):
    pass

class struct_RDP_RECT(Structure):
    pass

struct_RDP_RECT._pack_ = 1 # source:False
struct_RDP_RECT._fields_ = [
    ('x', ctypes.c_int16),
    ('y', ctypes.c_int16),
    ('width', ctypes.c_int16),
    ('height', ctypes.c_int16),
]

struct_FREERDP_RGNDATA._pack_ = 1 # source:False
struct_FREERDP_RGNDATA._fields_ = [
    ('boundingRect', struct_RDP_RECT),
    ('nRectCount', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('rects', ctypes.POINTER(struct_RDP_RECT)),
]

struct_S_MAPPED_GEOMETRY._pack_ = 1 # source:False
struct_S_MAPPED_GEOMETRY._fields_ = [
    ('refCounter', ctypes.c_int32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('mappingId', ctypes.c_uint64),
    ('topLevelId', ctypes.c_uint64),
    ('left', ctypes.c_int32),
    ('top', ctypes.c_int32),
    ('right', ctypes.c_int32),
    ('bottom', ctypes.c_int32),
    ('topLevelLeft', ctypes.c_int32),
    ('topLevelTop', ctypes.c_int32),
    ('topLevelRight', ctypes.c_int32),
    ('topLevelBottom', ctypes.c_int32),
    ('geometry', struct_FREERDP_RGNDATA),
    ('custom', ctypes.POINTER(None)),
    ('MappedGeometryUpdate', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_S_MAPPED_GEOMETRY))),
    ('MappedGeometryClear', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_S_MAPPED_GEOMETRY))),
]

struct_VideoSurface._pack_ = 1 # source:False
struct_VideoSurface._fields_ = [
    ('x', ctypes.c_uint32),
    ('y', ctypes.c_uint32),
    ('w', ctypes.c_uint32),
    ('h', ctypes.c_uint32),
    ('alignedWidth', ctypes.c_uint32),
    ('alignedHeight', ctypes.c_uint32),
    ('data', ctypes.POINTER(ctypes.c_ubyte)),
    ('format', ctypes.c_uint32),
    ('scanline', ctypes.c_uint32),
]

class struct_rdp_pointer(Structure):
    pass

class struct_rdp_glyph(Structure):
    pass

struct_rdp_graphics._pack_ = 1 # source:False
struct_rdp_graphics._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('Bitmap_Prototype', ctypes.POINTER(struct_rdp_bitmap)),
    ('Pointer_Prototype', ctypes.POINTER(struct_rdp_pointer)),
    ('Glyph_Prototype', ctypes.POINTER(struct_rdp_glyph)),
    ('paddingA', ctypes.c_uint32 * 12),
]

struct_rdp_pointer._pack_ = 1 # source:False
struct_rdp_pointer._fields_ = [
    ('size', ctypes.c_uint64),
    ('New', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_pointer))),
    ('Free', ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_pointer))),
    ('Set', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_pointer))),
    ('SetNull', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context))),
    ('SetDefault', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context))),
    ('SetPosition', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_uint32, ctypes.c_uint32)),
    ('paddingA', ctypes.c_uint32 * 9),
    ('xPos', ctypes.c_uint32),
    ('yPos', ctypes.c_uint32),
    ('width', ctypes.c_uint32),
    ('height', ctypes.c_uint32),
    ('xorBpp', ctypes.c_uint32),
    ('lengthAndMask', ctypes.c_uint32),
    ('lengthXorMask', ctypes.c_uint32),
    ('xorMaskData', ctypes.POINTER(ctypes.c_ubyte)),
    ('andMaskData', ctypes.POINTER(ctypes.c_ubyte)),
    ('paddingB', ctypes.c_uint32 * 7),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

struct_rdp_glyph._pack_ = 1 # source:False
struct_rdp_glyph._fields_ = [
    ('size', ctypes.c_uint64),
    ('New', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_glyph))),
    ('Free', ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_glyph))),
    ('Draw', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_glyph), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32)),
    ('BeginDraw', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32)),
    ('EndDraw', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint32)),
    ('SetBounds', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32)),
    ('paddingA', ctypes.c_uint32 * 9),
    ('x', ctypes.c_int32),
    ('y', ctypes.c_int32),
    ('cx', ctypes.c_uint32),
    ('cy', ctypes.c_uint32),
    ('cb', ctypes.c_uint32),
    ('aj', ctypes.POINTER(ctypes.c_ubyte)),
    ('paddingB', ctypes.c_uint32 * 10),
]

struct_rdp_input._pack_ = 1 # source:False
struct_rdp_input._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('param1', ctypes.POINTER(None)),
    ('paddingA', ctypes.c_uint32 * 14),
    ('SynchronizeEvent', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_input), ctypes.c_uint32)),
    ('KeyboardEvent', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_input), ctypes.c_uint16, ctypes.c_ubyte)),
    ('UnicodeKeyboardEvent', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_input), ctypes.c_uint16, ctypes.c_uint16)),
    ('MouseEvent', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_input), ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint16)),
    ('ExtendedMouseEvent', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_input), ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint16)),
    ('FocusInEvent', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_input), ctypes.c_uint16)),
    ('KeyboardPauseEvent', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_input))),
    ('RelMouseEvent', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_input), ctypes.c_uint16, ctypes.c_int16, ctypes.c_int16)),
    ('QoEEvent', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_input), ctypes.c_uint32)),
    ('paddingB', ctypes.c_uint32 * 7),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

class struct_rdp_pointer_update(Structure):
    pass

class struct_rdp_primary_update(Structure):
    pass

class struct_rdp_secondary_update(Structure):
    pass

class struct_rdp_altsec_update(Structure):
    pass

class struct_rdp_window_update(Structure):
    pass

class struct_rdp_bounds(Structure):
    pass

class struct_BITMAP_UPDATE(Structure):
    pass

class struct_PALETTE_UPDATE(Structure):
    pass

class struct_PLAY_SOUND_UPDATE(Structure):
    pass

class struct_wStream(Structure):
    pass

class struct_SURFACE_BITS_COMMAND(Structure):
    pass

class struct_SURFACE_FRAME_MARKER(Structure):
    pass

struct_rdp_update._pack_ = 1 # source:False
struct_rdp_update._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('paddingA', ctypes.c_uint32 * 15),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('BeginPaint', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context))),
    ('EndPaint', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context))),
    ('SetBounds', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_rdp_bounds))),
    ('Synchronize', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context))),
    ('DesktopResize', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context))),
    ('BitmapUpdate', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_BITMAP_UPDATE))),
    ('Palette', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_PALETTE_UPDATE))),
    ('PlaySound', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_PLAY_SOUND_UPDATE))),
    ('SetKeyboardIndicators', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_uint16)),
    ('SetKeyboardImeStatus', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint32)),
    ('paddingB', ctypes.c_uint32 * 6),
    ('pointer', ctypes.POINTER(struct_rdp_pointer_update)),
    ('primary', ctypes.POINTER(struct_rdp_primary_update)),
    ('secondary', ctypes.POINTER(struct_rdp_secondary_update)),
    ('altsec', ctypes.POINTER(struct_rdp_altsec_update)),
    ('window', ctypes.POINTER(struct_rdp_window_update)),
    ('paddingC', ctypes.c_uint32 * 11),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('RefreshRect', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_ubyte, ctypes.POINTER(struct_RECTANGLE_16))),
    ('SuppressOutput', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_ubyte, ctypes.POINTER(struct_RECTANGLE_16))),
    ('RemoteMonitors', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_uint32, ctypes.POINTER(struct_MONITOR_DEF))),
    ('paddingD', ctypes.c_uint32 * 13),
    ('PADDING_2', ctypes.c_ubyte * 4),
    ('SurfaceCommand', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_wStream))),
    ('SurfaceBits', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_SURFACE_BITS_COMMAND))),
    ('SurfaceFrameMarker', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_SURFACE_FRAME_MARKER))),
    ('SurfaceFrameBits', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_SURFACE_BITS_COMMAND), ctypes.c_int32, ctypes.c_int32, ctypes.c_uint32)),
    ('SurfaceFrameAcknowledge', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_uint32)),
    ('SaveSessionInfo', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_uint32, ctypes.POINTER(None))),
    ('ServerStatusInfo', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_uint32)),
    ('autoCalculateBitmapData', ctypes.c_int32),
    ('paddingE', ctypes.c_uint32 * 8),
    ('PADDING_3', ctypes.c_ubyte * 4),
]

struct_rdp_bounds._pack_ = 1 # source:False
struct_rdp_bounds._fields_ = [
    ('left', ctypes.c_int32),
    ('top', ctypes.c_int32),
    ('right', ctypes.c_int32),
    ('bottom', ctypes.c_int32),
]

class struct_BITMAP_DATA(Structure):
    pass

struct_BITMAP_UPDATE._pack_ = 1 # source:False
struct_BITMAP_UPDATE._fields_ = [
    ('number', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('rectangles', ctypes.POINTER(struct_BITMAP_DATA)),
    ('skipCompression', ctypes.c_int32),
    ('PADDING_1', ctypes.c_ubyte * 4),
]

struct_BITMAP_DATA._pack_ = 1 # source:False
struct_BITMAP_DATA._fields_ = [
    ('destLeft', ctypes.c_uint32),
    ('destTop', ctypes.c_uint32),
    ('destRight', ctypes.c_uint32),
    ('destBottom', ctypes.c_uint32),
    ('width', ctypes.c_uint32),
    ('height', ctypes.c_uint32),
    ('bitsPerPixel', ctypes.c_uint32),
    ('flags', ctypes.c_uint32),
    ('bitmapLength', ctypes.c_uint32),
    ('cbCompFirstRowSize', ctypes.c_uint32),
    ('cbCompMainBodySize', ctypes.c_uint32),
    ('cbScanWidth', ctypes.c_uint32),
    ('cbUncompressedSize', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('bitmapDataStream', ctypes.POINTER(ctypes.c_ubyte)),
    ('compressed', ctypes.c_int32),
    ('PADDING_1', ctypes.c_ubyte * 4),
]

class struct_PALETTE_ENTRY(Structure):
    pass

struct_PALETTE_ENTRY._pack_ = 1 # source:False
struct_PALETTE_ENTRY._fields_ = [
    ('red', ctypes.c_ubyte),
    ('green', ctypes.c_ubyte),
    ('blue', ctypes.c_ubyte),
]

struct_PALETTE_UPDATE._pack_ = 1 # source:False
struct_PALETTE_UPDATE._fields_ = [
    ('number', ctypes.c_uint32),
    ('entries', struct_PALETTE_ENTRY * 256),
]

struct_PLAY_SOUND_UPDATE._pack_ = 1 # source:False
struct_PLAY_SOUND_UPDATE._fields_ = [
    ('duration', ctypes.c_uint32),
    ('frequency', ctypes.c_uint32),
]

class struct_POINTER_POSITION_UPDATE(Structure):
    pass

class struct_POINTER_SYSTEM_UPDATE(Structure):
    pass

class struct_POINTER_COLOR_UPDATE(Structure):
    pass

class struct_POINTER_NEW_UPDATE(Structure):
    pass

class struct_POINTER_CACHED_UPDATE(Structure):
    pass

class struct_POINTER_LARGE_UPDATE(Structure):
    pass

struct_rdp_pointer_update._pack_ = 1 # source:False
struct_rdp_pointer_update._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('paddingA', ctypes.c_uint32 * 15),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('PointerPosition', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_POINTER_POSITION_UPDATE))),
    ('PointerSystem', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_POINTER_SYSTEM_UPDATE))),
    ('PointerColor', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_POINTER_COLOR_UPDATE))),
    ('PointerNew', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_POINTER_NEW_UPDATE))),
    ('PointerCached', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_POINTER_CACHED_UPDATE))),
    ('PointerLarge', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_POINTER_LARGE_UPDATE))),
    ('paddingB', ctypes.c_uint32 * 10),
]

struct_POINTER_POSITION_UPDATE._pack_ = 1 # source:False
struct_POINTER_POSITION_UPDATE._fields_ = [
    ('xPos', ctypes.c_uint32),
    ('yPos', ctypes.c_uint32),
]

struct_POINTER_SYSTEM_UPDATE._pack_ = 1 # source:False
struct_POINTER_SYSTEM_UPDATE._fields_ = [
    ('type', ctypes.c_uint32),
]

struct_POINTER_COLOR_UPDATE._pack_ = 1 # source:False
struct_POINTER_COLOR_UPDATE._fields_ = [
    ('cacheIndex', ctypes.c_uint16),
    ('hotSpotX', ctypes.c_uint16),
    ('hotSpotY', ctypes.c_uint16),
    ('width', ctypes.c_uint16),
    ('height', ctypes.c_uint16),
    ('lengthAndMask', ctypes.c_uint16),
    ('lengthXorMask', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('xorMaskData', ctypes.POINTER(ctypes.c_ubyte)),
    ('andMaskData', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_POINTER_NEW_UPDATE._pack_ = 1 # source:False
struct_POINTER_NEW_UPDATE._fields_ = [
    ('xorBpp', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('colorPtrAttr', struct_POINTER_COLOR_UPDATE),
]

struct_POINTER_CACHED_UPDATE._pack_ = 1 # source:False
struct_POINTER_CACHED_UPDATE._fields_ = [
    ('cacheIndex', ctypes.c_uint32),
]

struct_POINTER_LARGE_UPDATE._pack_ = 1 # source:False
struct_POINTER_LARGE_UPDATE._fields_ = [
    ('xorBpp', ctypes.c_uint16),
    ('cacheIndex', ctypes.c_uint16),
    ('hotSpotX', ctypes.c_uint16),
    ('hotSpotY', ctypes.c_uint16),
    ('width', ctypes.c_uint16),
    ('height', ctypes.c_uint16),
    ('lengthAndMask', ctypes.c_uint32),
    ('lengthXorMask', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('xorMaskData', ctypes.POINTER(ctypes.c_ubyte)),
    ('andMaskData', ctypes.POINTER(ctypes.c_ubyte)),
]

class struct_DSTBLT_ORDER(Structure):
    pass

class struct_PATBLT_ORDER(Structure):
    pass

class struct_SCRBLT_ORDER(Structure):
    pass

class struct_OPAQUE_RECT_ORDER(Structure):
    pass

class struct_DRAW_NINE_GRID_ORDER(Structure):
    pass

class struct_MULTI_DSTBLT_ORDER(Structure):
    pass

class struct_MULTI_PATBLT_ORDER(Structure):
    pass

class struct_MULTI_SCRBLT_ORDER(Structure):
    pass

class struct_MULTI_OPAQUE_RECT_ORDER(Structure):
    pass

class struct_MULTI_DRAW_NINE_GRID_ORDER(Structure):
    pass

class struct_LINE_TO_ORDER(Structure):
    pass

class struct_POLYLINE_ORDER(Structure):
    pass

class struct_MEMBLT_ORDER(Structure):
    pass

class struct_MEM3BLT_ORDER(Structure):
    pass

class struct_SAVE_BITMAP_ORDER(Structure):
    pass

class struct_GLYPH_INDEX_ORDER(Structure):
    pass

class struct_FAST_INDEX_ORDER(Structure):
    pass

class struct_FAST_GLYPH_ORDER(Structure):
    pass

class struct_POLYGON_SC_ORDER(Structure):
    pass

class struct_POLYGON_CB_ORDER(Structure):
    pass

class struct_ELLIPSE_SC_ORDER(Structure):
    pass

class struct_ELLIPSE_CB_ORDER(Structure):
    pass

class struct_ORDER_INFO(Structure):
    pass

struct_rdp_primary_update._pack_ = 1 # source:False
struct_rdp_primary_update._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('paddingA', ctypes.c_uint32 * 15),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('DstBlt', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_DSTBLT_ORDER))),
    ('PatBlt', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_PATBLT_ORDER))),
    ('ScrBlt', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_SCRBLT_ORDER))),
    ('OpaqueRect', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_OPAQUE_RECT_ORDER))),
    ('DrawNineGrid', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_DRAW_NINE_GRID_ORDER))),
    ('MultiDstBlt', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_MULTI_DSTBLT_ORDER))),
    ('MultiPatBlt', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_MULTI_PATBLT_ORDER))),
    ('MultiScrBlt', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_MULTI_SCRBLT_ORDER))),
    ('MultiOpaqueRect', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_MULTI_OPAQUE_RECT_ORDER))),
    ('MultiDrawNineGrid', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_MULTI_DRAW_NINE_GRID_ORDER))),
    ('LineTo', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_LINE_TO_ORDER))),
    ('Polyline', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_POLYLINE_ORDER))),
    ('MemBlt', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_MEMBLT_ORDER))),
    ('Mem3Blt', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_MEM3BLT_ORDER))),
    ('SaveBitmap', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_SAVE_BITMAP_ORDER))),
    ('GlyphIndex', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_GLYPH_INDEX_ORDER))),
    ('FastIndex', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_FAST_INDEX_ORDER))),
    ('FastGlyph', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_FAST_GLYPH_ORDER))),
    ('PolygonSC', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_POLYGON_SC_ORDER))),
    ('PolygonCB', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_POLYGON_CB_ORDER))),
    ('EllipseSC', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_ELLIPSE_SC_ORDER))),
    ('EllipseCB', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_ELLIPSE_CB_ORDER))),
    ('OrderInfo', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_ORDER_INFO), ctypes.POINTER(ctypes.c_char))),
    ('paddingB', ctypes.c_uint32 * 9),
    ('PADDING_1', ctypes.c_ubyte * 4),
]

struct_DSTBLT_ORDER._pack_ = 1 # source:False
struct_DSTBLT_ORDER._fields_ = [
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nWidth', ctypes.c_int32),
    ('nHeight', ctypes.c_int32),
    ('bRop', ctypes.c_uint32),
]

class struct_rdp_brush(Structure):
    pass

struct_rdp_brush._pack_ = 1 # source:False
struct_rdp_brush._fields_ = [
    ('x', ctypes.c_uint32),
    ('y', ctypes.c_uint32),
    ('bpp', ctypes.c_uint32),
    ('style', ctypes.c_uint32),
    ('hatch', ctypes.c_uint32),
    ('index', ctypes.c_uint32),
    ('data', ctypes.POINTER(ctypes.c_ubyte)),
    ('p8x8', ctypes.c_ubyte * 8),
]

struct_PATBLT_ORDER._pack_ = 1 # source:False
struct_PATBLT_ORDER._fields_ = [
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nWidth', ctypes.c_int32),
    ('nHeight', ctypes.c_int32),
    ('bRop', ctypes.c_uint32),
    ('backColor', ctypes.c_uint32),
    ('foreColor', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('brush', struct_rdp_brush),
]

struct_SCRBLT_ORDER._pack_ = 1 # source:False
struct_SCRBLT_ORDER._fields_ = [
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nWidth', ctypes.c_int32),
    ('nHeight', ctypes.c_int32),
    ('bRop', ctypes.c_uint32),
    ('nXSrc', ctypes.c_int32),
    ('nYSrc', ctypes.c_int32),
]

struct_OPAQUE_RECT_ORDER._pack_ = 1 # source:False
struct_OPAQUE_RECT_ORDER._fields_ = [
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nWidth', ctypes.c_int32),
    ('nHeight', ctypes.c_int32),
    ('color', ctypes.c_uint32),
]

struct_DRAW_NINE_GRID_ORDER._pack_ = 1 # source:False
struct_DRAW_NINE_GRID_ORDER._fields_ = [
    ('srcLeft', ctypes.c_int32),
    ('srcTop', ctypes.c_int32),
    ('srcRight', ctypes.c_int32),
    ('srcBottom', ctypes.c_int32),
    ('bitmapId', ctypes.c_uint32),
]

class struct_DELTA_RECT(Structure):
    pass

struct_DELTA_RECT._pack_ = 1 # source:False
struct_DELTA_RECT._fields_ = [
    ('left', ctypes.c_int32),
    ('top', ctypes.c_int32),
    ('width', ctypes.c_int32),
    ('height', ctypes.c_int32),
]

struct_MULTI_DSTBLT_ORDER._pack_ = 1 # source:False
struct_MULTI_DSTBLT_ORDER._fields_ = [
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nWidth', ctypes.c_int32),
    ('nHeight', ctypes.c_int32),
    ('bRop', ctypes.c_uint32),
    ('numRectangles', ctypes.c_uint32),
    ('cbData', ctypes.c_uint32),
    ('rectangles', struct_DELTA_RECT * 45),
]

struct_MULTI_PATBLT_ORDER._pack_ = 1 # source:False
struct_MULTI_PATBLT_ORDER._fields_ = [
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nWidth', ctypes.c_int32),
    ('nHeight', ctypes.c_int32),
    ('bRop', ctypes.c_uint32),
    ('backColor', ctypes.c_uint32),
    ('foreColor', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('brush', struct_rdp_brush),
    ('numRectangles', ctypes.c_uint32),
    ('cbData', ctypes.c_uint32),
    ('rectangles', struct_DELTA_RECT * 45),
]

struct_MULTI_SCRBLT_ORDER._pack_ = 1 # source:False
struct_MULTI_SCRBLT_ORDER._fields_ = [
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nWidth', ctypes.c_int32),
    ('nHeight', ctypes.c_int32),
    ('bRop', ctypes.c_uint32),
    ('nXSrc', ctypes.c_int32),
    ('nYSrc', ctypes.c_int32),
    ('numRectangles', ctypes.c_uint32),
    ('cbData', ctypes.c_uint32),
    ('rectangles', struct_DELTA_RECT * 45),
]

struct_MULTI_OPAQUE_RECT_ORDER._pack_ = 1 # source:False
struct_MULTI_OPAQUE_RECT_ORDER._fields_ = [
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nWidth', ctypes.c_int32),
    ('nHeight', ctypes.c_int32),
    ('color', ctypes.c_uint32),
    ('numRectangles', ctypes.c_uint32),
    ('cbData', ctypes.c_uint32),
    ('rectangles', struct_DELTA_RECT * 45),
]

struct_MULTI_DRAW_NINE_GRID_ORDER._pack_ = 1 # source:False
struct_MULTI_DRAW_NINE_GRID_ORDER._fields_ = [
    ('srcLeft', ctypes.c_int32),
    ('srcTop', ctypes.c_int32),
    ('srcRight', ctypes.c_int32),
    ('srcBottom', ctypes.c_int32),
    ('bitmapId', ctypes.c_uint32),
    ('nDeltaEntries', ctypes.c_uint32),
    ('cbData', ctypes.c_uint32),
    ('rectangles', struct_DELTA_RECT * 45),
]

struct_LINE_TO_ORDER._pack_ = 1 # source:False
struct_LINE_TO_ORDER._fields_ = [
    ('backMode', ctypes.c_uint32),
    ('nXStart', ctypes.c_int32),
    ('nYStart', ctypes.c_int32),
    ('nXEnd', ctypes.c_int32),
    ('nYEnd', ctypes.c_int32),
    ('backColor', ctypes.c_uint32),
    ('bRop2', ctypes.c_uint32),
    ('penStyle', ctypes.c_uint32),
    ('penWidth', ctypes.c_uint32),
    ('penColor', ctypes.c_uint32),
]

class struct_DELTA_POINT(Structure):
    pass

struct_POLYLINE_ORDER._pack_ = 1 # source:False
struct_POLYLINE_ORDER._fields_ = [
    ('xStart', ctypes.c_int32),
    ('yStart', ctypes.c_int32),
    ('bRop2', ctypes.c_uint32),
    ('penColor', ctypes.c_uint32),
    ('numDeltaEntries', ctypes.c_uint32),
    ('cbData', ctypes.c_uint32),
    ('points', ctypes.POINTER(struct_DELTA_POINT)),
]

struct_DELTA_POINT._pack_ = 1 # source:False
struct_DELTA_POINT._fields_ = [
    ('x', ctypes.c_int32),
    ('y', ctypes.c_int32),
]

struct_MEMBLT_ORDER._pack_ = 1 # source:False
struct_MEMBLT_ORDER._fields_ = [
    ('cacheId', ctypes.c_uint32),
    ('colorIndex', ctypes.c_uint32),
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nWidth', ctypes.c_int32),
    ('nHeight', ctypes.c_int32),
    ('bRop', ctypes.c_uint32),
    ('nXSrc', ctypes.c_int32),
    ('nYSrc', ctypes.c_int32),
    ('cacheIndex', ctypes.c_uint32),
    ('bitmap', ctypes.POINTER(struct_rdp_bitmap)),
]

struct_MEM3BLT_ORDER._pack_ = 1 # source:False
struct_MEM3BLT_ORDER._fields_ = [
    ('cacheId', ctypes.c_uint32),
    ('colorIndex', ctypes.c_uint32),
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nWidth', ctypes.c_int32),
    ('nHeight', ctypes.c_int32),
    ('bRop', ctypes.c_uint32),
    ('nXSrc', ctypes.c_int32),
    ('nYSrc', ctypes.c_int32),
    ('backColor', ctypes.c_uint32),
    ('foreColor', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('brush', struct_rdp_brush),
    ('cacheIndex', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('bitmap', ctypes.POINTER(struct_rdp_bitmap)),
]

struct_SAVE_BITMAP_ORDER._pack_ = 1 # source:False
struct_SAVE_BITMAP_ORDER._fields_ = [
    ('savedBitmapPosition', ctypes.c_uint32),
    ('nLeftRect', ctypes.c_int32),
    ('nTopRect', ctypes.c_int32),
    ('nRightRect', ctypes.c_int32),
    ('nBottomRect', ctypes.c_int32),
    ('operation', ctypes.c_uint32),
]

struct_GLYPH_INDEX_ORDER._pack_ = 1 # source:False
struct_GLYPH_INDEX_ORDER._fields_ = [
    ('cacheId', ctypes.c_uint32),
    ('flAccel', ctypes.c_uint32),
    ('ulCharInc', ctypes.c_uint32),
    ('fOpRedundant', ctypes.c_uint32),
    ('backColor', ctypes.c_uint32),
    ('foreColor', ctypes.c_uint32),
    ('bkLeft', ctypes.c_int32),
    ('bkTop', ctypes.c_int32),
    ('bkRight', ctypes.c_int32),
    ('bkBottom', ctypes.c_int32),
    ('opLeft', ctypes.c_int32),
    ('opTop', ctypes.c_int32),
    ('opRight', ctypes.c_int32),
    ('opBottom', ctypes.c_int32),
    ('brush', struct_rdp_brush),
    ('x', ctypes.c_int32),
    ('y', ctypes.c_int32),
    ('cbData', ctypes.c_uint32),
    ('data', ctypes.c_ubyte * 256),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

struct_FAST_INDEX_ORDER._pack_ = 1 # source:False
struct_FAST_INDEX_ORDER._fields_ = [
    ('cacheId', ctypes.c_uint32),
    ('flAccel', ctypes.c_uint32),
    ('ulCharInc', ctypes.c_uint32),
    ('backColor', ctypes.c_uint32),
    ('foreColor', ctypes.c_uint32),
    ('bkLeft', ctypes.c_int32),
    ('bkTop', ctypes.c_int32),
    ('bkRight', ctypes.c_int32),
    ('bkBottom', ctypes.c_int32),
    ('opLeft', ctypes.c_int32),
    ('opTop', ctypes.c_int32),
    ('opRight', ctypes.c_int32),
    ('opBottom', ctypes.c_int32),
    ('opaqueRect', ctypes.c_int32),
    ('x', ctypes.c_int32),
    ('y', ctypes.c_int32),
    ('cbData', ctypes.c_uint32),
    ('data', ctypes.c_ubyte * 256),
]

class struct_GLYPH_DATA_V2(Structure):
    pass

struct_GLYPH_DATA_V2._pack_ = 1 # source:False
struct_GLYPH_DATA_V2._fields_ = [
    ('cacheIndex', ctypes.c_uint32),
    ('x', ctypes.c_int32),
    ('y', ctypes.c_int32),
    ('cx', ctypes.c_uint32),
    ('cy', ctypes.c_uint32),
    ('cb', ctypes.c_uint32),
    ('aj', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_FAST_GLYPH_ORDER._pack_ = 1 # source:False
struct_FAST_GLYPH_ORDER._fields_ = [
    ('cacheId', ctypes.c_uint32),
    ('flAccel', ctypes.c_uint32),
    ('ulCharInc', ctypes.c_uint32),
    ('backColor', ctypes.c_uint32),
    ('foreColor', ctypes.c_uint32),
    ('bkLeft', ctypes.c_int32),
    ('bkTop', ctypes.c_int32),
    ('bkRight', ctypes.c_int32),
    ('bkBottom', ctypes.c_int32),
    ('opLeft', ctypes.c_int32),
    ('opTop', ctypes.c_int32),
    ('opRight', ctypes.c_int32),
    ('opBottom', ctypes.c_int32),
    ('x', ctypes.c_int32),
    ('y', ctypes.c_int32),
    ('cbData', ctypes.c_uint32),
    ('data', ctypes.c_ubyte * 256),
    ('glyphData', struct_GLYPH_DATA_V2),
]

struct_POLYGON_SC_ORDER._pack_ = 1 # source:False
struct_POLYGON_SC_ORDER._fields_ = [
    ('xStart', ctypes.c_int32),
    ('yStart', ctypes.c_int32),
    ('bRop2', ctypes.c_uint32),
    ('fillMode', ctypes.c_uint32),
    ('brushColor', ctypes.c_uint32),
    ('numPoints', ctypes.c_uint32),
    ('cbData', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('points', ctypes.POINTER(struct_DELTA_POINT)),
]

struct_POLYGON_CB_ORDER._pack_ = 1 # source:False
struct_POLYGON_CB_ORDER._fields_ = [
    ('xStart', ctypes.c_int32),
    ('yStart', ctypes.c_int32),
    ('bRop2', ctypes.c_uint32),
    ('backMode', ctypes.c_uint32),
    ('fillMode', ctypes.c_uint32),
    ('backColor', ctypes.c_uint32),
    ('foreColor', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('brush', struct_rdp_brush),
    ('numPoints', ctypes.c_uint32),
    ('cbData', ctypes.c_uint32),
    ('points', ctypes.POINTER(struct_DELTA_POINT)),
]

struct_ELLIPSE_SC_ORDER._pack_ = 1 # source:False
struct_ELLIPSE_SC_ORDER._fields_ = [
    ('leftRect', ctypes.c_int32),
    ('topRect', ctypes.c_int32),
    ('rightRect', ctypes.c_int32),
    ('bottomRect', ctypes.c_int32),
    ('bRop2', ctypes.c_uint32),
    ('fillMode', ctypes.c_uint32),
    ('color', ctypes.c_uint32),
]

struct_ELLIPSE_CB_ORDER._pack_ = 1 # source:False
struct_ELLIPSE_CB_ORDER._fields_ = [
    ('leftRect', ctypes.c_int32),
    ('topRect', ctypes.c_int32),
    ('rightRect', ctypes.c_int32),
    ('bottomRect', ctypes.c_int32),
    ('bRop2', ctypes.c_uint32),
    ('fillMode', ctypes.c_uint32),
    ('backColor', ctypes.c_uint32),
    ('foreColor', ctypes.c_uint32),
    ('brush', struct_rdp_brush),
]

struct_ORDER_INFO._pack_ = 1 # source:False
struct_ORDER_INFO._fields_ = [
    ('controlFlags', ctypes.c_uint32),
    ('orderType', ctypes.c_uint32),
    ('fieldFlags', ctypes.c_uint32),
    ('boundsFlags', ctypes.c_uint32),
    ('bounds', struct_rdp_bounds),
    ('deltaCoordinates', ctypes.c_int32),
]

class struct_CACHE_BITMAP_ORDER(Structure):
    pass

class struct_CACHE_BITMAP_V2_ORDER(Structure):
    pass

class struct_CACHE_BITMAP_V3_ORDER(Structure):
    pass

class struct_CACHE_COLOR_TABLE_ORDER(Structure):
    pass

class struct_CACHE_GLYPH_ORDER(Structure):
    pass

class struct_CACHE_GLYPH_V2_ORDER(Structure):
    pass

class struct_CACHE_BRUSH_ORDER(Structure):
    pass

struct_rdp_secondary_update._pack_ = 1 # source:False
struct_rdp_secondary_update._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('paddingA', ctypes.c_uint32 * 15),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('CacheBitmap', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_CACHE_BITMAP_ORDER))),
    ('CacheBitmapV2', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_CACHE_BITMAP_V2_ORDER))),
    ('CacheBitmapV3', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_CACHE_BITMAP_V3_ORDER))),
    ('CacheColorTable', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_CACHE_COLOR_TABLE_ORDER))),
    ('CacheGlyph', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_CACHE_GLYPH_ORDER))),
    ('CacheGlyphV2', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_CACHE_GLYPH_V2_ORDER))),
    ('CacheBrush', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_CACHE_BRUSH_ORDER))),
    ('CacheOrderInfo', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_int16, ctypes.c_uint16, ctypes.c_ubyte, ctypes.POINTER(ctypes.c_char))),
    ('paddingE', ctypes.c_uint32 * 8),
]

struct_CACHE_BITMAP_ORDER._pack_ = 1 # source:False
struct_CACHE_BITMAP_ORDER._fields_ = [
    ('cacheId', ctypes.c_uint32),
    ('bitmapBpp', ctypes.c_uint32),
    ('bitmapWidth', ctypes.c_uint32),
    ('bitmapHeight', ctypes.c_uint32),
    ('bitmapLength', ctypes.c_uint32),
    ('cacheIndex', ctypes.c_uint32),
    ('compressed', ctypes.c_int32),
    ('bitmapComprHdr', ctypes.c_ubyte * 8),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('bitmapDataStream', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_CACHE_BITMAP_V2_ORDER._pack_ = 1 # source:False
struct_CACHE_BITMAP_V2_ORDER._fields_ = [
    ('cacheId', ctypes.c_uint32),
    ('flags', ctypes.c_uint32),
    ('key1', ctypes.c_uint32),
    ('key2', ctypes.c_uint32),
    ('bitmapBpp', ctypes.c_uint32),
    ('bitmapWidth', ctypes.c_uint32),
    ('bitmapHeight', ctypes.c_uint32),
    ('bitmapLength', ctypes.c_uint32),
    ('cacheIndex', ctypes.c_uint32),
    ('compressed', ctypes.c_int32),
    ('cbCompFirstRowSize', ctypes.c_uint32),
    ('cbCompMainBodySize', ctypes.c_uint32),
    ('cbScanWidth', ctypes.c_uint32),
    ('cbUncompressedSize', ctypes.c_uint32),
    ('bitmapDataStream', ctypes.POINTER(ctypes.c_ubyte)),
]

class struct_BITMAP_DATA_EX(Structure):
    pass

struct_BITMAP_DATA_EX._pack_ = 1 # source:False
struct_BITMAP_DATA_EX._fields_ = [
    ('bpp', ctypes.c_uint32),
    ('codecID', ctypes.c_uint32),
    ('width', ctypes.c_uint32),
    ('height', ctypes.c_uint32),
    ('length', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('data', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_CACHE_BITMAP_V3_ORDER._pack_ = 1 # source:False
struct_CACHE_BITMAP_V3_ORDER._fields_ = [
    ('cacheId', ctypes.c_uint32),
    ('bpp', ctypes.c_uint32),
    ('flags', ctypes.c_uint32),
    ('cacheIndex', ctypes.c_uint32),
    ('key1', ctypes.c_uint32),
    ('key2', ctypes.c_uint32),
    ('bitmapData', struct_BITMAP_DATA_EX),
]

struct_CACHE_COLOR_TABLE_ORDER._pack_ = 1 # source:False
struct_CACHE_COLOR_TABLE_ORDER._fields_ = [
    ('cacheIndex', ctypes.c_uint32),
    ('numberColors', ctypes.c_uint32),
    ('colorTable', ctypes.c_uint32 * 256),
]

class struct_GLYPH_DATA(Structure):
    pass

struct_GLYPH_DATA._pack_ = 1 # source:False
struct_GLYPH_DATA._fields_ = [
    ('cacheIndex', ctypes.c_uint32),
    ('x', ctypes.c_int16),
    ('y', ctypes.c_int16),
    ('cx', ctypes.c_uint32),
    ('cy', ctypes.c_uint32),
    ('cb', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('aj', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_CACHE_GLYPH_ORDER._pack_ = 1 # source:False
struct_CACHE_GLYPH_ORDER._fields_ = [
    ('cacheId', ctypes.c_uint32),
    ('cGlyphs', ctypes.c_uint32),
    ('glyphData', struct_GLYPH_DATA * 256),
    ('unicodeCharacters', ctypes.POINTER(ctypes.c_uint16)),
]

struct_CACHE_GLYPH_V2_ORDER._pack_ = 1 # source:False
struct_CACHE_GLYPH_V2_ORDER._fields_ = [
    ('cacheId', ctypes.c_uint32),
    ('flags', ctypes.c_uint32),
    ('cGlyphs', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('glyphData', struct_GLYPH_DATA_V2 * 256),
    ('unicodeCharacters', ctypes.POINTER(ctypes.c_uint16)),
]

struct_CACHE_BRUSH_ORDER._pack_ = 1 # source:False
struct_CACHE_BRUSH_ORDER._fields_ = [
    ('index', ctypes.c_uint32),
    ('bpp', ctypes.c_uint32),
    ('cx', ctypes.c_uint32),
    ('cy', ctypes.c_uint32),
    ('style', ctypes.c_uint32),
    ('length', ctypes.c_uint32),
    ('data', ctypes.c_ubyte * 256),
]

class struct_CREATE_OFFSCREEN_BITMAP_ORDER(Structure):
    pass

class struct_SWITCH_SURFACE_ORDER(Structure):
    pass

class struct_CREATE_NINE_GRID_BITMAP_ORDER(Structure):
    pass

class struct_FRAME_MARKER_ORDER(Structure):
    pass

class struct_STREAM_BITMAP_FIRST_ORDER(Structure):
    pass

class struct_STREAM_BITMAP_NEXT_ORDER(Structure):
    pass

class struct_DRAW_GDIPLUS_FIRST_ORDER(Structure):
    pass

class struct_DRAW_GDIPLUS_NEXT_ORDER(Structure):
    pass

class struct_DRAW_GDIPLUS_END_ORDER(Structure):
    pass

class struct_DRAW_GDIPLUS_CACHE_FIRST_ORDER(Structure):
    pass

class struct_DRAW_GDIPLUS_CACHE_NEXT_ORDER(Structure):
    pass

class struct_DRAW_GDIPLUS_CACHE_END_ORDER(Structure):
    pass

struct_rdp_altsec_update._pack_ = 1 # source:False
struct_rdp_altsec_update._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('paddingA', ctypes.c_uint32 * 15),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('CreateOffscreenBitmap', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_CREATE_OFFSCREEN_BITMAP_ORDER))),
    ('SwitchSurface', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_SWITCH_SURFACE_ORDER))),
    ('CreateNineGridBitmap', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_CREATE_NINE_GRID_BITMAP_ORDER))),
    ('FrameMarker', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_FRAME_MARKER_ORDER))),
    ('StreamBitmapFirst', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_STREAM_BITMAP_FIRST_ORDER))),
    ('StreamBitmapNext', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_STREAM_BITMAP_NEXT_ORDER))),
    ('DrawGdiPlusFirst', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_DRAW_GDIPLUS_FIRST_ORDER))),
    ('DrawGdiPlusNext', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_DRAW_GDIPLUS_NEXT_ORDER))),
    ('DrawGdiPlusEnd', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_DRAW_GDIPLUS_END_ORDER))),
    ('DrawGdiPlusCacheFirst', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_DRAW_GDIPLUS_CACHE_FIRST_ORDER))),
    ('DrawGdiPlusCacheNext', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_DRAW_GDIPLUS_CACHE_NEXT_ORDER))),
    ('DrawGdiPlusCacheEnd', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_DRAW_GDIPLUS_CACHE_END_ORDER))),
    ('DrawOrderInfo', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.c_ubyte, ctypes.POINTER(ctypes.c_char))),
    ('paddingB', ctypes.c_uint32 * 3),
    ('PADDING_1', ctypes.c_ubyte * 4),
]

class struct_OFFSCREEN_DELETE_LIST(Structure):
    pass

struct_OFFSCREEN_DELETE_LIST._pack_ = 1 # source:False
struct_OFFSCREEN_DELETE_LIST._fields_ = [
    ('sIndices', ctypes.c_uint32),
    ('cIndices', ctypes.c_uint32),
    ('indices', ctypes.POINTER(ctypes.c_uint16)),
]

struct_CREATE_OFFSCREEN_BITMAP_ORDER._pack_ = 1 # source:False
struct_CREATE_OFFSCREEN_BITMAP_ORDER._fields_ = [
    ('id', ctypes.c_uint32),
    ('cx', ctypes.c_uint32),
    ('cy', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('deleteList', struct_OFFSCREEN_DELETE_LIST),
]

struct_SWITCH_SURFACE_ORDER._pack_ = 1 # source:False
struct_SWITCH_SURFACE_ORDER._fields_ = [
    ('bitmapId', ctypes.c_uint32),
]

class struct_NINE_GRID_BITMAP_INFO(Structure):
    pass

struct_NINE_GRID_BITMAP_INFO._pack_ = 1 # source:False
struct_NINE_GRID_BITMAP_INFO._fields_ = [
    ('flFlags', ctypes.c_uint32),
    ('ulLeftWidth', ctypes.c_uint32),
    ('ulRightWidth', ctypes.c_uint32),
    ('ulTopHeight', ctypes.c_uint32),
    ('ulBottomHeight', ctypes.c_uint32),
    ('crTransparent', ctypes.c_uint32),
]

struct_CREATE_NINE_GRID_BITMAP_ORDER._pack_ = 1 # source:False
struct_CREATE_NINE_GRID_BITMAP_ORDER._fields_ = [
    ('bitmapBpp', ctypes.c_uint32),
    ('bitmapId', ctypes.c_uint32),
    ('cx', ctypes.c_uint32),
    ('cy', ctypes.c_uint32),
    ('nineGridInfo', struct_NINE_GRID_BITMAP_INFO),
]

struct_FRAME_MARKER_ORDER._pack_ = 1 # source:False
struct_FRAME_MARKER_ORDER._fields_ = [
    ('action', ctypes.c_uint32),
]

struct_STREAM_BITMAP_FIRST_ORDER._pack_ = 1 # source:False
struct_STREAM_BITMAP_FIRST_ORDER._fields_ = [
    ('bitmapFlags', ctypes.c_uint32),
    ('bitmapBpp', ctypes.c_uint32),
    ('bitmapType', ctypes.c_uint32),
    ('bitmapWidth', ctypes.c_uint32),
    ('bitmapHeight', ctypes.c_uint32),
    ('bitmapSize', ctypes.c_uint32),
    ('bitmapBlockSize', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('bitmapBlock', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_STREAM_BITMAP_NEXT_ORDER._pack_ = 1 # source:False
struct_STREAM_BITMAP_NEXT_ORDER._fields_ = [
    ('bitmapFlags', ctypes.c_uint32),
    ('bitmapType', ctypes.c_uint32),
    ('bitmapBlockSize', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('bitmapBlock', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_DRAW_GDIPLUS_FIRST_ORDER._pack_ = 1 # source:False
struct_DRAW_GDIPLUS_FIRST_ORDER._fields_ = [
    ('cbSize', ctypes.c_uint32),
    ('cbTotalSize', ctypes.c_uint32),
    ('cbTotalEmfSize', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('emfRecords', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_DRAW_GDIPLUS_NEXT_ORDER._pack_ = 1 # source:False
struct_DRAW_GDIPLUS_NEXT_ORDER._fields_ = [
    ('cbSize', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('emfRecords', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_DRAW_GDIPLUS_END_ORDER._pack_ = 1 # source:False
struct_DRAW_GDIPLUS_END_ORDER._fields_ = [
    ('cbSize', ctypes.c_uint32),
    ('cbTotalSize', ctypes.c_uint32),
    ('cbTotalEmfSize', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('emfRecords', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_DRAW_GDIPLUS_CACHE_FIRST_ORDER._pack_ = 1 # source:False
struct_DRAW_GDIPLUS_CACHE_FIRST_ORDER._fields_ = [
    ('flags', ctypes.c_uint32),
    ('cacheType', ctypes.c_uint32),
    ('cacheIndex', ctypes.c_uint32),
    ('cbSize', ctypes.c_uint32),
    ('cbTotalSize', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('emfRecords', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_DRAW_GDIPLUS_CACHE_NEXT_ORDER._pack_ = 1 # source:False
struct_DRAW_GDIPLUS_CACHE_NEXT_ORDER._fields_ = [
    ('flags', ctypes.c_uint32),
    ('cacheType', ctypes.c_uint32),
    ('cacheIndex', ctypes.c_uint32),
    ('cbSize', ctypes.c_uint32),
    ('emfRecords', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_DRAW_GDIPLUS_CACHE_END_ORDER._pack_ = 1 # source:False
struct_DRAW_GDIPLUS_CACHE_END_ORDER._fields_ = [
    ('flags', ctypes.c_uint32),
    ('cacheType', ctypes.c_uint32),
    ('cacheIndex', ctypes.c_uint32),
    ('cbSize', ctypes.c_uint32),
    ('cbTotalSize', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('emfRecords', ctypes.POINTER(ctypes.c_ubyte)),
]

class struct_WINDOW_ORDER_INFO(Structure):
    pass

class struct_WINDOW_STATE_ORDER(Structure):
    pass

class struct_WINDOW_ICON_ORDER(Structure):
    pass

class struct_WINDOW_CACHED_ICON_ORDER(Structure):
    pass

class struct_NOTIFY_ICON_STATE_ORDER(Structure):
    pass

class struct_MONITORED_DESKTOP_ORDER(Structure):
    pass

struct_rdp_window_update._pack_ = 1 # source:False
struct_rdp_window_update._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('paddingA', ctypes.c_uint32 * 15),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('WindowCreate', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_WINDOW_ORDER_INFO), ctypes.POINTER(struct_WINDOW_STATE_ORDER))),
    ('WindowUpdate', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_WINDOW_ORDER_INFO), ctypes.POINTER(struct_WINDOW_STATE_ORDER))),
    ('WindowIcon', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_WINDOW_ORDER_INFO), ctypes.POINTER(struct_WINDOW_ICON_ORDER))),
    ('WindowCachedIcon', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_WINDOW_ORDER_INFO), ctypes.POINTER(struct_WINDOW_CACHED_ICON_ORDER))),
    ('WindowDelete', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_WINDOW_ORDER_INFO))),
    ('NotifyIconCreate', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_WINDOW_ORDER_INFO), ctypes.POINTER(struct_NOTIFY_ICON_STATE_ORDER))),
    ('NotifyIconUpdate', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_WINDOW_ORDER_INFO), ctypes.POINTER(struct_NOTIFY_ICON_STATE_ORDER))),
    ('NotifyIconDelete', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_WINDOW_ORDER_INFO))),
    ('MonitoredDesktop', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_WINDOW_ORDER_INFO), ctypes.POINTER(struct_MONITORED_DESKTOP_ORDER))),
    ('NonMonitoredDesktop', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_WINDOW_ORDER_INFO))),
    ('paddingB', ctypes.c_uint32 * 6),
]

struct_WINDOW_ORDER_INFO._pack_ = 1 # source:False
struct_WINDOW_ORDER_INFO._fields_ = [
    ('windowId', ctypes.c_uint32),
    ('fieldFlags', ctypes.c_uint32),
    ('notifyIconId', ctypes.c_uint32),
]

class struct_RAIL_UNICODE_STRING(Structure):
    pass

struct_RAIL_UNICODE_STRING._pack_ = 1 # source:False
struct_RAIL_UNICODE_STRING._fields_ = [
    ('length', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 6),
    ('string', ctypes.POINTER(ctypes.c_uint16)),
]

struct_WINDOW_STATE_ORDER._pack_ = 1 # source:False
struct_WINDOW_STATE_ORDER._fields_ = [
    ('ownerWindowId', ctypes.c_uint32),
    ('style', ctypes.c_uint32),
    ('extendedStyle', ctypes.c_uint32),
    ('showState', ctypes.c_uint32),
    ('titleInfo', struct_RAIL_UNICODE_STRING),
    ('clientOffsetX', ctypes.c_int32),
    ('clientOffsetY', ctypes.c_int32),
    ('clientAreaWidth', ctypes.c_uint32),
    ('clientAreaHeight', ctypes.c_uint32),
    ('RPContent', ctypes.c_uint32),
    ('rootParentHandle', ctypes.c_uint32),
    ('windowOffsetX', ctypes.c_int32),
    ('windowOffsetY', ctypes.c_int32),
    ('windowClientDeltaX', ctypes.c_int32),
    ('windowClientDeltaY', ctypes.c_int32),
    ('windowWidth', ctypes.c_uint32),
    ('windowHeight', ctypes.c_uint32),
    ('numWindowRects', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('windowRects', ctypes.POINTER(struct_RECTANGLE_16)),
    ('visibleOffsetX', ctypes.c_int32),
    ('visibleOffsetY', ctypes.c_int32),
    ('resizeMarginLeft', ctypes.c_uint32),
    ('resizeMarginTop', ctypes.c_uint32),
    ('resizeMarginRight', ctypes.c_uint32),
    ('resizeMarginBottom', ctypes.c_uint32),
    ('numVisibilityRects', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('visibilityRects', ctypes.POINTER(struct_RECTANGLE_16)),
    ('OverlayDescription', struct_RAIL_UNICODE_STRING),
    ('TaskbarButton', ctypes.c_ubyte),
    ('EnforceServerZOrder', ctypes.c_ubyte),
    ('AppBarState', ctypes.c_ubyte),
    ('AppBarEdge', ctypes.c_ubyte),
    ('PADDING_2', ctypes.c_ubyte * 4),
]

class struct_ICON_INFO(Structure):
    pass

struct_WINDOW_ICON_ORDER._pack_ = 1 # source:False
struct_WINDOW_ICON_ORDER._fields_ = [
    ('iconInfo', ctypes.POINTER(struct_ICON_INFO)),
]

struct_ICON_INFO._pack_ = 1 # source:False
struct_ICON_INFO._fields_ = [
    ('cacheEntry', ctypes.c_uint32),
    ('cacheId', ctypes.c_uint32),
    ('bpp', ctypes.c_uint32),
    ('width', ctypes.c_uint32),
    ('height', ctypes.c_uint32),
    ('cbColorTable', ctypes.c_uint32),
    ('cbBitsMask', ctypes.c_uint32),
    ('cbBitsColor', ctypes.c_uint32),
    ('bitsMask', ctypes.POINTER(ctypes.c_ubyte)),
    ('colorTable', ctypes.POINTER(ctypes.c_ubyte)),
    ('bitsColor', ctypes.POINTER(ctypes.c_ubyte)),
]

class struct_CACHED_ICON_INFO(Structure):
    pass

struct_CACHED_ICON_INFO._pack_ = 1 # source:False
struct_CACHED_ICON_INFO._fields_ = [
    ('cacheEntry', ctypes.c_uint32),
    ('cacheId', ctypes.c_uint32),
]

struct_WINDOW_CACHED_ICON_ORDER._pack_ = 1 # source:False
struct_WINDOW_CACHED_ICON_ORDER._fields_ = [
    ('cachedIcon', struct_CACHED_ICON_INFO),
]

class struct_NOTIFY_ICON_INFOTIP(Structure):
    pass

struct_NOTIFY_ICON_INFOTIP._pack_ = 1 # source:False
struct_NOTIFY_ICON_INFOTIP._fields_ = [
    ('timeout', ctypes.c_uint32),
    ('flags', ctypes.c_uint32),
    ('text', struct_RAIL_UNICODE_STRING),
    ('title', struct_RAIL_UNICODE_STRING),
]

struct_NOTIFY_ICON_STATE_ORDER._pack_ = 1 # source:False
struct_NOTIFY_ICON_STATE_ORDER._fields_ = [
    ('version', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('toolTip', struct_RAIL_UNICODE_STRING),
    ('infoTip', struct_NOTIFY_ICON_INFOTIP),
    ('state', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('icon', struct_ICON_INFO),
    ('cachedIcon', struct_CACHED_ICON_INFO),
]

struct_MONITORED_DESKTOP_ORDER._pack_ = 1 # source:False
struct_MONITORED_DESKTOP_ORDER._fields_ = [
    ('activeWindowId', ctypes.c_uint32),
    ('numWindowIds', ctypes.c_uint32),
    ('windowIds', ctypes.POINTER(ctypes.c_uint32)),
]

class struct_s_wStreamPool(Structure):
    pass

struct_wStream._pack_ = 1 # source:False
struct_wStream._fields_ = [
    ('buffer', ctypes.POINTER(ctypes.c_ubyte)),
    ('pointer', ctypes.POINTER(ctypes.c_ubyte)),
    ('length', ctypes.c_uint64),
    ('capacity', ctypes.c_uint64),
    ('count', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('pool', ctypes.POINTER(struct_s_wStreamPool)),
    ('isAllocatedStream', ctypes.c_int32),
    ('isOwner', ctypes.c_int32),
]

class struct_TS_BITMAP_DATA_EX(Structure):
    pass

class struct_TS_COMPRESSED_BITMAP_HEADER_EX(Structure):
    pass

struct_TS_COMPRESSED_BITMAP_HEADER_EX._pack_ = 1 # source:False
struct_TS_COMPRESSED_BITMAP_HEADER_EX._fields_ = [
    ('highUniqueId', ctypes.c_uint32),
    ('lowUniqueId', ctypes.c_uint32),
    ('tmMilliseconds', ctypes.c_uint64),
    ('tmSeconds', ctypes.c_uint64),
]

struct_TS_BITMAP_DATA_EX._pack_ = 1 # source:False
struct_TS_BITMAP_DATA_EX._fields_ = [
    ('bpp', ctypes.c_ubyte),
    ('flags', ctypes.c_ubyte),
    ('codecID', ctypes.c_uint16),
    ('width', ctypes.c_uint16),
    ('height', ctypes.c_uint16),
    ('bitmapDataLength', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('exBitmapDataHeader', struct_TS_COMPRESSED_BITMAP_HEADER_EX),
    ('bitmapData', ctypes.POINTER(ctypes.c_ubyte)),
]

struct_SURFACE_BITS_COMMAND._pack_ = 1 # source:False
struct_SURFACE_BITS_COMMAND._fields_ = [
    ('cmdType', ctypes.c_uint32),
    ('destLeft', ctypes.c_uint32),
    ('destTop', ctypes.c_uint32),
    ('destRight', ctypes.c_uint32),
    ('destBottom', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('bmp', struct_TS_BITMAP_DATA_EX),
    ('skipCompression', ctypes.c_int32),
    ('PADDING_1', ctypes.c_ubyte * 4),
]

struct_SURFACE_FRAME_MARKER._pack_ = 1 # source:False
struct_SURFACE_FRAME_MARKER._fields_ = [
    ('frameAction', ctypes.c_uint32),
    ('frameId', ctypes.c_uint32),
]

class struct_tagCHANNEL_DEF(Structure):
    pass

class struct_rdpMonitor(Structure):
    pass

class struct_ARC_CS_PRIVATE_PACKET(Structure):
    pass

class struct_ARC_SC_PRIVATE_PACKET(Structure):
    pass

class struct_TIME_ZONE_INFORMATION(Structure):
    pass

class struct_rdp_certificate(Structure):
    pass

class struct_rdp_private_key(Structure):
    pass

class struct_BITMAP_CACHE_V2_CELL_INFO(Structure):
    pass

class struct_GLYPH_CACHE_DEFINITION(Structure):
    pass

class struct_RDPDR_DEVICE(Structure):
    pass

class struct_ADDIN_ARGV(Structure):
    pass

struct_rdp_settings._pack_ = 1 # source:False
struct_rdp_settings._fields_ = [
    ('instance', ctypes.POINTER(None)),
    ('padding001', ctypes.c_uint64 * 15),
    ('ServerMode', ctypes.c_int32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('ShareId', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('PduSource', ctypes.c_uint32),
    ('PADDING_2', ctypes.c_ubyte * 4),
    ('ServerPort', ctypes.c_uint32),
    ('PADDING_3', ctypes.c_ubyte * 4),
    ('ServerHostname', ctypes.POINTER(ctypes.c_char)),
    ('Username', ctypes.POINTER(ctypes.c_char)),
    ('Password', ctypes.POINTER(ctypes.c_char)),
    ('Domain', ctypes.POINTER(ctypes.c_char)),
    ('PasswordHash', ctypes.POINTER(ctypes.c_char)),
    ('WaitForOutputBufferFlush', ctypes.c_int32),
    ('PADDING_4', ctypes.c_ubyte * 4),
    ('padding26', ctypes.c_uint64 * 1),
    ('AcceptedCert', ctypes.POINTER(ctypes.c_char)),
    ('AcceptedCertLength', ctypes.c_uint32),
    ('PADDING_5', ctypes.c_ubyte * 4),
    ('UserSpecifiedServerName', ctypes.POINTER(ctypes.c_char)),
    ('AadServerHostname', ctypes.POINTER(ctypes.c_char)),
    ('CorrelationId', ctypes.POINTER(ctypes.c_char)),
    ('padding0064', ctypes.c_uint64 * 32),
    ('ThreadingFlags', ctypes.c_uint32),
    ('PADDING_6', ctypes.c_ubyte * 4),
    ('padding0128', ctypes.c_uint64 * 63),
    ('RdpVersion', ctypes.c_uint32),
    ('PADDING_7', ctypes.c_ubyte * 4),
    ('DesktopWidth', ctypes.c_uint32),
    ('PADDING_8', ctypes.c_ubyte * 4),
    ('DesktopHeight', ctypes.c_uint32),
    ('PADDING_9', ctypes.c_ubyte * 4),
    ('ColorDepth', ctypes.c_uint32),
    ('PADDING_10', ctypes.c_ubyte * 4),
    ('ConnectionType', ctypes.c_uint32),
    ('PADDING_11', ctypes.c_ubyte * 4),
    ('ClientBuild', ctypes.c_uint32),
    ('PADDING_12', ctypes.c_ubyte * 4),
    ('ClientHostname', ctypes.POINTER(ctypes.c_char)),
    ('ClientProductId', ctypes.POINTER(ctypes.c_char)),
    ('EarlyCapabilityFlags', ctypes.c_uint32),
    ('PADDING_13', ctypes.c_ubyte * 4),
    ('NetworkAutoDetect', ctypes.c_int32),
    ('PADDING_14', ctypes.c_ubyte * 4),
    ('SupportAsymetricKeys', ctypes.c_int32),
    ('PADDING_15', ctypes.c_ubyte * 4),
    ('SupportErrorInfoPdu', ctypes.c_int32),
    ('PADDING_16', ctypes.c_ubyte * 4),
    ('SupportStatusInfoPdu', ctypes.c_int32),
    ('PADDING_17', ctypes.c_ubyte * 4),
    ('SupportMonitorLayoutPdu', ctypes.c_int32),
    ('PADDING_18', ctypes.c_ubyte * 4),
    ('SupportGraphicsPipeline', ctypes.c_int32),
    ('PADDING_19', ctypes.c_ubyte * 4),
    ('SupportDynamicTimeZone', ctypes.c_int32),
    ('PADDING_20', ctypes.c_ubyte * 4),
    ('SupportHeartbeatPdu', ctypes.c_int32),
    ('PADDING_21', ctypes.c_ubyte * 4),
    ('DesktopPhysicalWidth', ctypes.c_uint32),
    ('PADDING_22', ctypes.c_ubyte * 4),
    ('DesktopPhysicalHeight', ctypes.c_uint32),
    ('PADDING_23', ctypes.c_ubyte * 4),
    ('DesktopOrientation', ctypes.c_uint16),
    ('PADDING_24', ctypes.c_ubyte * 6),
    ('DesktopScaleFactor', ctypes.c_uint32),
    ('PADDING_25', ctypes.c_ubyte * 4),
    ('DeviceScaleFactor', ctypes.c_uint32),
    ('PADDING_26', ctypes.c_ubyte * 4),
    ('SupportEdgeActionV1', ctypes.c_int32),
    ('PADDING_27', ctypes.c_ubyte * 4),
    ('SupportEdgeActionV2', ctypes.c_int32),
    ('PADDING_28', ctypes.c_ubyte * 4),
    ('SupportSkipChannelJoin', ctypes.c_int32),
    ('PADDING_29', ctypes.c_ubyte * 4),
    ('SupportedColorDepths', ctypes.c_uint16),
    ('PADDING_30', ctypes.c_ubyte * 6),
    ('MonitorOverrideFlags', ctypes.c_uint64),
    ('SspiClientHostname', ctypes.POINTER(ctypes.c_char)),
    ('padding0192', ctypes.c_uint64 * 36),
    ('UseRdpSecurityLayer', ctypes.c_int32),
    ('PADDING_31', ctypes.c_ubyte * 4),
    ('EncryptionMethods', ctypes.c_uint32),
    ('PADDING_32', ctypes.c_ubyte * 4),
    ('ExtEncryptionMethods', ctypes.c_uint32),
    ('PADDING_33', ctypes.c_ubyte * 4),
    ('EncryptionLevel', ctypes.c_uint32),
    ('PADDING_34', ctypes.c_ubyte * 4),
    ('ServerRandom', ctypes.POINTER(ctypes.c_ubyte)),
    ('ServerRandomLength', ctypes.c_uint32),
    ('PADDING_35', ctypes.c_ubyte * 4),
    ('ServerCertificate', ctypes.POINTER(ctypes.c_ubyte)),
    ('ServerCertificateLength', ctypes.c_uint32),
    ('PADDING_36', ctypes.c_ubyte * 4),
    ('ClientRandom', ctypes.POINTER(ctypes.c_ubyte)),
    ('ClientRandomLength', ctypes.c_uint32),
    ('PADDING_37', ctypes.c_ubyte * 4),
    ('ServerLicenseRequired', ctypes.c_int32),
    ('PADDING_38', ctypes.c_ubyte * 4),
    ('ServerLicenseCompanyName', ctypes.POINTER(ctypes.c_char)),
    ('ServerLicenseProductVersion', ctypes.c_uint32),
    ('PADDING_39', ctypes.c_ubyte * 4),
    ('ServerLicenseProductName', ctypes.POINTER(ctypes.c_char)),
    ('ServerLicenseProductIssuers', ctypes.POINTER(ctypes.POINTER(ctypes.c_char))),
    ('ServerLicenseProductIssuersCount', ctypes.c_uint32),
    ('PADDING_40', ctypes.c_ubyte * 4),
    ('padding0256', ctypes.c_uint64 * 48),
    ('ChannelCount', ctypes.c_uint32),
    ('PADDING_41', ctypes.c_ubyte * 4),
    ('ChannelDefArraySize', ctypes.c_uint32),
    ('PADDING_42', ctypes.c_ubyte * 4),
    ('ChannelDefArray', ctypes.POINTER(struct_tagCHANNEL_DEF)),
    ('padding0320', ctypes.c_uint64 * 61),
    ('ClusterInfoFlags', ctypes.c_uint32),
    ('PADDING_43', ctypes.c_ubyte * 4),
    ('RedirectedSessionId', ctypes.c_uint32),
    ('PADDING_44', ctypes.c_ubyte * 4),
    ('ConsoleSession', ctypes.c_int32),
    ('PADDING_45', ctypes.c_ubyte * 4),
    ('padding0384', ctypes.c_uint64 * 61),
    ('MonitorCount', ctypes.c_uint32),
    ('PADDING_46', ctypes.c_ubyte * 4),
    ('MonitorDefArraySize', ctypes.c_uint32),
    ('PADDING_47', ctypes.c_ubyte * 4),
    ('MonitorDefArray', ctypes.POINTER(struct_rdpMonitor)),
    ('SpanMonitors', ctypes.c_int32),
    ('PADDING_48', ctypes.c_ubyte * 4),
    ('UseMultimon', ctypes.c_int32),
    ('PADDING_49', ctypes.c_ubyte * 4),
    ('ForceMultimon', ctypes.c_int32),
    ('PADDING_50', ctypes.c_ubyte * 4),
    ('DesktopPosX', ctypes.c_uint32),
    ('PADDING_51', ctypes.c_ubyte * 4),
    ('DesktopPosY', ctypes.c_uint32),
    ('PADDING_52', ctypes.c_ubyte * 4),
    ('ListMonitors', ctypes.c_int32),
    ('PADDING_53', ctypes.c_ubyte * 4),
    ('MonitorIds', ctypes.POINTER(ctypes.c_uint32)),
    ('NumMonitorIds', ctypes.c_uint32),
    ('PADDING_54', ctypes.c_ubyte * 4),
    ('MonitorLocalShiftX', ctypes.c_int32),
    ('PADDING_55', ctypes.c_ubyte * 4),
    ('MonitorLocalShiftY', ctypes.c_int32),
    ('PADDING_56', ctypes.c_ubyte * 4),
    ('HasMonitorAttributes', ctypes.c_int32),
    ('PADDING_57', ctypes.c_ubyte * 4),
    ('MonitorFlags', ctypes.c_uint32),
    ('PADDING_58', ctypes.c_ubyte * 4),
    ('MonitorAttributeFlags', ctypes.c_uint32),
    ('PADDING_59', ctypes.c_ubyte * 4),
    ('padding0448', ctypes.c_uint64 * 48),
    ('padding0512', ctypes.c_uint64 * 64),
    ('MultitransportFlags', ctypes.c_uint32),
    ('PADDING_60', ctypes.c_ubyte * 4),
    ('SupportMultitransport', ctypes.c_int32),
    ('PADDING_61', ctypes.c_ubyte * 4),
    ('padding0576', ctypes.c_uint64 * 62),
    ('padding0640', ctypes.c_uint64 * 64),
    ('AlternateShell', ctypes.POINTER(ctypes.c_char)),
    ('ShellWorkingDirectory', ctypes.POINTER(ctypes.c_char)),
    ('padding0704', ctypes.c_uint64 * 62),
    ('AutoLogonEnabled', ctypes.c_int32),
    ('PADDING_62', ctypes.c_ubyte * 4),
    ('CompressionEnabled', ctypes.c_int32),
    ('PADDING_63', ctypes.c_ubyte * 4),
    ('DisableCtrlAltDel', ctypes.c_int32),
    ('PADDING_64', ctypes.c_ubyte * 4),
    ('EnableWindowsKey', ctypes.c_int32),
    ('PADDING_65', ctypes.c_ubyte * 4),
    ('MaximizeShell', ctypes.c_int32),
    ('PADDING_66', ctypes.c_ubyte * 4),
    ('LogonNotify', ctypes.c_int32),
    ('PADDING_67', ctypes.c_ubyte * 4),
    ('LogonErrors', ctypes.c_int32),
    ('PADDING_68', ctypes.c_ubyte * 4),
    ('MouseAttached', ctypes.c_int32),
    ('PADDING_69', ctypes.c_ubyte * 4),
    ('MouseHasWheel', ctypes.c_int32),
    ('PADDING_70', ctypes.c_ubyte * 4),
    ('RemoteConsoleAudio', ctypes.c_int32),
    ('PADDING_71', ctypes.c_ubyte * 4),
    ('AudioPlayback', ctypes.c_int32),
    ('PADDING_72', ctypes.c_ubyte * 4),
    ('AudioCapture', ctypes.c_int32),
    ('PADDING_73', ctypes.c_ubyte * 4),
    ('VideoDisable', ctypes.c_int32),
    ('PADDING_74', ctypes.c_ubyte * 4),
    ('PasswordIsSmartcardPin', ctypes.c_int32),
    ('PADDING_75', ctypes.c_ubyte * 4),
    ('UsingSavedCredentials', ctypes.c_int32),
    ('PADDING_76', ctypes.c_ubyte * 4),
    ('ForceEncryptedCsPdu', ctypes.c_int32),
    ('PADDING_77', ctypes.c_ubyte * 4),
    ('HiDefRemoteApp', ctypes.c_int32),
    ('PADDING_78', ctypes.c_ubyte * 4),
    ('CompressionLevel', ctypes.c_uint32),
    ('PADDING_79', ctypes.c_ubyte * 4),
    ('RemoteAppFeatureFlags', ctypes.c_uint32),
    ('PADDING_80', ctypes.c_ubyte * 4),
    ('padding0768', ctypes.c_uint64 * 45),
    ('IPv6Enabled', ctypes.c_int32),
    ('PADDING_81', ctypes.c_ubyte * 4),
    ('ClientAddress', ctypes.POINTER(ctypes.c_char)),
    ('ClientDir', ctypes.POINTER(ctypes.c_char)),
    ('ClientSessionId', ctypes.c_uint32),
    ('PADDING_82', ctypes.c_ubyte * 4),
    ('padding0832', ctypes.c_uint64 * 60),
    ('AutoReconnectionEnabled', ctypes.c_int32),
    ('PADDING_83', ctypes.c_ubyte * 4),
    ('AutoReconnectMaxRetries', ctypes.c_uint32),
    ('PADDING_84', ctypes.c_ubyte * 4),
    ('ClientAutoReconnectCookie', ctypes.POINTER(struct_ARC_CS_PRIVATE_PACKET)),
    ('ServerAutoReconnectCookie', ctypes.POINTER(struct_ARC_SC_PRIVATE_PACKET)),
    ('PrintReconnectCookie', ctypes.c_int32),
    ('PADDING_85', ctypes.c_ubyte * 4),
    ('AutoReconnectionPacketSupported', ctypes.c_int32),
    ('PADDING_86', ctypes.c_ubyte * 4),
    ('SessionHasBeenReconnected', ctypes.c_int32),
    ('PADDING_87', ctypes.c_ubyte * 4),
    ('padding0896', ctypes.c_uint64 * 57),
    ('ClientTimeZone', ctypes.POINTER(struct_TIME_ZONE_INFORMATION)),
    ('DynamicDSTTimeZoneKeyName', ctypes.POINTER(ctypes.c_char)),
    ('DynamicDaylightTimeDisabled', ctypes.c_int32),
    ('PADDING_88', ctypes.c_ubyte * 4),
    ('padding0960', ctypes.c_uint64 * 61),
    ('PerformanceFlags', ctypes.c_uint32),
    ('PADDING_89', ctypes.c_ubyte * 4),
    ('AllowFontSmoothing', ctypes.c_int32),
    ('PADDING_90', ctypes.c_ubyte * 4),
    ('DisableWallpaper', ctypes.c_int32),
    ('PADDING_91', ctypes.c_ubyte * 4),
    ('DisableFullWindowDrag', ctypes.c_int32),
    ('PADDING_92', ctypes.c_ubyte * 4),
    ('DisableMenuAnims', ctypes.c_int32),
    ('PADDING_93', ctypes.c_ubyte * 4),
    ('DisableThemes', ctypes.c_int32),
    ('PADDING_94', ctypes.c_ubyte * 4),
    ('DisableCursorShadow', ctypes.c_int32),
    ('PADDING_95', ctypes.c_ubyte * 4),
    ('DisableCursorBlinking', ctypes.c_int32),
    ('PADDING_96', ctypes.c_ubyte * 4),
    ('AllowDesktopComposition', ctypes.c_int32),
    ('PADDING_97', ctypes.c_ubyte * 4),
    ('padding1024', ctypes.c_uint64 * 55),
    ('RemoteAssistanceMode', ctypes.c_int32),
    ('PADDING_98', ctypes.c_ubyte * 4),
    ('RemoteAssistanceSessionId', ctypes.POINTER(ctypes.c_char)),
    ('RemoteAssistancePassStub', ctypes.POINTER(ctypes.c_char)),
    ('RemoteAssistancePassword', ctypes.POINTER(ctypes.c_char)),
    ('RemoteAssistanceRCTicket', ctypes.POINTER(ctypes.c_char)),
    ('EncomspVirtualChannel', ctypes.c_int32),
    ('PADDING_99', ctypes.c_ubyte * 4),
    ('RemdeskVirtualChannel', ctypes.c_int32),
    ('PADDING_100', ctypes.c_ubyte * 4),
    ('LyncRdpMode', ctypes.c_int32),
    ('PADDING_101', ctypes.c_ubyte * 4),
    ('RemoteAssistanceRequestControl', ctypes.c_int32),
    ('PADDING_102', ctypes.c_ubyte * 4),
    ('padding1088', ctypes.c_uint64 * 55),
    ('TlsSecurity', ctypes.c_int32),
    ('PADDING_103', ctypes.c_ubyte * 4),
    ('NlaSecurity', ctypes.c_int32),
    ('PADDING_104', ctypes.c_ubyte * 4),
    ('RdpSecurity', ctypes.c_int32),
    ('PADDING_105', ctypes.c_ubyte * 4),
    ('ExtSecurity', ctypes.c_int32),
    ('PADDING_106', ctypes.c_ubyte * 4),
    ('Authentication', ctypes.c_int32),
    ('PADDING_107', ctypes.c_ubyte * 4),
    ('RequestedProtocols', ctypes.c_uint32),
    ('PADDING_108', ctypes.c_ubyte * 4),
    ('SelectedProtocol', ctypes.c_uint32),
    ('PADDING_109', ctypes.c_ubyte * 4),
    ('NegotiationFlags', ctypes.c_uint32),
    ('PADDING_110', ctypes.c_ubyte * 4),
    ('NegotiateSecurityLayer', ctypes.c_int32),
    ('PADDING_111', ctypes.c_ubyte * 4),
    ('RestrictedAdminModeRequired', ctypes.c_int32),
    ('PADDING_112', ctypes.c_ubyte * 4),
    ('AuthenticationServiceClass', ctypes.POINTER(ctypes.c_char)),
    ('DisableCredentialsDelegation', ctypes.c_int32),
    ('PADDING_113', ctypes.c_ubyte * 4),
    ('AuthenticationLevel', ctypes.c_uint32),
    ('PADDING_114', ctypes.c_ubyte * 4),
    ('AllowedTlsCiphers', ctypes.POINTER(ctypes.c_char)),
    ('VmConnectMode', ctypes.c_int32),
    ('PADDING_115', ctypes.c_ubyte * 4),
    ('NtlmSamFile', ctypes.POINTER(ctypes.c_char)),
    ('FIPSMode', ctypes.c_int32),
    ('PADDING_116', ctypes.c_ubyte * 4),
    ('TlsSecLevel', ctypes.c_uint32),
    ('PADDING_117', ctypes.c_ubyte * 4),
    ('SspiModule', ctypes.POINTER(ctypes.c_char)),
    ('TLSMinVersion', ctypes.c_uint16),
    ('PADDING_118', ctypes.c_ubyte * 6),
    ('TLSMaxVersion', ctypes.c_uint16),
    ('PADDING_119', ctypes.c_ubyte * 6),
    ('TlsSecretsFile', ctypes.POINTER(ctypes.c_char)),
    ('AuthenticationPackageList', ctypes.POINTER(ctypes.c_char)),
    ('RdstlsSecurity', ctypes.c_int32),
    ('PADDING_120', ctypes.c_ubyte * 4),
    ('AadSecurity', ctypes.c_int32),
    ('PADDING_121', ctypes.c_ubyte * 4),
    ('WinSCardModule', ctypes.POINTER(ctypes.c_char)),
    ('RemoteCredentialGuard', ctypes.c_int32),
    ('PADDING_122', ctypes.c_ubyte * 4),
    ('RestrictedAdminModeSupported', ctypes.c_int32),
    ('PADDING_123', ctypes.c_ubyte * 4),
    ('padding1152', ctypes.c_uint64 * 36),
    ('MstscCookieMode', ctypes.c_int32),
    ('PADDING_124', ctypes.c_ubyte * 4),
    ('CookieMaxLength', ctypes.c_uint32),
    ('PADDING_125', ctypes.c_ubyte * 4),
    ('PreconnectionId', ctypes.c_uint32),
    ('PADDING_126', ctypes.c_ubyte * 4),
    ('PreconnectionBlob', ctypes.POINTER(ctypes.c_char)),
    ('SendPreconnectionPdu', ctypes.c_int32),
    ('PADDING_127', ctypes.c_ubyte * 4),
    ('EndpointFedAuthToken', ctypes.POINTER(ctypes.c_char)),
    ('padding1216', ctypes.c_uint64 * 58),
    ('RedirectionFlags', ctypes.c_uint32),
    ('PADDING_128', ctypes.c_ubyte * 4),
    ('TargetNetAddress', ctypes.POINTER(ctypes.c_char)),
    ('LoadBalanceInfo', ctypes.POINTER(ctypes.c_ubyte)),
    ('LoadBalanceInfoLength', ctypes.c_uint32),
    ('PADDING_129', ctypes.c_ubyte * 4),
    ('RedirectionUsername', ctypes.POINTER(ctypes.c_char)),
    ('RedirectionDomain', ctypes.POINTER(ctypes.c_char)),
    ('RedirectionPassword', ctypes.POINTER(ctypes.c_ubyte)),
    ('RedirectionPasswordLength', ctypes.c_uint32),
    ('PADDING_130', ctypes.c_ubyte * 4),
    ('RedirectionTargetFQDN', ctypes.POINTER(ctypes.c_char)),
    ('RedirectionTargetNetBiosName', ctypes.POINTER(ctypes.c_char)),
    ('RedirectionTsvUrl', ctypes.POINTER(ctypes.c_ubyte)),
    ('RedirectionTsvUrlLength', ctypes.c_uint32),
    ('PADDING_131', ctypes.c_ubyte * 4),
    ('TargetNetAddressCount', ctypes.c_uint32),
    ('PADDING_132', ctypes.c_ubyte * 4),
    ('TargetNetAddresses', ctypes.POINTER(ctypes.POINTER(ctypes.c_char))),
    ('TargetNetPorts', ctypes.POINTER(ctypes.c_uint32)),
    ('RedirectionAcceptedCert', ctypes.POINTER(ctypes.c_char)),
    ('RedirectionAcceptedCertLength', ctypes.c_uint32),
    ('PADDING_133', ctypes.c_ubyte * 4),
    ('RedirectionPreferType', ctypes.c_uint32),
    ('PADDING_134', ctypes.c_ubyte * 4),
    ('RedirectionGuid', ctypes.POINTER(ctypes.c_ubyte)),
    ('RedirectionGuidLength', ctypes.c_uint32),
    ('PADDING_135', ctypes.c_ubyte * 4),
    ('RedirectionTargetCertificate', ctypes.POINTER(struct_rdp_certificate)),
    ('padding1280', ctypes.c_uint64 * 43),
    ('Password51', ctypes.POINTER(ctypes.c_ubyte)),
    ('Password51Length', ctypes.c_uint32),
    ('PADDING_136', ctypes.c_ubyte * 4),
    ('SmartcardLogon', ctypes.c_int32),
    ('PADDING_137', ctypes.c_ubyte * 4),
    ('PromptForCredentials', ctypes.c_int32),
    ('PADDING_138', ctypes.c_ubyte * 4),
    ('padding1284', ctypes.c_uint64 * 1),
    ('SmartcardCertificate', ctypes.POINTER(ctypes.c_char)),
    ('SmartcardPrivateKey', ctypes.POINTER(ctypes.c_char)),
    ('padding1287', ctypes.c_uint64 * 1),
    ('SmartcardEmulation', ctypes.c_int32),
    ('PADDING_139', ctypes.c_ubyte * 4),
    ('Pkcs11Module', ctypes.POINTER(ctypes.c_char)),
    ('PkinitAnchors', ctypes.POINTER(ctypes.c_char)),
    ('KeySpec', ctypes.c_uint32),
    ('PADDING_140', ctypes.c_ubyte * 4),
    ('CardName', ctypes.POINTER(ctypes.c_char)),
    ('ReaderName', ctypes.POINTER(ctypes.c_char)),
    ('ContainerName', ctypes.POINTER(ctypes.c_char)),
    ('CspName', ctypes.POINTER(ctypes.c_char)),
    ('padding1344', ctypes.c_uint64 * 48),
    ('KerberosKdcUrl', ctypes.POINTER(ctypes.c_char)),
    ('KerberosRealm', ctypes.POINTER(ctypes.c_char)),
    ('KerberosStartTime', ctypes.POINTER(ctypes.c_char)),
    ('KerberosLifeTime', ctypes.POINTER(ctypes.c_char)),
    ('KerberosRenewableLifeTime', ctypes.POINTER(ctypes.c_char)),
    ('KerberosCache', ctypes.POINTER(ctypes.c_char)),
    ('KerberosArmor', ctypes.POINTER(ctypes.c_char)),
    ('KerberosKeytab', ctypes.POINTER(ctypes.c_char)),
    ('KerberosRdgIsProxy', ctypes.c_int32),
    ('PADDING_141', ctypes.c_ubyte * 4),
    ('padding1408', ctypes.c_uint64 * 55),
    ('IgnoreCertificate', ctypes.c_int32),
    ('PADDING_142', ctypes.c_ubyte * 4),
    ('CertificateName', ctypes.POINTER(ctypes.c_char)),
    ('padding1410', ctypes.c_uint64 * 3),
    ('RdpServerRsaKey', ctypes.POINTER(struct_rdp_private_key)),
    ('RdpServerCertificate', ctypes.POINTER(struct_rdp_certificate)),
    ('ExternalCertificateManagement', ctypes.c_int32),
    ('PADDING_143', ctypes.c_ubyte * 4),
    ('padding1416', ctypes.c_uint64 * 3),
    ('AutoAcceptCertificate', ctypes.c_int32),
    ('PADDING_144', ctypes.c_ubyte * 4),
    ('AutoDenyCertificate', ctypes.c_int32),
    ('PADDING_145', ctypes.c_ubyte * 4),
    ('CertificateAcceptedFingerprints', ctypes.POINTER(ctypes.c_char)),
    ('padding1422', ctypes.c_uint64 * 1),
    ('CertificateCallbackPreferPEM', ctypes.c_int32),
    ('PADDING_146', ctypes.c_ubyte * 4),
    ('padding1472', ctypes.c_uint64 * 48),
    ('padding1536', ctypes.c_uint64 * 64),
    ('Workarea', ctypes.c_int32),
    ('PADDING_147', ctypes.c_ubyte * 4),
    ('Fullscreen', ctypes.c_int32),
    ('PADDING_148', ctypes.c_ubyte * 4),
    ('PercentScreen', ctypes.c_uint32),
    ('PADDING_149', ctypes.c_ubyte * 4),
    ('GrabKeyboard', ctypes.c_int32),
    ('PADDING_150', ctypes.c_ubyte * 4),
    ('Decorations', ctypes.c_int32),
    ('PADDING_151', ctypes.c_ubyte * 4),
    ('MouseMotion', ctypes.c_int32),
    ('PADDING_152', ctypes.c_ubyte * 4),
    ('WindowTitle', ctypes.POINTER(ctypes.c_char)),
    ('ParentWindowId', ctypes.c_uint64),
    ('padding1544', ctypes.c_uint64 * 1),
    ('AsyncUpdate', ctypes.c_int32),
    ('PADDING_153', ctypes.c_ubyte * 4),
    ('AsyncChannels', ctypes.c_int32),
    ('PADDING_154', ctypes.c_ubyte * 4),
    ('padding1548', ctypes.c_uint64 * 1),
    ('ToggleFullscreen', ctypes.c_int32),
    ('PADDING_155', ctypes.c_ubyte * 4),
    ('WmClass', ctypes.POINTER(ctypes.c_char)),
    ('EmbeddedWindow', ctypes.c_int32),
    ('PADDING_156', ctypes.c_ubyte * 4),
    ('SmartSizing', ctypes.c_int32),
    ('PADDING_157', ctypes.c_ubyte * 4),
    ('XPan', ctypes.c_int32),
    ('PADDING_158', ctypes.c_ubyte * 4),
    ('YPan', ctypes.c_int32),
    ('PADDING_159', ctypes.c_ubyte * 4),
    ('SmartSizingWidth', ctypes.c_uint32),
    ('PADDING_160', ctypes.c_ubyte * 4),
    ('SmartSizingHeight', ctypes.c_uint32),
    ('PADDING_161', ctypes.c_ubyte * 4),
    ('PercentScreenUseWidth', ctypes.c_int32),
    ('PADDING_162', ctypes.c_ubyte * 4),
    ('PercentScreenUseHeight', ctypes.c_int32),
    ('PADDING_163', ctypes.c_ubyte * 4),
    ('DynamicResolutionUpdate', ctypes.c_int32),
    ('PADDING_164', ctypes.c_ubyte * 4),
    ('GrabMouse', ctypes.c_int32),
    ('PADDING_165', ctypes.c_ubyte * 4),
    ('padding1601', ctypes.c_uint64 * 41),
    ('SoftwareGdi', ctypes.c_int32),
    ('PADDING_166', ctypes.c_ubyte * 4),
    ('LocalConnection', ctypes.c_int32),
    ('PADDING_167', ctypes.c_ubyte * 4),
    ('AuthenticationOnly', ctypes.c_int32),
    ('PADDING_168', ctypes.c_ubyte * 4),
    ('CredentialsFromStdin', ctypes.c_int32),
    ('PADDING_169', ctypes.c_ubyte * 4),
    ('UnmapButtons', ctypes.c_int32),
    ('PADDING_170', ctypes.c_ubyte * 4),
    ('OldLicenseBehaviour', ctypes.c_int32),
    ('PADDING_171', ctypes.c_ubyte * 4),
    ('MouseUseRelativeMove', ctypes.c_int32),
    ('PADDING_172', ctypes.c_ubyte * 4),
    ('UseCommonStdioCallbacks', ctypes.c_int32),
    ('PADDING_173', ctypes.c_ubyte * 4),
    ('ConnectChildSession', ctypes.c_int32),
    ('PADDING_174', ctypes.c_ubyte * 4),
    ('padding1664', ctypes.c_uint64 * 54),
    ('ComputerName', ctypes.POINTER(ctypes.c_char)),
    ('padding1728', ctypes.c_uint64 * 63),
    ('ConnectionFile', ctypes.POINTER(ctypes.c_char)),
    ('AssistanceFile', ctypes.POINTER(ctypes.c_char)),
    ('padding1792', ctypes.c_uint64 * 62),
    ('HomePath', ctypes.POINTER(ctypes.c_char)),
    ('ConfigPath', ctypes.POINTER(ctypes.c_char)),
    ('CurrentPath', ctypes.POINTER(ctypes.c_char)),
    ('padding1856', ctypes.c_uint64 * 61),
    ('DumpRemoteFx', ctypes.c_int32),
    ('PADDING_175', ctypes.c_ubyte * 4),
    ('PlayRemoteFx', ctypes.c_int32),
    ('PADDING_176', ctypes.c_ubyte * 4),
    ('DumpRemoteFxFile', ctypes.POINTER(ctypes.c_char)),
    ('PlayRemoteFxFile', ctypes.POINTER(ctypes.c_char)),
    ('TransportDump', ctypes.c_int32),
    ('PADDING_177', ctypes.c_ubyte * 4),
    ('TransportDumpFile', ctypes.POINTER(ctypes.c_char)),
    ('TransportDumpReplay', ctypes.c_int32),
    ('PADDING_178', ctypes.c_ubyte * 4),
    ('DeactivateClientDecoding', ctypes.c_int32),
    ('PADDING_179', ctypes.c_ubyte * 4),
    ('TransportDumpReplayNodelay', ctypes.c_int32),
    ('PADDING_180', ctypes.c_ubyte * 4),
    ('padding1920', ctypes.c_uint64 * 55),
    ('padding1984', ctypes.c_uint64 * 64),
    ('GatewayUsageMethod', ctypes.c_uint32),
    ('PADDING_181', ctypes.c_ubyte * 4),
    ('GatewayPort', ctypes.c_uint32),
    ('PADDING_182', ctypes.c_ubyte * 4),
    ('GatewayHostname', ctypes.POINTER(ctypes.c_char)),
    ('GatewayUsername', ctypes.POINTER(ctypes.c_char)),
    ('GatewayPassword', ctypes.POINTER(ctypes.c_char)),
    ('GatewayDomain', ctypes.POINTER(ctypes.c_char)),
    ('GatewayCredentialsSource', ctypes.c_uint32),
    ('PADDING_183', ctypes.c_ubyte * 4),
    ('GatewayUseSameCredentials', ctypes.c_int32),
    ('PADDING_184', ctypes.c_ubyte * 4),
    ('GatewayEnabled', ctypes.c_int32),
    ('PADDING_185', ctypes.c_ubyte * 4),
    ('GatewayBypassLocal', ctypes.c_int32),
    ('PADDING_186', ctypes.c_ubyte * 4),
    ('GatewayRpcTransport', ctypes.c_int32),
    ('PADDING_187', ctypes.c_ubyte * 4),
    ('GatewayHttpTransport', ctypes.c_int32),
    ('PADDING_188', ctypes.c_ubyte * 4),
    ('GatewayUdpTransport', ctypes.c_int32),
    ('PADDING_189', ctypes.c_ubyte * 4),
    ('GatewayAccessToken', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAcceptedCert', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAcceptedCertLength', ctypes.c_uint32),
    ('PADDING_190', ctypes.c_ubyte * 4),
    ('GatewayHttpUseWebsockets', ctypes.c_int32),
    ('PADDING_191', ctypes.c_ubyte * 4),
    ('GatewayHttpExtAuthSspiNtlm', ctypes.c_int32),
    ('PADDING_192', ctypes.c_ubyte * 4),
    ('GatewayHttpExtAuthBearer', ctypes.POINTER(ctypes.c_char)),
    ('GatewayUrl', ctypes.POINTER(ctypes.c_char)),
    ('GatewayArmTransport', ctypes.c_int32),
    ('PADDING_193', ctypes.c_ubyte * 4),
    ('GatewayAvdWvdEndpointPool', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAvdGeo', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAvdArmpath', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAvdAadtenantid', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAvdDiagnosticserviceurl', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAvdHubdiscoverygeourl', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAvdActivityhint', ctypes.POINTER(ctypes.c_char)),
    ('GatewayIgnoreRedirectionPolicy', ctypes.c_int32),
    ('PADDING_194', ctypes.c_ubyte * 4),
    ('GatewayAvdClientID', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAzureActiveDirectory', ctypes.POINTER(ctypes.c_char)),
    ('ProxyType', ctypes.c_uint32),
    ('PADDING_195', ctypes.c_ubyte * 4),
    ('ProxyHostname', ctypes.POINTER(ctypes.c_char)),
    ('ProxyPort', ctypes.c_uint16),
    ('PADDING_196', ctypes.c_ubyte * 6),
    ('ProxyUsername', ctypes.POINTER(ctypes.c_char)),
    ('ProxyPassword', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAvdUseTenantid', ctypes.c_int32),
    ('PADDING_197', ctypes.c_ubyte * 4),
    ('GatewayAvdScope', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAvdAccessTokenFormat', ctypes.POINTER(ctypes.c_char)),
    ('GatewayAvdAccessAadFormat', ctypes.POINTER(ctypes.c_char)),
    ('GatewayHttpReferer', ctypes.POINTER(ctypes.c_char)),
    ('GatewayHttpUserAgent', ctypes.POINTER(ctypes.c_char)),
    ('GatewayHttpMsUserAgent', ctypes.POINTER(ctypes.c_char)),
    ('padding2112', ctypes.c_uint64 * 85),
    ('RemoteApplicationMode', ctypes.c_int32),
    ('PADDING_198', ctypes.c_ubyte * 4),
    ('RemoteApplicationName', ctypes.POINTER(ctypes.c_char)),
    ('RemoteApplicationIcon', ctypes.POINTER(ctypes.c_char)),
    ('RemoteApplicationProgram', ctypes.POINTER(ctypes.c_char)),
    ('RemoteApplicationFile', ctypes.POINTER(ctypes.c_char)),
    ('RemoteApplicationGuid', ctypes.POINTER(ctypes.c_char)),
    ('RemoteApplicationCmdLine', ctypes.POINTER(ctypes.c_char)),
    ('RemoteApplicationExpandCmdLine', ctypes.c_uint32),
    ('PADDING_199', ctypes.c_ubyte * 4),
    ('RemoteApplicationExpandWorkingDir', ctypes.c_uint32),
    ('PADDING_200', ctypes.c_ubyte * 4),
    ('DisableRemoteAppCapsCheck', ctypes.c_int32),
    ('PADDING_201', ctypes.c_ubyte * 4),
    ('RemoteAppNumIconCaches', ctypes.c_uint32),
    ('PADDING_202', ctypes.c_ubyte * 4),
    ('RemoteAppNumIconCacheEntries', ctypes.c_uint32),
    ('PADDING_203', ctypes.c_ubyte * 4),
    ('RemoteAppLanguageBarSupported', ctypes.c_int32),
    ('PADDING_204', ctypes.c_ubyte * 4),
    ('RemoteWndSupportLevel', ctypes.c_uint32),
    ('PADDING_205', ctypes.c_ubyte * 4),
    ('RemoteApplicationSupportLevel', ctypes.c_uint32),
    ('PADDING_206', ctypes.c_ubyte * 4),
    ('RemoteApplicationSupportMask', ctypes.c_uint32),
    ('PADDING_207', ctypes.c_ubyte * 4),
    ('RemoteApplicationWorkingDir', ctypes.POINTER(ctypes.c_char)),
    ('padding2176', ctypes.c_uint64 * 47),
    ('padding2240', ctypes.c_uint64 * 64),
    ('ReceivedCapabilities', ctypes.POINTER(ctypes.c_ubyte)),
    ('ReceivedCapabilitiesSize', ctypes.c_uint32),
    ('PADDING_208', ctypes.c_ubyte * 4),
    ('ReceivedCapabilityData', ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))),
    ('ReceivedCapabilityDataSizes', ctypes.POINTER(ctypes.c_uint32)),
    ('padding2304', ctypes.c_uint64 * 60),
    ('OsMajorType', ctypes.c_uint32),
    ('PADDING_209', ctypes.c_ubyte * 4),
    ('OsMinorType', ctypes.c_uint32),
    ('PADDING_210', ctypes.c_ubyte * 4),
    ('RefreshRect', ctypes.c_int32),
    ('PADDING_211', ctypes.c_ubyte * 4),
    ('SuppressOutput', ctypes.c_int32),
    ('PADDING_212', ctypes.c_ubyte * 4),
    ('FastPathOutput', ctypes.c_int32),
    ('PADDING_213', ctypes.c_ubyte * 4),
    ('SaltedChecksum', ctypes.c_int32),
    ('PADDING_214', ctypes.c_ubyte * 4),
    ('LongCredentialsSupported', ctypes.c_int32),
    ('PADDING_215', ctypes.c_ubyte * 4),
    ('NoBitmapCompressionHeader', ctypes.c_int32),
    ('PADDING_216', ctypes.c_ubyte * 4),
    ('BitmapCompressionDisabled', ctypes.c_int32),
    ('PADDING_217', ctypes.c_ubyte * 4),
    ('CapsProtocolVersion', ctypes.c_uint16),
    ('PADDING_218', ctypes.c_ubyte * 6),
    ('CapsGeneralCompressionTypes', ctypes.c_uint16),
    ('PADDING_219', ctypes.c_ubyte * 6),
    ('CapsUpdateCapabilityFlag', ctypes.c_uint16),
    ('PADDING_220', ctypes.c_ubyte * 6),
    ('CapsRemoteUnshareFlag', ctypes.c_uint16),
    ('PADDING_221', ctypes.c_ubyte * 6),
    ('CapsGeneralCompressionLevel', ctypes.c_uint16),
    ('PADDING_222', ctypes.c_ubyte * 6),
    ('padding2368', ctypes.c_uint64 * 50),
    ('DesktopResize', ctypes.c_int32),
    ('PADDING_223', ctypes.c_ubyte * 4),
    ('DrawAllowDynamicColorFidelity', ctypes.c_int32),
    ('PADDING_224', ctypes.c_ubyte * 4),
    ('DrawAllowColorSubsampling', ctypes.c_int32),
    ('PADDING_225', ctypes.c_ubyte * 4),
    ('DrawAllowSkipAlpha', ctypes.c_int32),
    ('PADDING_226', ctypes.c_ubyte * 4),
    ('padding2432', ctypes.c_uint64 * 60),
    ('OrderSupport', ctypes.POINTER(ctypes.c_ubyte)),
    ('BitmapCacheV3Enabled', ctypes.c_int32),
    ('PADDING_227', ctypes.c_ubyte * 4),
    ('AltSecFrameMarkerSupport', ctypes.c_int32),
    ('PADDING_228', ctypes.c_ubyte * 4),
    ('AllowUnanouncedOrdersFromServer', ctypes.c_int32),
    ('PADDING_229', ctypes.c_ubyte * 4),
    ('OrderSupportFlags', ctypes.c_uint16),
    ('PADDING_230', ctypes.c_ubyte * 6),
    ('OrderSupportFlagsEx', ctypes.c_uint16),
    ('PADDING_231', ctypes.c_ubyte * 6),
    ('TerminalDescriptor', ctypes.POINTER(ctypes.c_char)),
    ('TextANSICodePage', ctypes.c_uint16),
    ('PADDING_232', ctypes.c_ubyte * 6),
    ('padding2497', ctypes.c_uint64 * 57),
    ('BitmapCacheEnabled', ctypes.c_int32),
    ('PADDING_233', ctypes.c_ubyte * 4),
    ('BitmapCacheVersion', ctypes.c_uint32),
    ('PADDING_234', ctypes.c_ubyte * 4),
    ('AllowCacheWaitingList', ctypes.c_int32),
    ('PADDING_235', ctypes.c_ubyte * 4),
    ('BitmapCachePersistEnabled', ctypes.c_int32),
    ('PADDING_236', ctypes.c_ubyte * 4),
    ('BitmapCacheV2NumCells', ctypes.c_uint32),
    ('PADDING_237', ctypes.c_ubyte * 4),
    ('BitmapCacheV2CellInfo', ctypes.POINTER(struct_BITMAP_CACHE_V2_CELL_INFO)),
    ('BitmapCachePersistFile', ctypes.POINTER(ctypes.c_char)),
    ('padding2560', ctypes.c_uint64 * 56),
    ('ColorPointerCacheSize', ctypes.c_uint32),
    ('PADDING_238', ctypes.c_ubyte * 4),
    ('PointerCacheSize', ctypes.c_uint32),
    ('PADDING_239', ctypes.c_ubyte * 4),
    ('padding2624', ctypes.c_uint64 * 60),
    ('KeyboardRemappingList', ctypes.POINTER(ctypes.c_char)),
    ('KeyboardCodePage', ctypes.c_uint32),
    ('PADDING_240', ctypes.c_ubyte * 4),
    ('KeyboardLayout', ctypes.c_uint32),
    ('PADDING_241', ctypes.c_ubyte * 4),
    ('KeyboardType', ctypes.c_uint32),
    ('PADDING_242', ctypes.c_ubyte * 4),
    ('KeyboardSubType', ctypes.c_uint32),
    ('PADDING_243', ctypes.c_ubyte * 4),
    ('KeyboardFunctionKey', ctypes.c_uint32),
    ('PADDING_244', ctypes.c_ubyte * 4),
    ('ImeFileName', ctypes.POINTER(ctypes.c_char)),
    ('UnicodeInput', ctypes.c_int32),
    ('PADDING_245', ctypes.c_ubyte * 4),
    ('FastPathInput', ctypes.c_int32),
    ('PADDING_246', ctypes.c_ubyte * 4),
    ('MultiTouchInput', ctypes.c_int32),
    ('PADDING_247', ctypes.c_ubyte * 4),
    ('MultiTouchGestures', ctypes.c_int32),
    ('PADDING_248', ctypes.c_ubyte * 4),
    ('KeyboardHook', ctypes.c_uint32),
    ('PADDING_249', ctypes.c_ubyte * 4),
    ('HasHorizontalWheel', ctypes.c_int32),
    ('PADDING_250', ctypes.c_ubyte * 4),
    ('HasExtendedMouseEvent', ctypes.c_int32),
    ('PADDING_251', ctypes.c_ubyte * 4),
    ('SuspendInput', ctypes.c_int32),
    ('PADDING_252', ctypes.c_ubyte * 4),
    ('KeyboardPipeName', ctypes.POINTER(ctypes.c_char)),
    ('HasRelativeMouseEvent', ctypes.c_int32),
    ('PADDING_253', ctypes.c_ubyte * 4),
    ('HasQoeEvent', ctypes.c_int32),
    ('PADDING_254', ctypes.c_ubyte * 4),
    ('padding2688', ctypes.c_uint64 * 48),
    ('BrushSupportLevel', ctypes.c_uint32),
    ('PADDING_255', ctypes.c_ubyte * 4),
    ('padding2752', ctypes.c_uint64 * 63),
    ('GlyphSupportLevel', ctypes.c_uint32),
    ('PADDING_256', ctypes.c_ubyte * 4),
    ('GlyphCache', ctypes.POINTER(struct_GLYPH_CACHE_DEFINITION)),
    ('FragCache', ctypes.POINTER(struct_GLYPH_CACHE_DEFINITION)),
    ('padding2816', ctypes.c_uint64 * 61),
    ('OffscreenSupportLevel', ctypes.c_uint32),
    ('PADDING_257', ctypes.c_ubyte * 4),
    ('OffscreenCacheSize', ctypes.c_uint32),
    ('PADDING_258', ctypes.c_ubyte * 4),
    ('OffscreenCacheEntries', ctypes.c_uint32),
    ('PADDING_259', ctypes.c_ubyte * 4),
    ('padding2880', ctypes.c_uint64 * 61),
    ('VCFlags', ctypes.c_uint32),
    ('PADDING_260', ctypes.c_ubyte * 4),
    ('VCChunkSize', ctypes.c_uint32),
    ('PADDING_261', ctypes.c_ubyte * 4),
    ('padding2944', ctypes.c_uint64 * 62),
    ('SoundBeepsEnabled', ctypes.c_int32),
    ('PADDING_262', ctypes.c_ubyte * 4),
    ('padding3008', ctypes.c_uint64 * 63),
    ('padding3072', ctypes.c_uint64 * 64),
    ('padding3136', ctypes.c_uint64 * 64),
    ('padding3200', ctypes.c_uint64 * 64),
    ('padding3264', ctypes.c_uint64 * 64),
    ('padding3328', ctypes.c_uint64 * 64),
    ('MultifragMaxRequestSize', ctypes.c_uint32),
    ('PADDING_263', ctypes.c_ubyte * 4),
    ('padding3392', ctypes.c_uint64 * 63),
    ('LargePointerFlag', ctypes.c_uint32),
    ('PADDING_264', ctypes.c_ubyte * 4),
    ('padding3456', ctypes.c_uint64 * 63),
    ('CompDeskSupportLevel', ctypes.c_uint32),
    ('PADDING_265', ctypes.c_ubyte * 4),
    ('padding3520', ctypes.c_uint64 * 63),
    ('SurfaceCommandsEnabled', ctypes.c_int32),
    ('PADDING_266', ctypes.c_ubyte * 4),
    ('FrameMarkerCommandEnabled', ctypes.c_int32),
    ('PADDING_267', ctypes.c_ubyte * 4),
    ('SurfaceFrameMarkerEnabled', ctypes.c_int32),
    ('PADDING_268', ctypes.c_ubyte * 4),
    ('SurfaceCommandsSupported', ctypes.c_uint32),
    ('PADDING_269', ctypes.c_ubyte * 4),
    ('padding3584', ctypes.c_uint64 * 60),
    ('padding3648', ctypes.c_uint64 * 64),
    ('RemoteFxOnly', ctypes.c_int32),
    ('PADDING_270', ctypes.c_ubyte * 4),
    ('RemoteFxCodec', ctypes.c_int32),
    ('PADDING_271', ctypes.c_ubyte * 4),
    ('RemoteFxCodecId', ctypes.c_uint32),
    ('PADDING_272', ctypes.c_ubyte * 4),
    ('RemoteFxCodecMode', ctypes.c_uint32),
    ('PADDING_273', ctypes.c_ubyte * 4),
    ('RemoteFxImageCodec', ctypes.c_int32),
    ('PADDING_274', ctypes.c_ubyte * 4),
    ('RemoteFxCaptureFlags', ctypes.c_uint32),
    ('PADDING_275', ctypes.c_ubyte * 4),
    ('RemoteFxRlgrMode', ctypes.c_uint32),
    ('PADDING_276', ctypes.c_ubyte * 4),
    ('padding3712', ctypes.c_uint64 * 57),
    ('NSCodec', ctypes.c_int32),
    ('PADDING_277', ctypes.c_ubyte * 4),
    ('NSCodecId', ctypes.c_uint32),
    ('PADDING_278', ctypes.c_ubyte * 4),
    ('FrameAcknowledge', ctypes.c_uint32),
    ('PADDING_279', ctypes.c_ubyte * 4),
    ('NSCodecColorLossLevel', ctypes.c_uint32),
    ('PADDING_280', ctypes.c_ubyte * 4),
    ('NSCodecAllowSubsampling', ctypes.c_int32),
    ('PADDING_281', ctypes.c_ubyte * 4),
    ('NSCodecAllowDynamicColorFidelity', ctypes.c_int32),
    ('PADDING_282', ctypes.c_ubyte * 4),
    ('padding3776', ctypes.c_uint64 * 58),
    ('JpegCodec', ctypes.c_int32),
    ('PADDING_283', ctypes.c_ubyte * 4),
    ('JpegCodecId', ctypes.c_uint32),
    ('PADDING_284', ctypes.c_ubyte * 4),
    ('JpegQuality', ctypes.c_uint32),
    ('PADDING_285', ctypes.c_ubyte * 4),
    ('padding3840', ctypes.c_uint64 * 61),
    ('GfxThinClient', ctypes.c_int32),
    ('PADDING_286', ctypes.c_ubyte * 4),
    ('GfxSmallCache', ctypes.c_int32),
    ('PADDING_287', ctypes.c_ubyte * 4),
    ('GfxProgressive', ctypes.c_int32),
    ('PADDING_288', ctypes.c_ubyte * 4),
    ('GfxProgressiveV2', ctypes.c_int32),
    ('PADDING_289', ctypes.c_ubyte * 4),
    ('GfxH264', ctypes.c_int32),
    ('PADDING_290', ctypes.c_ubyte * 4),
    ('GfxAVC444', ctypes.c_int32),
    ('PADDING_291', ctypes.c_ubyte * 4),
    ('GfxSendQoeAck', ctypes.c_int32),
    ('PADDING_292', ctypes.c_ubyte * 4),
    ('GfxAVC444v2', ctypes.c_int32),
    ('PADDING_293', ctypes.c_ubyte * 4),
    ('GfxCapsFilter', ctypes.c_uint32),
    ('PADDING_294', ctypes.c_ubyte * 4),
    ('GfxPlanar', ctypes.c_int32),
    ('PADDING_295', ctypes.c_ubyte * 4),
    ('GfxSuspendFrameAck', ctypes.c_int32),
    ('PADDING_296', ctypes.c_ubyte * 4),
    ('GfxCodecAV1', ctypes.c_int32),
    ('PADDING_297', ctypes.c_ubyte * 4),
    ('GfxCodecAV1Profile', ctypes.c_uint32),
    ('PADDING_298', ctypes.c_ubyte * 4),
    ('padding3904', ctypes.c_uint64 * 51),
    ('BitmapCacheV3CodecId', ctypes.c_uint32),
    ('PADDING_299', ctypes.c_ubyte * 4),
    ('padding3968', ctypes.c_uint64 * 63),
    ('DrawNineGridEnabled', ctypes.c_int32),
    ('PADDING_300', ctypes.c_ubyte * 4),
    ('DrawNineGridCacheSize', ctypes.c_uint32),
    ('PADDING_301', ctypes.c_ubyte * 4),
    ('DrawNineGridCacheEntries', ctypes.c_uint32),
    ('PADDING_302', ctypes.c_ubyte * 4),
    ('padding4032', ctypes.c_uint64 * 61),
    ('DrawGdiPlusEnabled', ctypes.c_int32),
    ('PADDING_303', ctypes.c_ubyte * 4),
    ('DrawGdiPlusCacheEnabled', ctypes.c_int32),
    ('PADDING_304', ctypes.c_ubyte * 4),
    ('padding4096', ctypes.c_uint64 * 62),
    ('padding4160', ctypes.c_uint64 * 64),
    ('DeviceRedirection', ctypes.c_int32),
    ('PADDING_305', ctypes.c_ubyte * 4),
    ('DeviceCount', ctypes.c_uint32),
    ('PADDING_306', ctypes.c_ubyte * 4),
    ('DeviceArraySize', ctypes.c_uint32),
    ('PADDING_307', ctypes.c_ubyte * 4),
    ('DeviceArray', ctypes.POINTER(ctypes.POINTER(struct_RDPDR_DEVICE))),
    ('IgnoreInvalidDevices', ctypes.c_int32),
    ('PADDING_308', ctypes.c_ubyte * 4),
    ('padding4288', ctypes.c_uint64 * 123),
    ('RedirectDrives', ctypes.c_int32),
    ('PADDING_309', ctypes.c_ubyte * 4),
    ('RedirectHomeDrive', ctypes.c_int32),
    ('PADDING_310', ctypes.c_ubyte * 4),
    ('DrivesToRedirect', ctypes.POINTER(ctypes.c_char)),
    ('padding4416', ctypes.c_uint64 * 125),
    ('RedirectSmartCards', ctypes.c_int32),
    ('PADDING_311', ctypes.c_ubyte * 4),
    ('RedirectWebAuthN', ctypes.c_int32),
    ('PADDING_312', ctypes.c_ubyte * 4),
    ('padding4544', ctypes.c_uint64 * 126),
    ('RedirectPrinters', ctypes.c_int32),
    ('PADDING_313', ctypes.c_ubyte * 4),
    ('padding4672', ctypes.c_uint64 * 127),
    ('RedirectSerialPorts', ctypes.c_int32),
    ('PADDING_314', ctypes.c_ubyte * 4),
    ('RedirectParallelPorts', ctypes.c_int32),
    ('PADDING_315', ctypes.c_ubyte * 4),
    ('PreferIPv6OverIPv4', ctypes.c_int32),
    ('PADDING_316', ctypes.c_ubyte * 4),
    ('ForceIPvX', ctypes.c_uint32),
    ('PADDING_317', ctypes.c_ubyte * 4),
    ('padding4800', ctypes.c_uint64 * 124),
    ('RedirectClipboard', ctypes.c_int32),
    ('PADDING_318', ctypes.c_ubyte * 4),
    ('ClipboardFeatureMask', ctypes.c_uint32),
    ('PADDING_319', ctypes.c_ubyte * 4),
    ('ClipboardUseSelection', ctypes.POINTER(ctypes.c_char)),
    ('padding4928', ctypes.c_uint64 * 125),
    ('StaticChannelCount', ctypes.c_uint32),
    ('PADDING_320', ctypes.c_ubyte * 4),
    ('StaticChannelArraySize', ctypes.c_uint32),
    ('PADDING_321', ctypes.c_ubyte * 4),
    ('StaticChannelArray', ctypes.POINTER(ctypes.POINTER(struct_ADDIN_ARGV))),
    ('SynchronousStaticChannels', ctypes.c_int32),
    ('PADDING_322', ctypes.c_ubyte * 4),
    ('padding5056', ctypes.c_uint64 * 124),
    ('DynamicChannelCount', ctypes.c_uint32),
    ('PADDING_323', ctypes.c_ubyte * 4),
    ('DynamicChannelArraySize', ctypes.c_uint32),
    ('PADDING_324', ctypes.c_ubyte * 4),
    ('DynamicChannelArray', ctypes.POINTER(ctypes.POINTER(struct_ADDIN_ARGV))),
    ('SupportDynamicChannels', ctypes.c_int32),
    ('PADDING_325', ctypes.c_ubyte * 4),
    ('SynchronousDynamicChannels', ctypes.c_int32),
    ('PADDING_326', ctypes.c_ubyte * 4),
    ('padding5184', ctypes.c_uint64 * 123),
    ('SupportEchoChannel', ctypes.c_int32),
    ('PADDING_327', ctypes.c_ubyte * 4),
    ('SupportDisplayControl', ctypes.c_int32),
    ('PADDING_328', ctypes.c_ubyte * 4),
    ('SupportGeometryTracking', ctypes.c_int32),
    ('PADDING_329', ctypes.c_ubyte * 4),
    ('SupportSSHAgentChannel', ctypes.c_int32),
    ('PADDING_330', ctypes.c_ubyte * 4),
    ('SupportVideoOptimized', ctypes.c_int32),
    ('PADDING_331', ctypes.c_ubyte * 4),
    ('RDP2TCPArgs', ctypes.POINTER(ctypes.c_char)),
    ('TcpKeepAlive', ctypes.c_int32),
    ('PADDING_332', ctypes.c_ubyte * 4),
    ('TcpKeepAliveRetries', ctypes.c_uint32),
    ('PADDING_333', ctypes.c_ubyte * 4),
    ('TcpKeepAliveDelay', ctypes.c_uint32),
    ('PADDING_334', ctypes.c_ubyte * 4),
    ('TcpKeepAliveInterval', ctypes.c_uint32),
    ('PADDING_335', ctypes.c_ubyte * 4),
    ('TcpAckTimeout', ctypes.c_uint32),
    ('PADDING_336', ctypes.c_ubyte * 4),
    ('ActionScript', ctypes.POINTER(ctypes.c_char)),
    ('Floatbar', ctypes.c_uint32),
    ('PADDING_337', ctypes.c_ubyte * 4),
    ('TcpConnectTimeout', ctypes.c_uint32),
    ('PADDING_338', ctypes.c_ubyte * 4),
    ('FakeMouseMotionInterval', ctypes.c_uint32),
    ('PADDING_339', ctypes.c_ubyte * 4),
    ('padding5312', ctypes.c_uint64 * 113),
]

struct_tagCHANNEL_DEF._pack_ = 1 # source:False
struct_tagCHANNEL_DEF._fields_ = [
    ('name', ctypes.c_char * 8),
    ('options', ctypes.c_uint32),
]

class struct_MONITOR_ATTRIBUTES(Structure):
    pass

struct_MONITOR_ATTRIBUTES._pack_ = 1 # source:False
struct_MONITOR_ATTRIBUTES._fields_ = [
    ('physicalWidth', ctypes.c_uint32),
    ('physicalHeight', ctypes.c_uint32),
    ('orientation', ctypes.c_uint32),
    ('desktopScaleFactor', ctypes.c_uint32),
    ('deviceScaleFactor', ctypes.c_uint32),
]

struct_rdpMonitor._pack_ = 1 # source:False
struct_rdpMonitor._fields_ = [
    ('x', ctypes.c_int32),
    ('y', ctypes.c_int32),
    ('width', ctypes.c_int32),
    ('height', ctypes.c_int32),
    ('is_primary', ctypes.c_uint32),
    ('orig_screen', ctypes.c_uint32),
    ('attributes', struct_MONITOR_ATTRIBUTES),
]

struct_ARC_CS_PRIVATE_PACKET._pack_ = 1 # source:False
struct_ARC_CS_PRIVATE_PACKET._fields_ = [
    ('cbLen', ctypes.c_uint32),
    ('version', ctypes.c_uint32),
    ('logonId', ctypes.c_uint32),
    ('securityVerifier', ctypes.c_ubyte * 16),
]

struct_ARC_SC_PRIVATE_PACKET._pack_ = 1 # source:False
struct_ARC_SC_PRIVATE_PACKET._fields_ = [
    ('cbLen', ctypes.c_uint32),
    ('version', ctypes.c_uint32),
    ('logonId', ctypes.c_uint32),
    ('arcRandomBits', ctypes.c_ubyte * 16),
]

class struct_s_SYSTEMTIME(Structure):
    pass

struct_s_SYSTEMTIME._pack_ = 1 # source:False
struct_s_SYSTEMTIME._fields_ = [
    ('wYear', ctypes.c_uint16),
    ('wMonth', ctypes.c_uint16),
    ('wDayOfWeek', ctypes.c_uint16),
    ('wDay', ctypes.c_uint16),
    ('wHour', ctypes.c_uint16),
    ('wMinute', ctypes.c_uint16),
    ('wSecond', ctypes.c_uint16),
    ('wMilliseconds', ctypes.c_uint16),
]

struct_TIME_ZONE_INFORMATION._pack_ = 1 # source:False
struct_TIME_ZONE_INFORMATION._fields_ = [
    ('Bias', ctypes.c_int32),
    ('StandardName', ctypes.c_uint16 * 32),
    ('StandardDate', struct_s_SYSTEMTIME),
    ('StandardBias', ctypes.c_int32),
    ('DaylightName', ctypes.c_uint16 * 32),
    ('DaylightDate', struct_s_SYSTEMTIME),
    ('DaylightBias', ctypes.c_int32),
]

struct_BITMAP_CACHE_V2_CELL_INFO._pack_ = 1 # source:False
struct_BITMAP_CACHE_V2_CELL_INFO._fields_ = [
    ('numEntries', ctypes.c_uint32),
    ('persistent', ctypes.c_int32),
]

struct_GLYPH_CACHE_DEFINITION._pack_ = 1 # source:False
struct_GLYPH_CACHE_DEFINITION._fields_ = [
    ('cacheEntries', ctypes.c_uint16),
    ('cacheMaximumCellSize', ctypes.c_uint16),
]

struct_RDPDR_DEVICE._pack_ = 1 # source:False
struct_RDPDR_DEVICE._fields_ = [
    ('Id', ctypes.c_uint32),
    ('Type', ctypes.c_uint32),
    ('Name', ctypes.POINTER(ctypes.c_char)),
]

struct_ADDIN_ARGV._pack_ = 1 # source:False
struct_ADDIN_ARGV._fields_ = [
    ('argc', ctypes.c_int32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('argv', ctypes.POINTER(ctypes.POINTER(ctypes.c_char))),
]

struct_rdp_metrics._pack_ = 1 # source:False
struct_rdp_metrics._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('TotalCompressedBytes', ctypes.c_uint64),
    ('TotalUncompressedBytes', ctypes.c_uint64),
    ('TotalCompressionRatio', ctypes.c_double),
]


# values for enumeration 'FREERDP_AUTODETECT_STATE'
FREERDP_AUTODETECT_STATE__enumvalues = {
    0: 'FREERDP_AUTODETECT_STATE_INITIAL',
    1: 'FREERDP_AUTODETECT_STATE_REQUEST',
    2: 'FREERDP_AUTODETECT_STATE_RESPONSE',
    3: 'FREERDP_AUTODETECT_STATE_COMPLETE',
    4: 'FREERDP_AUTODETECT_STATE_FAIL',
}
FREERDP_AUTODETECT_STATE_INITIAL = 0
FREERDP_AUTODETECT_STATE_REQUEST = 1
FREERDP_AUTODETECT_STATE_RESPONSE = 2
FREERDP_AUTODETECT_STATE_COMPLETE = 3
FREERDP_AUTODETECT_STATE_FAIL = 4
FREERDP_AUTODETECT_STATE = ctypes.c_uint32 # enum

# values for enumeration 'RDP_TRANSPORT_TYPE'
RDP_TRANSPORT_TYPE__enumvalues = {
    0: 'RDP_TRANSPORT_TCP',
    1: 'RDP_TRANSPORT_UDP_R',
    2: 'RDP_TRANSPORT_UDP_L',
}
RDP_TRANSPORT_TCP = 0
RDP_TRANSPORT_UDP_R = 1
RDP_TRANSPORT_UDP_L = 2
RDP_TRANSPORT_TYPE = ctypes.c_uint32 # enum
class struct_rdp_network_characteristics_result(Structure):
    pass

struct_rdp_autodetect._pack_ = 1 # source:False
struct_rdp_autodetect._fields_ = [
    ('context', ctypes.POINTER(struct_rdp_context)),
    ('rttMeasureStartTime', ctypes.c_uint64),
    ('bandwidthMeasureStartTime', ctypes.c_uint64),
    ('bandwidthMeasureTimeDelta', ctypes.c_uint64),
    ('bandwidthMeasureByteCount', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('netCharBandwidth', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('netCharBaseRTT', ctypes.c_uint32),
    ('PADDING_2', ctypes.c_ubyte * 4),
    ('netCharAverageRTT', ctypes.c_uint32),
    ('PADDING_3', ctypes.c_ubyte * 4),
    ('bandwidthMeasureStarted', ctypes.c_int32),
    ('PADDING_4', ctypes.c_ubyte * 4),
    ('state', FREERDP_AUTODETECT_STATE),
    ('PADDING_5', ctypes.c_ubyte * 4),
    ('custom', ctypes.POINTER(None)),
    ('log', ctypes.POINTER(struct_s_wLog)),
    ('paddingA', ctypes.c_uint64 * 4),
    ('RTTMeasureRequest', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16)),
    ('RTTMeasureResponse', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16)),
    ('BandwidthMeasureStart', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16)),
    ('BandwidthMeasurePayload', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16, ctypes.c_uint16)),
    ('BandwidthMeasureStop', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16, ctypes.c_uint16)),
    ('BandwidthMeasureResults', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint32)),
    ('NetworkCharacteristicsResult', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16, ctypes.POINTER(struct_rdp_network_characteristics_result))),
    ('ClientBandwidthMeasureResult', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint32)),
    ('NetworkCharacteristicsSync', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint32)),
    ('RequestReceived', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16, ctypes.c_uint16)),
    ('ResponseReceived', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_autodetect), RDP_TRANSPORT_TYPE, ctypes.c_uint16, ctypes.c_uint16)),
    ('OnConnectTimeAutoDetectBegin', ctypes.CFUNCTYPE(FREERDP_AUTODETECT_STATE, ctypes.POINTER(struct_rdp_autodetect))),
    ('OnConnectTimeAutoDetectProgress', ctypes.CFUNCTYPE(FREERDP_AUTODETECT_STATE, ctypes.POINTER(struct_rdp_autodetect))),
    ('paddingB', ctypes.c_uint64 * 3),
]


# values for enumeration 'RDP_NETCHAR_RESULT_TYPE'
RDP_NETCHAR_RESULT_TYPE__enumvalues = {
    0: 'RDP_NETCHAR_RESERVED',
    2112: 'RDP_NETCHAR_RESULT_TYPE_BASE_RTT_AVG_RTT',
    2176: 'RDP_NETCHAR_RESULT_TYPE_BW_AVG_RTT',
    2240: 'RDP_NETCHAR_RESULT_TYPE_BASE_RTT_BW_AVG_RTT',
}
RDP_NETCHAR_RESERVED = 0
RDP_NETCHAR_RESULT_TYPE_BASE_RTT_AVG_RTT = 2112
RDP_NETCHAR_RESULT_TYPE_BW_AVG_RTT = 2176
RDP_NETCHAR_RESULT_TYPE_BASE_RTT_BW_AVG_RTT = 2240
RDP_NETCHAR_RESULT_TYPE = ctypes.c_uint32 # enum
struct_rdp_network_characteristics_result._pack_ = 1 # source:False
struct_rdp_network_characteristics_result._fields_ = [
    ('type', RDP_NETCHAR_RESULT_TYPE),
    ('baseRTT', ctypes.c_uint32),
    ('averageRTT', ctypes.c_uint32),
    ('bandwidth', ctypes.c_uint32),
]

struct_rdp_heartbeat._pack_ = 1 # source:False
struct_rdp_heartbeat._fields_ = [
    ('ServerHeartbeat', ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte)),
]

class struct_SmartcardKeyInfo_st(Structure):
    pass

struct_SmartcardCertInfo_st._pack_ = 1 # source:False
struct_SmartcardCertInfo_st._fields_ = [
    ('csp', ctypes.POINTER(ctypes.c_uint16)),
    ('reader', ctypes.POINTER(ctypes.c_uint16)),
    ('certificate', ctypes.POINTER(struct_rdp_certificate)),
    ('pkinitArgs', ctypes.POINTER(ctypes.c_char)),
    ('slotId', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('keyName', ctypes.POINTER(ctypes.c_char)),
    ('containerName', ctypes.POINTER(ctypes.c_uint16)),
    ('upn', ctypes.POINTER(ctypes.c_char)),
    ('userHint', ctypes.POINTER(ctypes.c_char)),
    ('domainHint', ctypes.POINTER(ctypes.c_char)),
    ('subject', ctypes.POINTER(ctypes.c_char)),
    ('issuer', ctypes.POINTER(ctypes.c_char)),
    ('sha1Hash', ctypes.c_ubyte * 20),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('key_info', ctypes.POINTER(struct_SmartcardKeyInfo_st)),
]

pContextNew = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(struct_rdp_context))
pContextFree = ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(struct_rdp_context))
pConnectCallback = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp))
pPostDisconnect = ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_rdp_freerdp))
pAuthenticate = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)))
pAuthenticateEx = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), rdp_auth_reason)
pChooseSmartcard = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.POINTER(struct_SmartcardCertInfo_st)), ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int32)
pGetAccessToken = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), AccessTokenType, ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.c_uint64)
pGetCommonAccessToken = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context), AccessTokenType, ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.c_uint64)
pRetryDialog = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.c_uint64, ctypes.POINTER(None))
pVerifyCertificate = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.c_int32)
pVerifyCertificateEx = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.c_uint16, ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.c_uint32)
pVerifyChangedCertificate = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char))
pVerifyChangedCertificateEx = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.c_uint16, ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.c_uint32)
pVerifyX509Certificate = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint64, ctypes.POINTER(ctypes.c_char), ctypes.c_uint16, ctypes.c_uint32)
pLogonErrorInfo = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_uint32, ctypes.c_uint32)
pSendChannelData = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_uint16, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint64)
pSendChannelPacket = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_uint16, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint64)
pReceiveChannelData = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_uint16, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint64)
pPresentGatewayMessage = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint16))

# values for enumeration 'Disconnect_Ultimatum'
Disconnect_Ultimatum__enumvalues = {
    0: 'Disconnect_Ultimatum_domain_disconnected',
    1: 'Disconnect_Ultimatum_provider_initiated',
    2: 'Disconnect_Ultimatum_token_purged',
    3: 'Disconnect_Ultimatum_user_requested',
    4: 'Disconnect_Ultimatum_channel_purged',
}
Disconnect_Ultimatum_domain_disconnected = 0
Disconnect_Ultimatum_provider_initiated = 1
Disconnect_Ultimatum_token_purged = 2
Disconnect_Ultimatum_user_requested = 3
Disconnect_Ultimatum_channel_purged = 4
Disconnect_Ultimatum = ctypes.c_uint32 # enum
MIBClientWrapper = struct_MIBClientWrapper
pRdpGlobalInit = ctypes.CFUNCTYPE(ctypes.c_int32)
pRdpGlobalUninit = ctypes.CFUNCTYPE(None)
pRdpClientNew = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(struct_rdp_context))
pRdpClientFree = ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(struct_rdp_context))
pRdpClientStart = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context))
pRdpClientStop = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_context))
pRdpClientEntry = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_client_entry_points_v1))
FreeRDP_TouchContact = struct_FreeRDP_TouchContact
FreeRDP_PenDevice = struct_pen_device
struct_ainput_client_context._pack_ = 1 # source:False
struct_ainput_client_context._fields_ = [
    ('handle', ctypes.POINTER(None)),
    ('custom', ctypes.POINTER(None)),
    ('AInputSendInputEvent', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_ainput_client_context), ctypes.c_uint64, ctypes.c_int32, ctypes.c_int32)),
]

class struct_RDPINPUT_CONTACT_DATA(Structure):
    pass

class struct_RDPINPUT_PEN_CONTACT(Structure):
    pass

class struct___va_list_tag(Structure):
    pass

struct_s_rdpei_client_context._pack_ = 1 # source:False
struct_s_rdpei_client_context._fields_ = [
    ('handle', ctypes.POINTER(None)),
    ('custom', ctypes.POINTER(None)),
    ('GetVersion', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context))),
    ('GetFeatures', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context))),
    ('AddContact', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.POINTER(struct_RDPINPUT_CONTACT_DATA))),
    ('TouchBegin', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32))),
    ('TouchUpdate', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32))),
    ('TouchEnd', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32))),
    ('AddPen', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.POINTER(struct_RDPINPUT_PEN_CONTACT))),
    ('PenBegin', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32)),
    ('PenUpdate', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32)),
    ('PenEnd', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32)),
    ('PenHoverBegin', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32)),
    ('PenHoverUpdate', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32)),
    ('PenHoverCancel', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32)),
    ('SuspendTouch', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context))),
    ('ResumeTouch', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context))),
    ('TouchCancel', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32))),
    ('TouchRawEvent', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32), ctypes.c_uint32, ctypes.c_uint32)),
    ('TouchRawEventVA', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32), ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(struct___va_list_tag))),
    ('PenCancel', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32)),
    ('PenRawEvent', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32)),
    ('PenRawEventVA', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_rdpei_client_context), ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(struct___va_list_tag))),
    ('clientFeaturesMask', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

struct_RDPINPUT_CONTACT_DATA._pack_ = 1 # source:False
struct_RDPINPUT_CONTACT_DATA._fields_ = [
    ('contactId', ctypes.c_uint32),
    ('fieldsPresent', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('x', ctypes.c_int32),
    ('y', ctypes.c_int32),
    ('contactFlags', ctypes.c_uint32),
    ('contactRectLeft', ctypes.c_int16),
    ('contactRectTop', ctypes.c_int16),
    ('contactRectRight', ctypes.c_int16),
    ('contactRectBottom', ctypes.c_int16),
    ('orientation', ctypes.c_uint32),
    ('pressure', ctypes.c_uint32),
]

struct_RDPINPUT_PEN_CONTACT._pack_ = 1 # source:False
struct_RDPINPUT_PEN_CONTACT._fields_ = [
    ('deviceId', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte),
    ('fieldsPresent', ctypes.c_uint16),
    ('x', ctypes.c_int32),
    ('y', ctypes.c_int32),
    ('contactFlags', ctypes.c_uint32),
    ('penFlags', ctypes.c_uint32),
    ('rotation', ctypes.c_uint16),
    ('PADDING_1', ctypes.c_ubyte * 2),
    ('pressure', ctypes.c_uint32),
    ('tiltX', ctypes.c_int16),
    ('tiltY', ctypes.c_int16),
]

class struct_ENCOMSP_FILTER_UPDATED_PDU(Structure):
    pass

class struct_ENCOMSP_APPLICATION_CREATED_PDU(Structure):
    pass

class struct_ENCOMSP_APPLICATION_REMOVED_PDU(Structure):
    pass

class struct_ENCOMSP_WINDOW_CREATED_PDU(Structure):
    pass

class struct_ENCOMSP_WINDOW_REMOVED_PDU(Structure):
    pass

class struct_ENCOMSP_SHOW_WINDOW_PDU(Structure):
    pass

class struct_ENCOMSP_PARTICIPANT_CREATED_PDU(Structure):
    pass

class struct_ENCOMSP_PARTICIPANT_REMOVED_PDU(Structure):
    pass

class struct_ENCOMSP_CHANGE_PARTICIPANT_CONTROL_LEVEL_PDU(Structure):
    pass

class struct_ENCOMSP_GRAPHICS_STREAM_PAUSED_PDU(Structure):
    pass

class struct_ENCOMSP_GRAPHICS_STREAM_RESUMED_PDU(Structure):
    pass

struct_s_encomsp_client_context._pack_ = 1 # source:False
struct_s_encomsp_client_context._fields_ = [
    ('handle', ctypes.POINTER(None)),
    ('custom', ctypes.POINTER(None)),
    ('FilterUpdated', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_FILTER_UPDATED_PDU))),
    ('ApplicationCreated', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_APPLICATION_CREATED_PDU))),
    ('ApplicationRemoved', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_APPLICATION_REMOVED_PDU))),
    ('WindowCreated', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_WINDOW_CREATED_PDU))),
    ('WindowRemoved', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_WINDOW_REMOVED_PDU))),
    ('ShowWindow', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_SHOW_WINDOW_PDU))),
    ('ParticipantCreated', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_PARTICIPANT_CREATED_PDU))),
    ('ParticipantRemoved', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_PARTICIPANT_REMOVED_PDU))),
    ('ChangeParticipantControlLevel', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_CHANGE_PARTICIPANT_CONTROL_LEVEL_PDU))),
    ('GraphicsStreamPaused', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_GRAPHICS_STREAM_PAUSED_PDU))),
    ('GraphicsStreamResumed', ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(struct_s_encomsp_client_context), ctypes.POINTER(struct_ENCOMSP_GRAPHICS_STREAM_RESUMED_PDU))),
    ('participantId', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

struct_ENCOMSP_FILTER_UPDATED_PDU._pack_ = 1 # source:False
struct_ENCOMSP_FILTER_UPDATED_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
    ('Flags', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte),
]

class struct_ENCOMSP_UNICODE_STRING(Structure):
    pass

struct_ENCOMSP_UNICODE_STRING._pack_ = 1 # source:False
struct_ENCOMSP_UNICODE_STRING._fields_ = [
    ('cchString', ctypes.c_uint16),
    ('wString', ctypes.c_uint16 * 1024),
]

struct_ENCOMSP_APPLICATION_CREATED_PDU._pack_ = 1 # source:False
struct_ENCOMSP_APPLICATION_CREATED_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
    ('Flags', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('AppId', ctypes.c_uint32),
    ('Name', struct_ENCOMSP_UNICODE_STRING),
    ('PADDING_1', ctypes.c_ubyte * 2),
]

struct_ENCOMSP_APPLICATION_REMOVED_PDU._pack_ = 1 # source:False
struct_ENCOMSP_APPLICATION_REMOVED_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
    ('AppId', ctypes.c_uint32),
]

struct_ENCOMSP_WINDOW_CREATED_PDU._pack_ = 1 # source:False
struct_ENCOMSP_WINDOW_CREATED_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
    ('Flags', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('AppId', ctypes.c_uint32),
    ('WndId', ctypes.c_uint32),
    ('Name', struct_ENCOMSP_UNICODE_STRING),
    ('PADDING_1', ctypes.c_ubyte * 2),
]

struct_ENCOMSP_WINDOW_REMOVED_PDU._pack_ = 1 # source:False
struct_ENCOMSP_WINDOW_REMOVED_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
    ('WndId', ctypes.c_uint32),
]

struct_ENCOMSP_SHOW_WINDOW_PDU._pack_ = 1 # source:False
struct_ENCOMSP_SHOW_WINDOW_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
    ('WndId', ctypes.c_uint32),
]

struct_ENCOMSP_PARTICIPANT_CREATED_PDU._pack_ = 1 # source:False
struct_ENCOMSP_PARTICIPANT_CREATED_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
    ('ParticipantId', ctypes.c_uint32),
    ('GroupId', ctypes.c_uint32),
    ('Flags', ctypes.c_uint16),
    ('FriendlyName', struct_ENCOMSP_UNICODE_STRING),
]

struct_ENCOMSP_PARTICIPANT_REMOVED_PDU._pack_ = 1 # source:False
struct_ENCOMSP_PARTICIPANT_REMOVED_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
    ('ParticipantId', ctypes.c_uint32),
    ('DiscType', ctypes.c_uint32),
    ('DiscCode', ctypes.c_uint32),
]

struct_ENCOMSP_CHANGE_PARTICIPANT_CONTROL_LEVEL_PDU._pack_ = 1 # source:False
struct_ENCOMSP_CHANGE_PARTICIPANT_CONTROL_LEVEL_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
    ('Flags', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('ParticipantId', ctypes.c_uint32),
]

struct_ENCOMSP_GRAPHICS_STREAM_PAUSED_PDU._pack_ = 1 # source:False
struct_ENCOMSP_GRAPHICS_STREAM_PAUSED_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
]

struct_ENCOMSP_GRAPHICS_STREAM_RESUMED_PDU._pack_ = 1 # source:False
struct_ENCOMSP_GRAPHICS_STREAM_RESUMED_PDU._fields_ = [
    ('Type', ctypes.c_uint16),
    ('Length', ctypes.c_uint16),
]

try:
    freerdp_client_context_free = _libraries['FIXME_STUB'].freerdp_client_context_free
    freerdp_client_context_free.restype = None
    freerdp_client_context_free.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_client_context_new = _libraries['FIXME_STUB'].freerdp_client_context_new
    freerdp_client_context_new.restype = ctypes.POINTER(struct_rdp_context)
    freerdp_client_context_new.argtypes = [ctypes.POINTER(struct_rdp_client_entry_points_v1)]
except AttributeError:
    pass
try:
    freerdp_client_start = _libraries['FIXME_STUB'].freerdp_client_start
    freerdp_client_start.restype = ctypes.c_int32
    freerdp_client_start.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_client_stop = _libraries['FIXME_STUB'].freerdp_client_stop
    freerdp_client_stop.restype = ctypes.c_int32
    freerdp_client_stop.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_client_get_instance = _libraries['FIXME_STUB'].freerdp_client_get_instance
    freerdp_client_get_instance.restype = ctypes.POINTER(struct_rdp_freerdp)
    freerdp_client_get_instance.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
HANDLE = ctypes.POINTER(None)
try:
    freerdp_client_get_thread = _libraries['FIXME_STUB'].freerdp_client_get_thread
    freerdp_client_get_thread.restype = HANDLE
    freerdp_client_get_thread.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
BOOL = ctypes.c_int32
try:
    freerdp_client_settings_parse_command_line = _libraries['FIXME_STUB'].freerdp_client_settings_parse_command_line
    freerdp_client_settings_parse_command_line.restype = ctypes.c_int32
    freerdp_client_settings_parse_command_line.argtypes = [ctypes.POINTER(struct_rdp_settings), ctypes.c_int32, ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), BOOL]
except AttributeError:
    pass
class struct_COMMAND_LINE_ARGUMENT_A(Structure):
    pass

struct_COMMAND_LINE_ARGUMENT_A._pack_ = 1 # source:False
struct_COMMAND_LINE_ARGUMENT_A._fields_ = [
    ('Name', ctypes.POINTER(ctypes.c_char)),
    ('Flags', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('Format', ctypes.POINTER(ctypes.c_char)),
    ('Default', ctypes.POINTER(ctypes.c_char)),
    ('Value', ctypes.POINTER(ctypes.c_char)),
    ('Index', ctypes.c_int32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('Alias', ctypes.POINTER(ctypes.c_char)),
    ('Text', ctypes.POINTER(ctypes.c_char)),
]

size_t = ctypes.c_uint64
freerdp_command_line_handle_option_t = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_COMMAND_LINE_ARGUMENT_A), ctypes.POINTER(None))
try:
    freerdp_client_settings_parse_command_line_ex = _libraries['FIXME_STUB'].freerdp_client_settings_parse_command_line_ex
    freerdp_client_settings_parse_command_line_ex.restype = ctypes.c_int32
    freerdp_client_settings_parse_command_line_ex.argtypes = [ctypes.POINTER(struct_rdp_settings), ctypes.c_int32, ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), BOOL, ctypes.POINTER(struct_COMMAND_LINE_ARGUMENT_A), size_t, freerdp_command_line_handle_option_t, ctypes.POINTER(None)]
except AttributeError:
    pass
try:
    freerdp_client_settings_parse_connection_file = _libraries['FIXME_STUB'].freerdp_client_settings_parse_connection_file
    freerdp_client_settings_parse_connection_file.restype = ctypes.c_int32
    freerdp_client_settings_parse_connection_file.argtypes = [ctypes.POINTER(struct_rdp_settings), ctypes.POINTER(ctypes.c_char)]
except AttributeError:
    pass
try:
    freerdp_client_settings_parse_connection_file_buffer = _libraries['FIXME_STUB'].freerdp_client_settings_parse_connection_file_buffer
    freerdp_client_settings_parse_connection_file_buffer.restype = ctypes.c_int32
    freerdp_client_settings_parse_connection_file_buffer.argtypes = [ctypes.POINTER(struct_rdp_settings), ctypes.POINTER(ctypes.c_ubyte), size_t]
except AttributeError:
    pass
try:
    freerdp_client_settings_write_connection_file = _libraries['FIXME_STUB'].freerdp_client_settings_write_connection_file
    freerdp_client_settings_write_connection_file.restype = ctypes.c_int32
    freerdp_client_settings_write_connection_file.argtypes = [ctypes.POINTER(struct_rdp_settings), ctypes.POINTER(ctypes.c_char), BOOL]
except AttributeError:
    pass
try:
    freerdp_client_settings_parse_assistance_file = _libraries['FIXME_STUB'].freerdp_client_settings_parse_assistance_file
    freerdp_client_settings_parse_assistance_file.restype = ctypes.c_int32
    freerdp_client_settings_parse_assistance_file.argtypes = [ctypes.POINTER(struct_rdp_settings), ctypes.c_int32, ctypes.POINTER(ctypes.c_char) * 0]
except AttributeError:
    pass
try:
    client_cli_authenticate_ex = _libraries['FIXME_STUB'].client_cli_authenticate_ex
    client_cli_authenticate_ex.restype = BOOL
    client_cli_authenticate_ex.argtypes = [ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), rdp_auth_reason]
except AttributeError:
    pass
DWORD = ctypes.c_uint32
try:
    client_cli_choose_smartcard = _libraries['FIXME_STUB'].client_cli_choose_smartcard
    client_cli_choose_smartcard.restype = BOOL
    client_cli_choose_smartcard.argtypes = [ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.POINTER(struct_SmartcardCertInfo_st)), DWORD, ctypes.POINTER(ctypes.c_uint32), BOOL]
except AttributeError:
    pass
UINT32 = ctypes.c_uint32
try:
    client_cli_logon_error_info = _libraries['FIXME_STUB'].client_cli_logon_error_info
    client_cli_logon_error_info.restype = ctypes.c_int32
    client_cli_logon_error_info.argtypes = [ctypes.POINTER(struct_rdp_freerdp), UINT32, UINT32]
except AttributeError:
    pass
try:
    client_cli_get_access_token = _libraries['FIXME_STUB'].client_cli_get_access_token
    client_cli_get_access_token.restype = BOOL
    client_cli_get_access_token.argtypes = [ctypes.POINTER(struct_rdp_freerdp), AccessTokenType, ctypes.POINTER(ctypes.POINTER(ctypes.c_char)), size_t]
except AttributeError:
    pass
try:
    client_common_get_access_token = _libraries['FIXME_STUB'].client_common_get_access_token
    client_common_get_access_token.restype = BOOL
    client_common_get_access_token.argtypes = [ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.POINTER(ctypes.c_char))]
except AttributeError:
    pass
SSIZE_T = ctypes.c_int64
try:
    client_common_retry_dialog = _libraries['FIXME_STUB'].client_common_retry_dialog
    client_common_retry_dialog.restype = SSIZE_T
    client_common_retry_dialog.argtypes = [ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), size_t, ctypes.POINTER(None)]
except AttributeError:
    pass
try:
    client_common_save_session_info = _libraries['FIXME_STUB'].client_common_save_session_info
    client_common_save_session_info.restype = BOOL
    client_common_save_session_info.argtypes = [ctypes.POINTER(struct_rdp_context), UINT32, ctypes.POINTER(None)]
except AttributeError:
    pass
class struct_ChannelConnectedEventArgs(Structure):
    pass

class struct_wEventArgs(Structure):
    pass

struct_wEventArgs._pack_ = 1 # source:False
struct_wEventArgs._fields_ = [
    ('Size', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('Sender', ctypes.POINTER(ctypes.c_char)),
]

struct_ChannelConnectedEventArgs._pack_ = 1 # source:False
struct_ChannelConnectedEventArgs._fields_ = [
    ('e', struct_wEventArgs),
    ('name', ctypes.POINTER(ctypes.c_char)),
    ('pInterface', ctypes.POINTER(None)),
]

try:
    freerdp_client_OnChannelConnectedEventHandler = _libraries['FIXME_STUB'].freerdp_client_OnChannelConnectedEventHandler
    freerdp_client_OnChannelConnectedEventHandler.restype = None
    freerdp_client_OnChannelConnectedEventHandler.argtypes = [ctypes.POINTER(None), ctypes.POINTER(struct_ChannelConnectedEventArgs)]
except AttributeError:
    pass
class struct_ChannelDisconnectedEventArgs(Structure):
    pass

struct_ChannelDisconnectedEventArgs._pack_ = 1 # source:False
struct_ChannelDisconnectedEventArgs._fields_ = [
    ('e', struct_wEventArgs),
    ('name', ctypes.POINTER(ctypes.c_char)),
    ('pInterface', ctypes.POINTER(None)),
]

try:
    freerdp_client_OnChannelDisconnectedEventHandler = _libraries['FIXME_STUB'].freerdp_client_OnChannelDisconnectedEventHandler
    freerdp_client_OnChannelDisconnectedEventHandler.restype = None
    freerdp_client_OnChannelDisconnectedEventHandler.argtypes = [ctypes.POINTER(None), ctypes.POINTER(struct_ChannelDisconnectedEventArgs)]
except AttributeError:
    pass
UINT16 = ctypes.c_uint16
try:
    client_cli_verify_certificate_ex = _libraries['FIXME_STUB'].client_cli_verify_certificate_ex
    client_cli_verify_certificate_ex.restype = DWORD
    client_cli_verify_certificate_ex.argtypes = [ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), UINT16, ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), DWORD]
except AttributeError:
    pass
try:
    client_cli_verify_changed_certificate_ex = _libraries['FIXME_STUB'].client_cli_verify_changed_certificate_ex
    client_cli_verify_changed_certificate_ex.restype = DWORD
    client_cli_verify_changed_certificate_ex.argtypes = [ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(ctypes.c_char), UINT16, ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), DWORD]
except AttributeError:
    pass
try:
    client_cli_present_gateway_message = _libraries['FIXME_STUB'].client_cli_present_gateway_message
    client_cli_present_gateway_message.restype = BOOL
    client_cli_present_gateway_message.argtypes = [ctypes.POINTER(struct_rdp_freerdp), UINT32, BOOL, BOOL, size_t, ctypes.POINTER(ctypes.c_uint16)]
except AttributeError:
    pass
try:
    client_auto_reconnect = _libraries['FIXME_STUB'].client_auto_reconnect
    client_auto_reconnect.restype = BOOL
    client_auto_reconnect.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    client_auto_reconnect_ex = _libraries['FIXME_STUB'].client_auto_reconnect_ex
    client_auto_reconnect_ex.restype = BOOL
    client_auto_reconnect_ex.argtypes = [ctypes.POINTER(struct_rdp_freerdp), ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(struct_rdp_freerdp))]
except AttributeError:
    pass

# values for enumeration 'FreeRDPTouchEventType'
FreeRDPTouchEventType__enumvalues = {
    1: 'FREERDP_TOUCH_DOWN',
    2: 'FREERDP_TOUCH_UP',
    4: 'FREERDP_TOUCH_MOTION',
    8: 'FREERDP_TOUCH_CANCEL',
    256: 'FREERDP_TOUCH_HAS_PRESSURE',
}
FREERDP_TOUCH_DOWN = 1
FREERDP_TOUCH_UP = 2
FREERDP_TOUCH_MOTION = 4
FREERDP_TOUCH_CANCEL = 8
FREERDP_TOUCH_HAS_PRESSURE = 256
FreeRDPTouchEventType = ctypes.c_uint32 # enum
INT32 = ctypes.c_int32
try:
    freerdp_client_handle_touch = _libraries['FIXME_STUB'].freerdp_client_handle_touch
    freerdp_client_handle_touch.restype = BOOL
    freerdp_client_handle_touch.argtypes = [ctypes.POINTER(struct_rdp_client_context), UINT32, INT32, UINT32, INT32, INT32]
except AttributeError:
    pass

# values for enumeration 'FreeRDPPenEventType'
FreeRDPPenEventType__enumvalues = {
    1: 'FREERDP_PEN_REGISTER',
    2: 'FREERDP_PEN_ERASER_PRESSED',
    4: 'FREERDP_PEN_PRESS',
    8: 'FREERDP_PEN_MOTION',
    16: 'FREERDP_PEN_RELEASE',
    32: 'FREERDP_PEN_BARREL_PRESSED',
    64: 'FREERDP_PEN_HAS_PRESSURE',
    128: 'FREERDP_PEN_HAS_ROTATION',
    256: 'FREERDP_PEN_HAS_TILTX',
    512: 'FREERDP_PEN_HAS_TILTY',
    1024: 'FREERDP_PEN_IS_INVERTED',
}
FREERDP_PEN_REGISTER = 1
FREERDP_PEN_ERASER_PRESSED = 2
FREERDP_PEN_PRESS = 4
FREERDP_PEN_MOTION = 8
FREERDP_PEN_RELEASE = 16
FREERDP_PEN_BARREL_PRESSED = 32
FREERDP_PEN_HAS_PRESSURE = 64
FREERDP_PEN_HAS_ROTATION = 128
FREERDP_PEN_HAS_TILTX = 256
FREERDP_PEN_HAS_TILTY = 512
FREERDP_PEN_IS_INVERTED = 1024
FreeRDPPenEventType = ctypes.c_uint32 # enum
try:
    freerdp_client_handle_pen = _libraries['FIXME_STUB'].freerdp_client_handle_pen
    freerdp_client_handle_pen.restype = BOOL
    freerdp_client_handle_pen.argtypes = [ctypes.POINTER(struct_rdp_client_context), UINT32, INT32]
except AttributeError:
    pass
try:
    freerdp_client_is_pen = _libraries['FIXME_STUB'].freerdp_client_is_pen
    freerdp_client_is_pen.restype = BOOL
    freerdp_client_is_pen.argtypes = [ctypes.POINTER(struct_rdp_client_context), INT32]
except AttributeError:
    pass
try:
    freerdp_client_pen_cancel_all = _libraries['FIXME_STUB'].freerdp_client_pen_cancel_all
    freerdp_client_pen_cancel_all.restype = BOOL
    freerdp_client_pen_cancel_all.argtypes = [ctypes.POINTER(struct_rdp_client_context)]
except AttributeError:
    pass
try:
    freerdp_client_send_wheel_event = _libraries['FIXME_STUB'].freerdp_client_send_wheel_event
    freerdp_client_send_wheel_event.restype = BOOL
    freerdp_client_send_wheel_event.argtypes = [ctypes.POINTER(struct_rdp_client_context), UINT16]
except AttributeError:
    pass
try:
    freerdp_client_use_relative_mouse_events = _libraries['FIXME_STUB'].freerdp_client_use_relative_mouse_events
    freerdp_client_use_relative_mouse_events.restype = BOOL
    freerdp_client_use_relative_mouse_events.argtypes = [ctypes.POINTER(struct_rdp_client_context)]
except AttributeError:
    pass
try:
    freerdp_client_send_button_event = _libraries['FIXME_STUB'].freerdp_client_send_button_event
    freerdp_client_send_button_event.restype = BOOL
    freerdp_client_send_button_event.argtypes = [ctypes.POINTER(struct_rdp_client_context), BOOL, UINT16, INT32, INT32]
except AttributeError:
    pass
try:
    freerdp_client_send_extended_button_event = _libraries['FIXME_STUB'].freerdp_client_send_extended_button_event
    freerdp_client_send_extended_button_event.restype = BOOL
    freerdp_client_send_extended_button_event.argtypes = [ctypes.POINTER(struct_rdp_client_context), BOOL, UINT16, INT32, INT32]
except AttributeError:
    pass
try:
    freerdp_client_common_stop = _libraries['FIXME_STUB'].freerdp_client_common_stop
    freerdp_client_common_stop.restype = ctypes.c_int32
    freerdp_client_common_stop.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_client_load_channels = _libraries['FIXME_STUB'].freerdp_client_load_channels
    freerdp_client_load_channels.restype = BOOL
    freerdp_client_load_channels.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_client_encomsp_toggle_control = _libraries['FIXME_STUB'].freerdp_client_encomsp_toggle_control
    freerdp_client_encomsp_toggle_control.restype = BOOL
    freerdp_client_encomsp_toggle_control.argtypes = [ctypes.POINTER(struct_s_encomsp_client_context)]
except AttributeError:
    pass
try:
    freerdp_client_encomsp_set_control = _libraries['FIXME_STUB'].freerdp_client_encomsp_set_control
    freerdp_client_encomsp_set_control.restype = BOOL
    freerdp_client_encomsp_set_control.argtypes = [ctypes.POINTER(struct_s_encomsp_client_context), BOOL]
except AttributeError:
    pass

# values for enumeration 'freerdp_client_aad_type'
freerdp_client_aad_type__enumvalues = {
    0: 'FREERDP_CLIENT_AAD_AUTH_REQUEST',
    1: 'FREERDP_CLIENT_AAD_TOKEN_REQUEST',
    2: 'FREERDP_CLIENT_AAD_AVD_AUTH_REQUEST',
    3: 'FREERDP_CLIENT_AAD_AVD_TOKEN_REQUEST',
}
FREERDP_CLIENT_AAD_AUTH_REQUEST = 0
FREERDP_CLIENT_AAD_TOKEN_REQUEST = 1
FREERDP_CLIENT_AAD_AVD_AUTH_REQUEST = 2
FREERDP_CLIENT_AAD_AVD_TOKEN_REQUEST = 3
freerdp_client_aad_type = ctypes.c_uint32 # enum
try:
    freerdp_client_get_aad_url = _libraries['FIXME_STUB'].freerdp_client_get_aad_url
    freerdp_client_get_aad_url.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_client_get_aad_url.argtypes = [ctypes.POINTER(struct_rdp_client_context), freerdp_client_aad_type]
except AttributeError:
    pass
class struct_rdp_channel_handles(Structure):
    pass

class struct_s_wListDictionary(Structure):
    pass

struct_rdp_channel_handles._pack_ = 1 # source:False
struct_rdp_channel_handles._fields_ = [
    ('init', ctypes.POINTER(struct_s_wListDictionary)),
    ('open', ctypes.POINTER(struct_s_wListDictionary)),
]

rdpChannelHandles = struct_rdp_channel_handles
try:
    freerdp_context_free = _libraries['FIXME_STUB'].freerdp_context_free
    freerdp_context_free.restype = None
    freerdp_context_free.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_context_new = _libraries['FIXME_STUB'].freerdp_context_new
    freerdp_context_new.restype = BOOL
    freerdp_context_new.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_context_new_ex = _libraries['FIXME_STUB'].freerdp_context_new_ex
    freerdp_context_new_ex.restype = BOOL
    freerdp_context_new_ex.argtypes = [ctypes.POINTER(struct_rdp_freerdp), ctypes.POINTER(struct_rdp_settings)]
except AttributeError:
    pass
try:
    freerdp_context_reset = _libraries['FIXME_STUB'].freerdp_context_reset
    freerdp_context_reset.restype = BOOL
    freerdp_context_reset.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_connect = _libraries['FIXME_STUB'].freerdp_connect
    freerdp_connect.restype = BOOL
    freerdp_connect.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_abort_connect = _libraries['FIXME_STUB'].freerdp_abort_connect
    freerdp_abort_connect.restype = BOOL
    freerdp_abort_connect.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_abort_connect_context = _libraries['FIXME_STUB'].freerdp_abort_connect_context
    freerdp_abort_connect_context.restype = BOOL
    freerdp_abort_connect_context.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_abort_event = _libraries['FIXME_STUB'].freerdp_abort_event
    freerdp_abort_event.restype = HANDLE
    freerdp_abort_event.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_shall_disconnect = _libraries['FIXME_STUB'].freerdp_shall_disconnect
    freerdp_shall_disconnect.restype = BOOL
    freerdp_shall_disconnect.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_shall_disconnect_context = _libraries['FIXME_STUB'].freerdp_shall_disconnect_context
    freerdp_shall_disconnect_context.restype = BOOL
    freerdp_shall_disconnect_context.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_disconnect = _libraries['FIXME_STUB'].freerdp_disconnect
    freerdp_disconnect.restype = BOOL
    freerdp_disconnect.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_disconnect_reason_string = _libraries['FIXME_STUB'].freerdp_disconnect_reason_string
    freerdp_disconnect_reason_string.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_disconnect_reason_string.argtypes = [ctypes.c_int32]
except AttributeError:
    pass
try:
    freerdp_disconnect_before_reconnect = _libraries['FIXME_STUB'].freerdp_disconnect_before_reconnect
    freerdp_disconnect_before_reconnect.restype = BOOL
    freerdp_disconnect_before_reconnect.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_disconnect_before_reconnect_context = _libraries['FIXME_STUB'].freerdp_disconnect_before_reconnect_context
    freerdp_disconnect_before_reconnect_context.restype = BOOL
    freerdp_disconnect_before_reconnect_context.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_reconnect = _libraries['FIXME_STUB'].freerdp_reconnect
    freerdp_reconnect.restype = BOOL
    freerdp_reconnect.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
UINT = ctypes.c_uint32
try:
    freerdp_channels_attach = _libraries['FIXME_STUB'].freerdp_channels_attach
    freerdp_channels_attach.restype = UINT
    freerdp_channels_attach.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_channels_detach = _libraries['FIXME_STUB'].freerdp_channels_detach
    freerdp_channels_detach.restype = UINT
    freerdp_channels_detach.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_check_fds = _libraries['FIXME_STUB'].freerdp_check_fds
    freerdp_check_fds.restype = BOOL
    freerdp_check_fds.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_get_event_handles = _libraries['FIXME_STUB'].freerdp_get_event_handles
    freerdp_get_event_handles.restype = DWORD
    freerdp_get_event_handles.argtypes = [ctypes.POINTER(struct_rdp_context), ctypes.POINTER(ctypes.POINTER(None)), DWORD]
except AttributeError:
    pass
try:
    freerdp_check_event_handles = _libraries['FIXME_STUB'].freerdp_check_event_handles
    freerdp_check_event_handles.restype = BOOL
    freerdp_check_event_handles.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
class struct_s_wMessageQueue(Structure):
    pass

try:
    freerdp_get_message_queue = _libraries['FIXME_STUB'].freerdp_get_message_queue
    freerdp_get_message_queue.restype = ctypes.POINTER(struct_s_wMessageQueue)
    freerdp_get_message_queue.argtypes = [ctypes.POINTER(struct_rdp_freerdp), DWORD]
except AttributeError:
    pass
try:
    freerdp_get_message_queue_event_handle = _libraries['FIXME_STUB'].freerdp_get_message_queue_event_handle
    freerdp_get_message_queue_event_handle.restype = HANDLE
    freerdp_get_message_queue_event_handle.argtypes = [ctypes.POINTER(struct_rdp_freerdp), DWORD]
except AttributeError:
    pass
class struct_s_wMessage(Structure):
    pass

struct_s_wMessage._pack_ = 1 # source:False
struct_s_wMessage._fields_ = [
    ('id', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('context', ctypes.POINTER(None)),
    ('wParam', ctypes.POINTER(None)),
    ('lParam', ctypes.POINTER(None)),
    ('time', ctypes.c_uint64),
    ('Free', ctypes.CFUNCTYPE(None, ctypes.POINTER(struct_s_wMessage))),
]

try:
    freerdp_message_queue_process_message = _libraries['FIXME_STUB'].freerdp_message_queue_process_message
    freerdp_message_queue_process_message.restype = ctypes.c_int32
    freerdp_message_queue_process_message.argtypes = [ctypes.POINTER(struct_rdp_freerdp), DWORD, ctypes.POINTER(struct_s_wMessage)]
except AttributeError:
    pass
try:
    freerdp_message_queue_process_pending_messages = _libraries['FIXME_STUB'].freerdp_message_queue_process_pending_messages
    freerdp_message_queue_process_pending_messages.restype = ctypes.c_int32
    freerdp_message_queue_process_pending_messages.argtypes = [ctypes.POINTER(struct_rdp_freerdp), DWORD]
except AttributeError:
    pass
try:
    freerdp_error_info = _libraries['FIXME_STUB'].freerdp_error_info
    freerdp_error_info.restype = UINT32
    freerdp_error_info.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_set_error_info = _libraries['FIXME_STUB'].freerdp_set_error_info
    freerdp_set_error_info.restype = None
    freerdp_set_error_info.argtypes = [ctypes.POINTER(struct_rdp_rdp), UINT32]
except AttributeError:
    pass
try:
    freerdp_send_error_info = _libraries['FIXME_STUB'].freerdp_send_error_info
    freerdp_send_error_info.restype = BOOL
    freerdp_send_error_info.argtypes = [ctypes.POINTER(struct_rdp_rdp)]
except AttributeError:
    pass
try:
    freerdp_get_stats = _libraries['FIXME_STUB'].freerdp_get_stats
    freerdp_get_stats.restype = BOOL
    freerdp_get_stats.argtypes = [ctypes.POINTER(struct_rdp_rdp), ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
except AttributeError:
    pass
try:
    freerdp_get_version = _libraries['FIXME_STUB'].freerdp_get_version
    freerdp_get_version.restype = None
    freerdp_get_version.argtypes = [ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32)]
except AttributeError:
    pass
try:
    freerdp_get_version_string = _libraries['FIXME_STUB'].freerdp_get_version_string
    freerdp_get_version_string.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_get_version_string.argtypes = []
except AttributeError:
    pass
try:
    freerdp_get_build_revision = _libraries['FIXME_STUB'].freerdp_get_build_revision
    freerdp_get_build_revision.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_get_build_revision.argtypes = []
except AttributeError:
    pass
try:
    freerdp_get_build_config = _libraries['FIXME_STUB'].freerdp_get_build_config
    freerdp_get_build_config.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_get_build_config.argtypes = []
except AttributeError:
    pass
try:
    freerdp_free = _libraries['FIXME_STUB'].freerdp_free
    freerdp_free.restype = None
    freerdp_free.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_new = _libraries['FIXME_STUB'].freerdp_new
    freerdp_new.restype = ctypes.POINTER(struct_rdp_freerdp)
    freerdp_new.argtypes = []
except AttributeError:
    pass
try:
    freerdp_focus_required = _libraries['FIXME_STUB'].freerdp_focus_required
    freerdp_focus_required.restype = BOOL
    freerdp_focus_required.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_set_focus = _libraries['FIXME_STUB'].freerdp_set_focus
    freerdp_set_focus.restype = None
    freerdp_set_focus.argtypes = [ctypes.POINTER(struct_rdp_freerdp)]
except AttributeError:
    pass
try:
    freerdp_get_disconnect_ultimatum = _libraries['FIXME_STUB'].freerdp_get_disconnect_ultimatum
    freerdp_get_disconnect_ultimatum.restype = ctypes.c_int32
    freerdp_get_disconnect_ultimatum.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_get_last_error = _libraries['FIXME_STUB'].freerdp_get_last_error
    freerdp_get_last_error.restype = UINT32
    freerdp_get_last_error.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_get_last_error_name = _libraries['FIXME_STUB'].freerdp_get_last_error_name
    freerdp_get_last_error_name.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_get_last_error_name.argtypes = [UINT32]
except AttributeError:
    pass
try:
    freerdp_get_last_error_string = _libraries['FIXME_STUB'].freerdp_get_last_error_string
    freerdp_get_last_error_string.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_get_last_error_string.argtypes = [UINT32]
except AttributeError:
    pass
try:
    freerdp_get_last_error_category = _libraries['FIXME_STUB'].freerdp_get_last_error_category
    freerdp_get_last_error_category.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_get_last_error_category.argtypes = [UINT32]
except AttributeError:
    pass
try:
    freerdp_set_last_error_ex = _libraries['FIXME_STUB'].freerdp_set_last_error_ex
    freerdp_set_last_error_ex.restype = None
    freerdp_set_last_error_ex.argtypes = [ctypes.POINTER(struct_rdp_context), UINT32, ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_char), ctypes.c_int32]
except AttributeError:
    pass
try:
    freerdp_get_logon_error_info_type = _libraries['FIXME_STUB'].freerdp_get_logon_error_info_type
    freerdp_get_logon_error_info_type.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_get_logon_error_info_type.argtypes = [UINT32]
except AttributeError:
    pass
try:
    freerdp_get_logon_error_info_type_ex = _libraries['FIXME_STUB'].freerdp_get_logon_error_info_type_ex
    freerdp_get_logon_error_info_type_ex.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_get_logon_error_info_type_ex.argtypes = [UINT32, ctypes.POINTER(ctypes.c_char), size_t]
except AttributeError:
    pass
try:
    freerdp_get_logon_error_info_data = _libraries['FIXME_STUB'].freerdp_get_logon_error_info_data
    freerdp_get_logon_error_info_data.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_get_logon_error_info_data.argtypes = [UINT32]
except AttributeError:
    pass
try:
    freerdp_get_logon_error_info_data_ex = _libraries['FIXME_STUB'].freerdp_get_logon_error_info_data_ex
    freerdp_get_logon_error_info_data_ex.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_get_logon_error_info_data_ex.argtypes = [UINT32, ctypes.POINTER(ctypes.c_char), size_t]
except AttributeError:
    pass
ULONG = ctypes.c_uint32
try:
    freerdp_get_transport_sent = _libraries['FIXME_STUB'].freerdp_get_transport_sent
    freerdp_get_transport_sent.restype = ULONG
    freerdp_get_transport_sent.argtypes = [ctypes.POINTER(struct_rdp_context), BOOL]
except AttributeError:
    pass
try:
    freerdp_nla_impersonate = _libraries['FIXME_STUB'].freerdp_nla_impersonate
    freerdp_nla_impersonate.restype = BOOL
    freerdp_nla_impersonate.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_nla_revert_to_self = _libraries['FIXME_STUB'].freerdp_nla_revert_to_self
    freerdp_nla_revert_to_self.restype = BOOL
    freerdp_nla_revert_to_self.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_get_nla_sspi_error = _libraries['FIXME_STUB'].freerdp_get_nla_sspi_error
    freerdp_get_nla_sspi_error.restype = UINT32
    freerdp_get_nla_sspi_error.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
class struct_SecBuffer(Structure):
    pass

struct_SecBuffer._pack_ = 1 # source:False
struct_SecBuffer._fields_ = [
    ('cbBuffer', ctypes.c_uint32),
    ('BufferType', ctypes.c_uint32),
    ('pvBuffer', ctypes.POINTER(None)),
]

try:
    freerdp_nla_encrypt = _libraries['FIXME_STUB'].freerdp_nla_encrypt
    freerdp_nla_encrypt.restype = BOOL
    freerdp_nla_encrypt.argtypes = [ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_SecBuffer), ctypes.POINTER(struct_SecBuffer)]
except AttributeError:
    pass
try:
    freerdp_nla_decrypt = _libraries['FIXME_STUB'].freerdp_nla_decrypt
    freerdp_nla_decrypt.restype = BOOL
    freerdp_nla_decrypt.argtypes = [ctypes.POINTER(struct_rdp_context), ctypes.POINTER(struct_SecBuffer), ctypes.POINTER(struct_SecBuffer)]
except AttributeError:
    pass
SECURITY_STATUS = ctypes.c_int32
PVOID = ctypes.POINTER(None)
try:
    freerdp_nla_QueryContextAttributes = _libraries['FIXME_STUB'].freerdp_nla_QueryContextAttributes
    freerdp_nla_QueryContextAttributes.restype = SECURITY_STATUS
    freerdp_nla_QueryContextAttributes.argtypes = [ctypes.POINTER(struct_rdp_context), DWORD, PVOID]
except AttributeError:
    pass
try:
    freerdp_nla_FreeContextBuffer = _libraries['FIXME_STUB'].freerdp_nla_FreeContextBuffer
    freerdp_nla_FreeContextBuffer.restype = SECURITY_STATUS
    freerdp_nla_FreeContextBuffer.argtypes = [ctypes.POINTER(struct_rdp_context), PVOID]
except AttributeError:
    pass
try:
    clearChannelError = _libraries['FIXME_STUB'].clearChannelError
    clearChannelError.restype = None
    clearChannelError.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    getChannelErrorEventHandle = _libraries['FIXME_STUB'].getChannelErrorEventHandle
    getChannelErrorEventHandle.restype = HANDLE
    getChannelErrorEventHandle.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    getChannelError = _libraries['FIXME_STUB'].getChannelError
    getChannelError.restype = UINT
    getChannelError.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    getChannelErrorDescription = _libraries['FIXME_STUB'].getChannelErrorDescription
    getChannelErrorDescription.restype = ctypes.POINTER(ctypes.c_char)
    getChannelErrorDescription.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    setChannelError = _libraries['FIXME_STUB'].setChannelError
    setChannelError.restype = None
    setChannelError.argtypes = [ctypes.POINTER(struct_rdp_context), UINT, ctypes.POINTER(ctypes.c_char)]
except AttributeError:
    pass
try:
    checkChannelErrorEvent = _libraries['FIXME_STUB'].checkChannelErrorEvent
    checkChannelErrorEvent.restype = BOOL
    checkChannelErrorEvent.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_nego_get_routing_token = _libraries['FIXME_STUB'].freerdp_nego_get_routing_token
    freerdp_nego_get_routing_token.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_nego_get_routing_token.argtypes = [ctypes.POINTER(struct_rdp_context), ctypes.POINTER(ctypes.c_uint32)]
except AttributeError:
    pass

# values for enumeration 'CONNECTION_STATE'
CONNECTION_STATE__enumvalues = {
    0: 'CONNECTION_STATE_INITIAL',
    1: 'CONNECTION_STATE_NEGO',
    2: 'CONNECTION_STATE_NLA',
    3: 'CONNECTION_STATE_AAD',
    4: 'CONNECTION_STATE_MCS_CREATE_REQUEST',
    5: 'CONNECTION_STATE_MCS_CREATE_RESPONSE',
    6: 'CONNECTION_STATE_MCS_ERECT_DOMAIN',
    7: 'CONNECTION_STATE_MCS_ATTACH_USER',
    8: 'CONNECTION_STATE_MCS_ATTACH_USER_CONFIRM',
    9: 'CONNECTION_STATE_MCS_CHANNEL_JOIN_REQUEST',
    10: 'CONNECTION_STATE_MCS_CHANNEL_JOIN_RESPONSE',
    11: 'CONNECTION_STATE_RDP_SECURITY_COMMENCEMENT',
    12: 'CONNECTION_STATE_SECURE_SETTINGS_EXCHANGE',
    13: 'CONNECTION_STATE_CONNECT_TIME_AUTO_DETECT_REQUEST',
    14: 'CONNECTION_STATE_CONNECT_TIME_AUTO_DETECT_RESPONSE',
    15: 'CONNECTION_STATE_LICENSING',
    16: 'CONNECTION_STATE_MULTITRANSPORT_BOOTSTRAPPING_REQUEST',
    17: 'CONNECTION_STATE_MULTITRANSPORT_BOOTSTRAPPING_RESPONSE',
    18: 'CONNECTION_STATE_CAPABILITIES_EXCHANGE_DEMAND_ACTIVE',
    19: 'CONNECTION_STATE_CAPABILITIES_EXCHANGE_MONITOR_LAYOUT',
    20: 'CONNECTION_STATE_CAPABILITIES_EXCHANGE_CONFIRM_ACTIVE',
    21: 'CONNECTION_STATE_FINALIZATION_SYNC',
    22: 'CONNECTION_STATE_FINALIZATION_COOPERATE',
    23: 'CONNECTION_STATE_FINALIZATION_REQUEST_CONTROL',
    24: 'CONNECTION_STATE_FINALIZATION_PERSISTENT_KEY_LIST',
    25: 'CONNECTION_STATE_FINALIZATION_FONT_LIST',
    26: 'CONNECTION_STATE_FINALIZATION_CLIENT_SYNC',
    27: 'CONNECTION_STATE_FINALIZATION_CLIENT_COOPERATE',
    28: 'CONNECTION_STATE_FINALIZATION_CLIENT_GRANTED_CONTROL',
    29: 'CONNECTION_STATE_FINALIZATION_CLIENT_FONT_MAP',
    30: 'CONNECTION_STATE_ACTIVE',
}
CONNECTION_STATE_INITIAL = 0
CONNECTION_STATE_NEGO = 1
CONNECTION_STATE_NLA = 2
CONNECTION_STATE_AAD = 3
CONNECTION_STATE_MCS_CREATE_REQUEST = 4
CONNECTION_STATE_MCS_CREATE_RESPONSE = 5
CONNECTION_STATE_MCS_ERECT_DOMAIN = 6
CONNECTION_STATE_MCS_ATTACH_USER = 7
CONNECTION_STATE_MCS_ATTACH_USER_CONFIRM = 8
CONNECTION_STATE_MCS_CHANNEL_JOIN_REQUEST = 9
CONNECTION_STATE_MCS_CHANNEL_JOIN_RESPONSE = 10
CONNECTION_STATE_RDP_SECURITY_COMMENCEMENT = 11
CONNECTION_STATE_SECURE_SETTINGS_EXCHANGE = 12
CONNECTION_STATE_CONNECT_TIME_AUTO_DETECT_REQUEST = 13
CONNECTION_STATE_CONNECT_TIME_AUTO_DETECT_RESPONSE = 14
CONNECTION_STATE_LICENSING = 15
CONNECTION_STATE_MULTITRANSPORT_BOOTSTRAPPING_REQUEST = 16
CONNECTION_STATE_MULTITRANSPORT_BOOTSTRAPPING_RESPONSE = 17
CONNECTION_STATE_CAPABILITIES_EXCHANGE_DEMAND_ACTIVE = 18
CONNECTION_STATE_CAPABILITIES_EXCHANGE_MONITOR_LAYOUT = 19
CONNECTION_STATE_CAPABILITIES_EXCHANGE_CONFIRM_ACTIVE = 20
CONNECTION_STATE_FINALIZATION_SYNC = 21
CONNECTION_STATE_FINALIZATION_COOPERATE = 22
CONNECTION_STATE_FINALIZATION_REQUEST_CONTROL = 23
CONNECTION_STATE_FINALIZATION_PERSISTENT_KEY_LIST = 24
CONNECTION_STATE_FINALIZATION_FONT_LIST = 25
CONNECTION_STATE_FINALIZATION_CLIENT_SYNC = 26
CONNECTION_STATE_FINALIZATION_CLIENT_COOPERATE = 27
CONNECTION_STATE_FINALIZATION_CLIENT_GRANTED_CONTROL = 28
CONNECTION_STATE_FINALIZATION_CLIENT_FONT_MAP = 29
CONNECTION_STATE_ACTIVE = 30
CONNECTION_STATE = ctypes.c_uint32 # enum
try:
    freerdp_get_state = _libraries['FIXME_STUB'].freerdp_get_state
    freerdp_get_state.restype = CONNECTION_STATE
    freerdp_get_state.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_state_string = _libraries['FIXME_STUB'].freerdp_state_string
    freerdp_state_string.restype = ctypes.POINTER(ctypes.c_char)
    freerdp_state_string.argtypes = [CONNECTION_STATE]
except AttributeError:
    pass
try:
    freerdp_is_active_state = _libraries['FIXME_STUB'].freerdp_is_active_state
    freerdp_is_active_state.restype = BOOL
    freerdp_is_active_state.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_channels_from_mcs = _libraries['FIXME_STUB'].freerdp_channels_from_mcs
    freerdp_channels_from_mcs.restype = BOOL
    freerdp_channels_from_mcs.argtypes = [ctypes.POINTER(struct_rdp_settings), ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_is_valid_mcs_create_request = _libraries['FIXME_STUB'].freerdp_is_valid_mcs_create_request
    freerdp_is_valid_mcs_create_request.restype = BOOL
    freerdp_is_valid_mcs_create_request.argtypes = [ctypes.POINTER(ctypes.c_ubyte), size_t]
except AttributeError:
    pass
try:
    freerdp_is_valid_mcs_create_response = _libraries['FIXME_STUB'].freerdp_is_valid_mcs_create_response
    freerdp_is_valid_mcs_create_response.restype = BOOL
    freerdp_is_valid_mcs_create_response.argtypes = [ctypes.POINTER(ctypes.c_ubyte), size_t]
except AttributeError:
    pass
try:
    freerdp_persist_credentials = _libraries['FIXME_STUB'].freerdp_persist_credentials
    freerdp_persist_credentials.restype = BOOL
    freerdp_persist_credentials.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
try:
    freerdp_set_common_access_token = _libraries['FIXME_STUB'].freerdp_set_common_access_token
    freerdp_set_common_access_token.restype = BOOL
    freerdp_set_common_access_token.argtypes = [ctypes.POINTER(struct_rdp_context), pGetCommonAccessToken]
except AttributeError:
    pass
try:
    freerdp_get_common_access_token = _libraries['FIXME_STUB'].freerdp_get_common_access_token
    freerdp_get_common_access_token.restype = pGetCommonAccessToken
    freerdp_get_common_access_token.argtypes = [ctypes.POINTER(struct_rdp_context)]
except AttributeError:
    pass
struct___va_list_tag._pack_ = 1 # source:False
struct___va_list_tag._fields_ = [
    ('gp_offset', ctypes.c_uint32),
    ('fp_offset', ctypes.c_uint32),
    ('overflow_arg_area', ctypes.POINTER(None)),
    ('reg_save_area', ctypes.POINTER(None)),
]

__all__ = \
    ['ACCESS_TOKEN_TYPE_AAD', 'ACCESS_TOKEN_TYPE_AVD',
    'AUTH_FIDO_PIN', 'AUTH_NLA', 'AUTH_RDP', 'AUTH_RDSTLS',
    'AUTH_SMARTCARD_PIN', 'AUTH_TLS', 'AccessTokenType', 'BOOL',
    'CONNECTION_STATE', 'CONNECTION_STATE_AAD',
    'CONNECTION_STATE_ACTIVE',
    'CONNECTION_STATE_CAPABILITIES_EXCHANGE_CONFIRM_ACTIVE',
    'CONNECTION_STATE_CAPABILITIES_EXCHANGE_DEMAND_ACTIVE',
    'CONNECTION_STATE_CAPABILITIES_EXCHANGE_MONITOR_LAYOUT',
    'CONNECTION_STATE_CONNECT_TIME_AUTO_DETECT_REQUEST',
    'CONNECTION_STATE_CONNECT_TIME_AUTO_DETECT_RESPONSE',
    'CONNECTION_STATE_FINALIZATION_CLIENT_COOPERATE',
    'CONNECTION_STATE_FINALIZATION_CLIENT_FONT_MAP',
    'CONNECTION_STATE_FINALIZATION_CLIENT_GRANTED_CONTROL',
    'CONNECTION_STATE_FINALIZATION_CLIENT_SYNC',
    'CONNECTION_STATE_FINALIZATION_COOPERATE',
    'CONNECTION_STATE_FINALIZATION_FONT_LIST',
    'CONNECTION_STATE_FINALIZATION_PERSISTENT_KEY_LIST',
    'CONNECTION_STATE_FINALIZATION_REQUEST_CONTROL',
    'CONNECTION_STATE_FINALIZATION_SYNC', 'CONNECTION_STATE_INITIAL',
    'CONNECTION_STATE_LICENSING', 'CONNECTION_STATE_MCS_ATTACH_USER',
    'CONNECTION_STATE_MCS_ATTACH_USER_CONFIRM',
    'CONNECTION_STATE_MCS_CHANNEL_JOIN_REQUEST',
    'CONNECTION_STATE_MCS_CHANNEL_JOIN_RESPONSE',
    'CONNECTION_STATE_MCS_CREATE_REQUEST',
    'CONNECTION_STATE_MCS_CREATE_RESPONSE',
    'CONNECTION_STATE_MCS_ERECT_DOMAIN',
    'CONNECTION_STATE_MULTITRANSPORT_BOOTSTRAPPING_REQUEST',
    'CONNECTION_STATE_MULTITRANSPORT_BOOTSTRAPPING_RESPONSE',
    'CONNECTION_STATE_NEGO', 'CONNECTION_STATE_NLA',
    'CONNECTION_STATE_RDP_SECURITY_COMMENCEMENT',
    'CONNECTION_STATE_SECURE_SETTINGS_EXCHANGE', 'DWORD',
    'Disconnect_Ultimatum', 'Disconnect_Ultimatum_channel_purged',
    'Disconnect_Ultimatum_domain_disconnected',
    'Disconnect_Ultimatum_provider_initiated',
    'Disconnect_Ultimatum_token_purged',
    'Disconnect_Ultimatum_user_requested', 'FREERDP_AUTODETECT_STATE',
    'FREERDP_AUTODETECT_STATE_COMPLETE',
    'FREERDP_AUTODETECT_STATE_FAIL',
    'FREERDP_AUTODETECT_STATE_INITIAL',
    'FREERDP_AUTODETECT_STATE_REQUEST',
    'FREERDP_AUTODETECT_STATE_RESPONSE',
    'FREERDP_CLIENT_AAD_AUTH_REQUEST',
    'FREERDP_CLIENT_AAD_AVD_AUTH_REQUEST',
    'FREERDP_CLIENT_AAD_AVD_TOKEN_REQUEST',
    'FREERDP_CLIENT_AAD_TOKEN_REQUEST', 'FREERDP_PEN_BARREL_PRESSED',
    'FREERDP_PEN_ERASER_PRESSED', 'FREERDP_PEN_HAS_PRESSURE',
    'FREERDP_PEN_HAS_ROTATION', 'FREERDP_PEN_HAS_TILTX',
    'FREERDP_PEN_HAS_TILTY', 'FREERDP_PEN_IS_INVERTED',
    'FREERDP_PEN_MOTION', 'FREERDP_PEN_PRESS', 'FREERDP_PEN_REGISTER',
    'FREERDP_PEN_RELEASE', 'FREERDP_TOUCH_CANCEL',
    'FREERDP_TOUCH_DOWN', 'FREERDP_TOUCH_HAS_PRESSURE',
    'FREERDP_TOUCH_MOTION', 'FREERDP_TOUCH_UP', 'FreeRDPPenEventType',
    'FreeRDPTouchEventType', 'FreeRDP_PenDevice',
    'FreeRDP_TouchContact', 'GW_AUTH_HTTP', 'GW_AUTH_RDG',
    'GW_AUTH_RPC', 'HANDLE', 'INT32', 'MIBClientWrapper', 'PVOID',
    'RDP_CLIENT_ENTRY_POINTS', 'RDP_CLIENT_ENTRY_POINTS_V1',
    'RDP_NETCHAR_RESERVED', 'RDP_NETCHAR_RESULT_TYPE',
    'RDP_NETCHAR_RESULT_TYPE_BASE_RTT_AVG_RTT',
    'RDP_NETCHAR_RESULT_TYPE_BASE_RTT_BW_AVG_RTT',
    'RDP_NETCHAR_RESULT_TYPE_BW_AVG_RTT', 'RDP_TRANSPORT_TCP',
    'RDP_TRANSPORT_TYPE', 'RDP_TRANSPORT_UDP_L',
    'RDP_TRANSPORT_UDP_R', 'SECURITY_STATUS', 'SSIZE_T', 'UINT',
    'UINT16', 'UINT32', 'ULONG', 'checkChannelErrorEvent',
    'clearChannelError', 'client_auto_reconnect',
    'client_auto_reconnect_ex', 'client_cli_authenticate_ex',
    'client_cli_choose_smartcard', 'client_cli_get_access_token',
    'client_cli_logon_error_info',
    'client_cli_present_gateway_message',
    'client_cli_verify_certificate_ex',
    'client_cli_verify_changed_certificate_ex',
    'client_common_get_access_token', 'client_common_retry_dialog',
    'client_common_save_session_info', 'freerdp_abort_connect',
    'freerdp_abort_connect_context', 'freerdp_abort_event',
    'freerdp_channels_attach', 'freerdp_channels_detach',
    'freerdp_channels_from_mcs', 'freerdp_check_event_handles',
    'freerdp_check_fds',
    'freerdp_client_OnChannelConnectedEventHandler',
    'freerdp_client_OnChannelDisconnectedEventHandler',
    'freerdp_client_aad_type', 'freerdp_client_common_stop',
    'freerdp_client_context_free', 'freerdp_client_context_new',
    'freerdp_client_encomsp_set_control',
    'freerdp_client_encomsp_toggle_control',
    'freerdp_client_get_aad_url', 'freerdp_client_get_instance',
    'freerdp_client_get_thread', 'freerdp_client_handle_pen',
    'freerdp_client_handle_touch', 'freerdp_client_is_pen',
    'freerdp_client_load_channels', 'freerdp_client_pen_cancel_all',
    'freerdp_client_send_button_event',
    'freerdp_client_send_extended_button_event',
    'freerdp_client_send_wheel_event',
    'freerdp_client_settings_parse_assistance_file',
    'freerdp_client_settings_parse_command_line',
    'freerdp_client_settings_parse_command_line_ex',
    'freerdp_client_settings_parse_connection_file',
    'freerdp_client_settings_parse_connection_file_buffer',
    'freerdp_client_settings_write_connection_file',
    'freerdp_client_start', 'freerdp_client_stop',
    'freerdp_client_use_relative_mouse_events',
    'freerdp_command_line_handle_option_t', 'freerdp_connect',
    'freerdp_context_free', 'freerdp_context_new',
    'freerdp_context_new_ex', 'freerdp_context_reset',
    'freerdp_disconnect', 'freerdp_disconnect_before_reconnect',
    'freerdp_disconnect_before_reconnect_context',
    'freerdp_disconnect_reason_string', 'freerdp_error_info',
    'freerdp_focus_required', 'freerdp_free',
    'freerdp_get_build_config', 'freerdp_get_build_revision',
    'freerdp_get_common_access_token',
    'freerdp_get_disconnect_ultimatum', 'freerdp_get_event_handles',
    'freerdp_get_last_error', 'freerdp_get_last_error_category',
    'freerdp_get_last_error_name', 'freerdp_get_last_error_string',
    'freerdp_get_logon_error_info_data',
    'freerdp_get_logon_error_info_data_ex',
    'freerdp_get_logon_error_info_type',
    'freerdp_get_logon_error_info_type_ex',
    'freerdp_get_message_queue',
    'freerdp_get_message_queue_event_handle',
    'freerdp_get_nla_sspi_error', 'freerdp_get_state',
    'freerdp_get_stats', 'freerdp_get_transport_sent',
    'freerdp_get_version', 'freerdp_get_version_string',
    'freerdp_is_active_state', 'freerdp_is_valid_mcs_create_request',
    'freerdp_is_valid_mcs_create_response',
    'freerdp_message_queue_process_message',
    'freerdp_message_queue_process_pending_messages',
    'freerdp_nego_get_routing_token', 'freerdp_new',
    'freerdp_nla_FreeContextBuffer',
    'freerdp_nla_QueryContextAttributes', 'freerdp_nla_decrypt',
    'freerdp_nla_encrypt', 'freerdp_nla_impersonate',
    'freerdp_nla_revert_to_self', 'freerdp_persist_credentials',
    'freerdp_reconnect', 'freerdp_send_error_info',
    'freerdp_set_common_access_token', 'freerdp_set_error_info',
    'freerdp_set_focus', 'freerdp_set_last_error_ex',
    'freerdp_shall_disconnect', 'freerdp_shall_disconnect_context',
    'freerdp_state_string', 'getChannelError',
    'getChannelErrorDescription', 'getChannelErrorEventHandle',
    'pAuthenticate', 'pAuthenticateEx', 'pChooseSmartcard',
    'pConnectCallback', 'pContextFree', 'pContextNew',
    'pGetAccessToken', 'pGetCommonAccessToken', 'pLogonErrorInfo',
    'pPostDisconnect', 'pPresentGatewayMessage', 'pRdpClientEntry',
    'pRdpClientFree', 'pRdpClientNew', 'pRdpClientStart',
    'pRdpClientStop', 'pRdpGlobalInit', 'pRdpGlobalUninit',
    'pReceiveChannelData', 'pRetryDialog', 'pSendChannelData',
    'pSendChannelPacket', 'pVerifyCertificate',
    'pVerifyCertificateEx', 'pVerifyChangedCertificate',
    'pVerifyChangedCertificateEx', 'pVerifyX509Certificate',
    'rdpCache', 'rdpChannelHandles', 'rdpClientContext', 'rdpRail',
    'rdpRdp', 'rdp_auth_reason', 'setChannelError', 'size_t',
    'struct_ADDIN_ARGV', 'struct_ARC_CS_PRIVATE_PACKET',
    'struct_ARC_SC_PRIVATE_PACKET',
    'struct_BITMAP_CACHE_V2_CELL_INFO', 'struct_BITMAP_DATA',
    'struct_BITMAP_DATA_EX', 'struct_BITMAP_UPDATE',
    'struct_CACHED_ICON_INFO', 'struct_CACHE_BITMAP_ORDER',
    'struct_CACHE_BITMAP_V2_ORDER', 'struct_CACHE_BITMAP_V3_ORDER',
    'struct_CACHE_BRUSH_ORDER', 'struct_CACHE_COLOR_TABLE_ORDER',
    'struct_CACHE_GLYPH_ORDER', 'struct_CACHE_GLYPH_V2_ORDER',
    'struct_COMMAND_LINE_ARGUMENT_A',
    'struct_CREATE_NINE_GRID_BITMAP_ORDER',
    'struct_CREATE_OFFSCREEN_BITMAP_ORDER',
    'struct_ChannelConnectedEventArgs',
    'struct_ChannelDisconnectedEventArgs', 'struct_DELTA_POINT',
    'struct_DELTA_RECT', 'struct_DRAW_GDIPLUS_CACHE_END_ORDER',
    'struct_DRAW_GDIPLUS_CACHE_FIRST_ORDER',
    'struct_DRAW_GDIPLUS_CACHE_NEXT_ORDER',
    'struct_DRAW_GDIPLUS_END_ORDER',
    'struct_DRAW_GDIPLUS_FIRST_ORDER',
    'struct_DRAW_GDIPLUS_NEXT_ORDER', 'struct_DRAW_NINE_GRID_ORDER',
    'struct_DSTBLT_ORDER', 'struct_ELLIPSE_CB_ORDER',
    'struct_ELLIPSE_SC_ORDER',
    'struct_ENCOMSP_APPLICATION_CREATED_PDU',
    'struct_ENCOMSP_APPLICATION_REMOVED_PDU',
    'struct_ENCOMSP_CHANGE_PARTICIPANT_CONTROL_LEVEL_PDU',
    'struct_ENCOMSP_FILTER_UPDATED_PDU',
    'struct_ENCOMSP_GRAPHICS_STREAM_PAUSED_PDU',
    'struct_ENCOMSP_GRAPHICS_STREAM_RESUMED_PDU',
    'struct_ENCOMSP_PARTICIPANT_CREATED_PDU',
    'struct_ENCOMSP_PARTICIPANT_REMOVED_PDU',
    'struct_ENCOMSP_SHOW_WINDOW_PDU', 'struct_ENCOMSP_UNICODE_STRING',
    'struct_ENCOMSP_WINDOW_CREATED_PDU',
    'struct_ENCOMSP_WINDOW_REMOVED_PDU', 'struct_FAST_GLYPH_ORDER',
    'struct_FAST_INDEX_ORDER', 'struct_FRAME_MARKER_ORDER',
    'struct_FREERDP_RGNDATA', 'struct_FreeRDP_TouchContact',
    'struct_GDIOBJECT', 'struct_GDI_BITMAP', 'struct_GDI_BRUSH',
    'struct_GDI_DC', 'struct_GDI_PEN', 'struct_GDI_RGN',
    'struct_GDI_WND', 'struct_GLYPH_CACHE_DEFINITION',
    'struct_GLYPH_DATA', 'struct_GLYPH_DATA_V2',
    'struct_GLYPH_INDEX_ORDER', 'struct_ICON_INFO',
    'struct_LINE_TO_ORDER', 'struct_MEM3BLT_ORDER',
    'struct_MEMBLT_ORDER', 'struct_MIBClientWrapper',
    'struct_MONITORED_DESKTOP_ORDER', 'struct_MONITOR_ATTRIBUTES',
    'struct_MONITOR_DEF', 'struct_MULTI_DRAW_NINE_GRID_ORDER',
    'struct_MULTI_DSTBLT_ORDER', 'struct_MULTI_OPAQUE_RECT_ORDER',
    'struct_MULTI_PATBLT_ORDER', 'struct_MULTI_SCRBLT_ORDER',
    'struct_NINE_GRID_BITMAP_INFO', 'struct_NOTIFY_ICON_INFOTIP',
    'struct_NOTIFY_ICON_STATE_ORDER', 'struct_OFFSCREEN_DELETE_LIST',
    'struct_OPAQUE_RECT_ORDER', 'struct_ORDER_INFO',
    'struct_PALETTE_ENTRY', 'struct_PALETTE_UPDATE',
    'struct_PATBLT_ORDER', 'struct_PERSISTENT_CACHE_ENTRY',
    'struct_PLAY_SOUND_UPDATE', 'struct_POINTER_CACHED_UPDATE',
    'struct_POINTER_COLOR_UPDATE', 'struct_POINTER_LARGE_UPDATE',
    'struct_POINTER_NEW_UPDATE', 'struct_POINTER_POSITION_UPDATE',
    'struct_POINTER_SYSTEM_UPDATE', 'struct_POLYGON_CB_ORDER',
    'struct_POLYGON_SC_ORDER', 'struct_POLYLINE_ORDER',
    'struct_RAIL_UNICODE_STRING', 'struct_RDPDR_DEVICE',
    'struct_RDPGFX_CACHE_ENTRY_METADATA',
    'struct_RDPGFX_CACHE_IMPORT_OFFER_PDU',
    'struct_RDPGFX_CACHE_IMPORT_REPLY_PDU',
    'struct_RDPGFX_CACHE_TO_SURFACE_PDU', 'struct_RDPGFX_CAPSET',
    'struct_RDPGFX_CAPS_ADVERTISE_PDU',
    'struct_RDPGFX_CAPS_CONFIRM_PDU', 'struct_RDPGFX_COLOR32',
    'struct_RDPGFX_CREATE_SURFACE_PDU',
    'struct_RDPGFX_DELETE_ENCODING_CONTEXT_PDU',
    'struct_RDPGFX_DELETE_SURFACE_PDU', 'struct_RDPGFX_END_FRAME_PDU',
    'struct_RDPGFX_EVICT_CACHE_ENTRY_PDU',
    'struct_RDPGFX_FRAME_ACKNOWLEDGE_PDU',
    'struct_RDPGFX_MAP_SURFACE_TO_OUTPUT_PDU',
    'struct_RDPGFX_MAP_SURFACE_TO_SCALED_OUTPUT_PDU',
    'struct_RDPGFX_MAP_SURFACE_TO_SCALED_WINDOW_PDU',
    'struct_RDPGFX_MAP_SURFACE_TO_WINDOW_PDU',
    'struct_RDPGFX_POINT16',
    'struct_RDPGFX_QOE_FRAME_ACKNOWLEDGE_PDU',
    'struct_RDPGFX_RESET_GRAPHICS_PDU',
    'struct_RDPGFX_SOLID_FILL_PDU', 'struct_RDPGFX_START_FRAME_PDU',
    'struct_RDPGFX_SURFACE_COMMAND',
    'struct_RDPGFX_SURFACE_TO_CACHE_PDU',
    'struct_RDPGFX_SURFACE_TO_SURFACE_PDU',
    'struct_RDPINPUT_CONTACT_DATA', 'struct_RDPINPUT_PEN_CONTACT',
    'struct_RDP_RECT', 'struct_RECTANGLE_16',
    'struct_RTL_CRITICAL_SECTION', 'struct_SAVE_BITMAP_ORDER',
    'struct_SCRBLT_ORDER', 'struct_STREAM_BITMAP_FIRST_ORDER',
    'struct_STREAM_BITMAP_NEXT_ORDER', 'struct_SURFACE_BITS_COMMAND',
    'struct_SURFACE_FRAME_MARKER', 'struct_SWITCH_SURFACE_ORDER',
    'struct_S_BITMAP_INTERLEAVED_CONTEXT',
    'struct_S_BITMAP_PLANAR_CONTEXT', 'struct_S_CLEAR_CONTEXT',
    'struct_S_H264_CONTEXT', 'struct_S_MAPPED_GEOMETRY',
    'struct_S_NSC_CONTEXT', 'struct_S_PROGRESSIVE_CONTEXT',
    'struct_S_RFX_CONTEXT', 'struct_SecBuffer',
    'struct_SmartcardCertInfo_st', 'struct_SmartcardKeyInfo_st',
    'struct_TIME_ZONE_INFORMATION', 'struct_TS_BITMAP_DATA_EX',
    'struct_TS_COMPRESSED_BITMAP_HEADER_EX', 'struct_VideoSurface',
    'struct_WINDOW_CACHED_ICON_ORDER', 'struct_WINDOW_ICON_ORDER',
    'struct_WINDOW_ORDER_INFO', 'struct_WINDOW_STATE_ORDER',
    'struct___va_list_tag', 'struct_ainput_client_context',
    'struct_gdi_bitmap', 'struct_gdi_gfx_surface',
    'struct_gdi_palette', 'struct_pen_device', 'struct_rdpMonitor',
    'struct_rdp_altsec_update', 'struct_rdp_autodetect',
    'struct_rdp_bitmap', 'struct_rdp_bounds', 'struct_rdp_brush',
    'struct_rdp_cache', 'struct_rdp_certificate',
    'struct_rdp_channel_handles', 'struct_rdp_channels',
    'struct_rdp_client_context', 'struct_rdp_client_entry_points_v1',
    'struct_rdp_codecs', 'struct_rdp_context', 'struct_rdp_freerdp',
    'struct_rdp_freerdp_peer', 'struct_rdp_gdi', 'struct_rdp_glyph',
    'struct_rdp_graphics', 'struct_rdp_heartbeat', 'struct_rdp_input',
    'struct_rdp_metrics', 'struct_rdp_network_characteristics_result',
    'struct_rdp_pointer', 'struct_rdp_pointer_update',
    'struct_rdp_primary_update', 'struct_rdp_private_key',
    'struct_rdp_rail', 'struct_rdp_rdp',
    'struct_rdp_secondary_update', 'struct_rdp_settings',
    'struct_rdp_update', 'struct_rdp_window_update',
    'struct_s_SYSTEMTIME', 'struct_s_VideoClientContext',
    'struct_s_VideoClientContextPriv',
    'struct_s_encomsp_client_context',
    'struct_s_geometry_client_context',
    'struct_s_rdpei_client_context', 'struct_s_rdpgfx_client_context',
    'struct_s_wHashTable', 'struct_s_wListDictionary',
    'struct_s_wLog', 'struct_s_wMessage', 'struct_s_wMessageQueue',
    'struct_s_wPubSub', 'struct_s_wStreamPool',
    'struct_stream_dump_context', 'struct_tagCHANNEL_DEF',
    'struct_wEventArgs', 'struct_wStream']
