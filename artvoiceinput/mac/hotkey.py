"""macOS: the hotkey's event taps (keys and mouse buttons; Quartz, active, so a bound key is swallowed). What they
decide is hotkeycore's; this module turns Quartz events into Windows virtual-key codes for it.

Modifier keys come as flagsChanged events: whether one went down or up is read from its device-dependent flag (right
Option 0x40 …). CapsLock is a toggle there (no release), so as a hotkey it fires at each press. A tap of Option or
Command alone opens no menu on a Mac: no mask is sent. Taps need Accessibility (and Input Monitoring for keys);
until allowed they are tried again every 2 seconds (system.EventTap)."""
import Quartz as Q

from ..hotkeycore import HotkeyCore
from .keyboard import MAC_TO_VK, UNMAPPED
from .system import _MOUSE_TYPES, EventTap, mouse_message

# a modifier's key code -> its device-dependent flag (NX_DEVICE*KEYMASK)
_DEVICE_FLAGS = {56: 0x02, 60: 0x04, 59: 0x01, 62: 0x2000, 58: 0x20, 61: 0x40, 55: 0x08, 54: 0x10}
_CAPS = 57


class Hotkeys(HotkeyCore):
    def __init__(self, on_tap, on_other_key=None):
        super().__init__(on_tap, on_other_key, None)
        self._keys = None
        self._mouse = None

    def start(self) -> None:
        self._keys = EventTap((Q.kCGEventKeyDown, Q.kCGEventKeyUp, Q.kCGEventFlagsChanged), self._key_event,
                              "key tap").start()
        self._mouse = EventTap(_MOUSE_TYPES, self._mouse_event, "hotkey mouse tap").start()

    def stop(self) -> None:
        for tap in (self._keys, self._mouse):
            if tap is not None:
                tap.stop()

    def _key_event(self, etype, event) -> bool:
        code = Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventKeycode)
        vk = MAC_TO_VK.get(code, UNMAPPED + code)
        if etype == Q.kCGEventFlagsChanged:
            if code == _CAPS:   # a toggle: each press is a down and an up
                return self.key(vk, True) | self.key(vk, False)
            flag = _DEVICE_FLAGS.get(code)
            if flag is None:
                return False   # Fn and the like
            return self.key(vk, bool(Q.CGEventGetFlags(event) & flag))
        return self.key(vk, etype == Q.kCGEventKeyDown)

    def _mouse_event(self, etype, event) -> bool:
        m = mouse_message(etype, event)
        return m is not None and self.mouse(*m)
