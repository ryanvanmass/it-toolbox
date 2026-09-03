"""Maps Qt key codes to PC/AT Scan Code Set 1 make codes, for the small set
of control keys that RDP servers expect as real scancode events rather
than injected Unicode text (Enter, Backspace, arrows, modifiers, ...).

These are decades-old, platform- and FreeRDP-version-independent PS/2
constants (the same table every RDP/VNC client embeds) — not something
that needs generating from a header. Anything not in this table but with
non-empty QKeyEvent.text() should go through
FreeRdpSession.send_key_unicode() instead, which sidesteps scancode/shift
mapping entirely and works correctly across keyboard layouts.

Format: Qt.Key -> (scancode, extended). `extended` marks a key that's
sent as an 0xE0-prefixed ("extended") scancode on real PC/AT keyboards —
e.g. the arrow keys and Insert/Delete/Home/End outside the numpad.
"""

from PySide6.QtCore import Qt

SCANCODES: dict[Qt.Key, tuple[int, bool]] = {
    Qt.Key.Key_Escape: (0x01, False),
    Qt.Key.Key_1: (0x02, False),
    Qt.Key.Key_2: (0x03, False),
    Qt.Key.Key_3: (0x04, False),
    Qt.Key.Key_4: (0x05, False),
    Qt.Key.Key_5: (0x06, False),
    Qt.Key.Key_6: (0x07, False),
    Qt.Key.Key_7: (0x08, False),
    Qt.Key.Key_8: (0x09, False),
    Qt.Key.Key_9: (0x0A, False),
    Qt.Key.Key_0: (0x0B, False),
    Qt.Key.Key_Minus: (0x0C, False),
    Qt.Key.Key_Equal: (0x0D, False),
    Qt.Key.Key_Backspace: (0x0E, False),
    Qt.Key.Key_Tab: (0x0F, False),
    Qt.Key.Key_Q: (0x10, False),
    Qt.Key.Key_W: (0x11, False),
    Qt.Key.Key_E: (0x12, False),
    Qt.Key.Key_R: (0x13, False),
    Qt.Key.Key_T: (0x14, False),
    Qt.Key.Key_Y: (0x15, False),
    Qt.Key.Key_U: (0x16, False),
    Qt.Key.Key_I: (0x17, False),
    Qt.Key.Key_O: (0x18, False),
    Qt.Key.Key_P: (0x19, False),
    Qt.Key.Key_BracketLeft: (0x1A, False),
    Qt.Key.Key_BracketRight: (0x1B, False),
    Qt.Key.Key_Return: (0x1C, False),
    Qt.Key.Key_Enter: (0x1C, False),
    Qt.Key.Key_Control: (0x1D, False),
    Qt.Key.Key_A: (0x1E, False),
    Qt.Key.Key_S: (0x1F, False),
    Qt.Key.Key_D: (0x20, False),
    Qt.Key.Key_F: (0x21, False),
    Qt.Key.Key_G: (0x22, False),
    Qt.Key.Key_H: (0x23, False),
    Qt.Key.Key_J: (0x24, False),
    Qt.Key.Key_K: (0x25, False),
    Qt.Key.Key_L: (0x26, False),
    Qt.Key.Key_Semicolon: (0x27, False),
    Qt.Key.Key_Apostrophe: (0x28, False),
    Qt.Key.Key_QuoteLeft: (0x29, False),
    Qt.Key.Key_Shift: (0x2A, False),
    Qt.Key.Key_Backslash: (0x2B, False),
    Qt.Key.Key_Z: (0x2C, False),
    Qt.Key.Key_X: (0x2D, False),
    Qt.Key.Key_C: (0x2E, False),
    Qt.Key.Key_V: (0x2F, False),
    Qt.Key.Key_B: (0x30, False),
    Qt.Key.Key_N: (0x31, False),
    Qt.Key.Key_M: (0x32, False),
    Qt.Key.Key_Comma: (0x33, False),
    Qt.Key.Key_Period: (0x34, False),
    Qt.Key.Key_Slash: (0x35, False),
    Qt.Key.Key_Alt: (0x38, False),
    Qt.Key.Key_Space: (0x39, False),
    Qt.Key.Key_CapsLock: (0x3A, False),
    Qt.Key.Key_F1: (0x3B, False),
    Qt.Key.Key_F2: (0x3C, False),
    Qt.Key.Key_F3: (0x3D, False),
    Qt.Key.Key_F4: (0x3E, False),
    Qt.Key.Key_F5: (0x3F, False),
    Qt.Key.Key_F6: (0x40, False),
    Qt.Key.Key_F7: (0x41, False),
    Qt.Key.Key_F8: (0x42, False),
    Qt.Key.Key_F9: (0x43, False),
    Qt.Key.Key_F10: (0x44, False),
    Qt.Key.Key_NumLock: (0x45, False),
    Qt.Key.Key_ScrollLock: (0x46, False),
    Qt.Key.Key_F11: (0x57, False),
    Qt.Key.Key_F12: (0x58, False),
    Qt.Key.Key_Meta: (0x5B, True),
    Qt.Key.Key_Menu: (0x5D, True),
    # Extended (0xE0-prefixed) navigation cluster — the standalone keys,
    # not the numpad equivalents (which share these same base codes on a
    # real keyboard but without the extended bit; we don't model NumLock
    # off/numpad mode at all here).
    Qt.Key.Key_Insert: (0x52, True),
    Qt.Key.Key_Delete: (0x53, True),
    Qt.Key.Key_Home: (0x47, True),
    Qt.Key.Key_End: (0x4F, True),
    Qt.Key.Key_PageUp: (0x49, True),
    Qt.Key.Key_PageDown: (0x51, True),
    Qt.Key.Key_Left: (0x4B, True),
    Qt.Key.Key_Right: (0x4D, True),
    Qt.Key.Key_Up: (0x48, True),
    Qt.Key.Key_Down: (0x50, True),
}
