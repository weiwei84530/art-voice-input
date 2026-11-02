"""Windows: the hotkey's low-level keyboard and mouse hooks (pynput's, filtered in place so an event can be
suppressed). What they decide is hotkeycore's; this module feeds it and sends the menu mask."""
import ctypes

from pynput import keyboard, mouse

from ..hotkeycore import HotkeyCore
from .keyboard import _INPUT, _KEYBDINPUT

_WM_KEYDOWN, _WM_SYSKEYDOWN = 0x0100, 0x0104
_LLKHF_INJECTED = 0x10
_LLMHF_INJECTED = 1
_MASK = 0xE8   # an unassigned key: Alt or Win released after it opens no menu


def _send(*events: tuple[int, bool]) -> None:
    """Keys (vk, is up) sent from inside the hook: no waiting (output.press_key settles after a paste first)."""
    arr = (_INPUT * len(events))()
    for i, (vk, up) in enumerate(events):
        arr[i].type = 1   # INPUT_KEYBOARD
        arr[i].ki = _KEYBDINPUT(vk, 0, 2 if up else 0, 0, None)
    ctypes.windll.user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))


def _mask(release_vk) -> bool:
    if release_vk is None:
        _send((_MASK, False), (_MASK, True))
        return False
    _send((_MASK, False), (_MASK, True), (release_vk, True))   # the release goes out after the mask
    return True


class Hotkeys(HotkeyCore):
    def __init__(self, on_tap, on_other_key=None):
        super().__init__(on_tap, on_other_key, _mask)
        self._listener = None
        self._mouse_listener = None

    def start(self) -> None:
        self._listener = keyboard.Listener(win32_event_filter=self._win32_filter)
        self._listener.daemon = True
        self._listener.start()
        self._mouse_listener = mouse.Listener(win32_event_filter=self._win32_mouse_filter)
        self._mouse_listener.daemon = True
        self._mouse_listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
        if self._mouse_listener:
            self._mouse_listener.stop()

    # Everything is handled inside the hooks so the key can be suppressed
    def _win32_filter(self, msg, data):
        if data.flags & _LLKHF_INJECTED:
            return True
        if self.key(data.vkCode, msg in (_WM_KEYDOWN, _WM_SYSKEYDOWN)):
            self._listener.suppress_event()
            return None
        return True

    def _win32_mouse_filter(self, msg, data):
        if data.flags & _LLMHF_INJECTED:
            return False
        if self.mouse(msg, data.mouseData):
            self._mouse_listener.suppress_event()
            return None
        return False   # never passed on to pynput's (unused) callbacks
