"""Global hooks for the hotkey that turns listening on and off (config.hotkey, keys.parse_hotkey).

A press of it is one tap (2026-10-17, the user's choice: no hold or double tap given back to the key, nothing to
wait for): a keyboard key or mouse button fires at its press and is suppressed, down and up, so the app under it
never sees it. A modifier alone (右 Ctrl) fires at its release when nothing else was pressed while it was down, and
is not suppressed, so it still works in combinations. When Alt or Win took part, an unassigned key (0xE8) is sent
before they come up, so a menu bar or the Start menu does not open (AutoHotkey's menu mask).

capture() takes the next press instead (the settings' 麥克風快捷鍵 button): any key, with the modifiers held, or a
mouse button but the left one; Esc or a left click cancels. Injected events (our own keystrokes) always pass.
"""
import ctypes

from pynput import keyboard, mouse

from .keys import MOD_OF, hotkey_spec, parse_hotkey, vk_main
from .output import _INPUT, _KEYBDINPUT

_WM_KEYDOWN, _WM_SYSKEYDOWN = 0x0100, 0x0104
_LLKHF_INJECTED = 0x10
_LLMHF_INJECTED = 1
_ESC, _MASK = 0x1B, 0xE8
_DOWNS = {0x201: "mouse_left", 0x204: "mouse_right", 0x207: "mouse_middle", 0x20B: None}
_UPS = {0x202: "mouse_left", 0x205: "mouse_right", 0x208: "mouse_middle", 0x20C: None}


def _button(msg: int, mouse_data: int) -> tuple[str, bool] | None:
    """(button, is down) for a low-level mouse button event, None for moves and the wheel."""
    for table, down in ((_DOWNS, True), (_UPS, False)):
        if msg in table:
            name = table[msg]
            if name is None:   # XBUTTON1 / 2 in the high word of MSLLHOOKSTRUCT.mouseData
                name = {1: "mouse_x1", 2: "mouse_x2"}.get(mouse_data >> 16)
            return (name, down) if name else None
    return None


def _send(*events: tuple[int, bool]) -> None:
    """Keys (vk, is up) sent from inside the hook: no waiting (output.press_key settles after a paste first)."""
    arr = (_INPUT * len(events))()
    for i, (vk, up) in enumerate(events):
        arr[i].type = 1   # INPUT_KEYBOARD
        arr[i].ki = _KEYBDINPUT(vk, 0, 2 if up else 0, 0, None)
    ctypes.windll.user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))


class Hotkeys:
    """Calls on_tap() when the hotkey is pressed, and on_other_key(vk) for any other key the user presses."""

    def __init__(self, on_tap, on_other_key=None):
        self.on_tap = on_tap
        self.on_other_key = on_other_key
        self._mods, self._main, self._vk = frozenset(), "", None
        self._down: set[int] = set()       # modifier keys down now (the user's, not injected)
        self._swallow: set = set()         # the hotkey's key or button, down: its repeats and release suppressed
        self._lone = False                 # the hotkey, a modifier alone, is down with nothing pressed since
        self._capture = None               # capture(): called with the spec pressed, or None when cancelled
        self._cap_mod = None               # capture: a modifier pressed with nothing after it yet
        self._listener = None
        self._mouse_listener = None

    def set_hotkey(self, spec: str) -> None:
        self._mods, self._main, self._vk = parse_hotkey(spec)
        self._lone = False

    def capture(self, done) -> None:
        """The next press is reported to done(spec) (hook thread) instead of doing anything; done(None) on Esc or a
        left click."""
        self._cap_mod = None
        self._capture = done

    def cancel_capture(self) -> None:
        self._capture = None

    def _held_mods(self, but: int | None = None) -> frozenset:
        return frozenset(MOD_OF[v] for v in self._down if v != but)

    def is_bound_mouse(self, msg: int, mouse_data: int) -> bool:
        """The event is the hotkey's mouse button (suppressed: not a click)."""
        hit = _button(msg, mouse_data)
        if hit is None or hit[0] == "mouse_left":
            return False
        name, down = hit
        if self._capture is not None or name in self._swallow:
            return True
        # the app's hook may see the press before this one does
        return down and name == self._main and self._vk is None and self._held_mods() == self._mods

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

    def _finish_capture(self, spec):
        done, self._capture = self._capture, None
        if done:
            done(spec)

    # Everything is handled inside the hooks so the key can be suppressed
    def _win32_filter(self, msg, data):
        if data.flags & _LLKHF_INJECTED:
            return True
        vk, down = data.vkCode, msg in (_WM_KEYDOWN, _WM_SYSKEYDOWN)
        mods = self._held_mods(vk)
        if vk in MOD_OF:
            (self._down.add if down else self._down.discard)(vk)
        if self._capture is not None:
            self._capture_key(vk, down, mods)
            self._listener.suppress_event()
            return
        if down and vk != self._vk:
            self._lone = False   # another key: the lone modifier is part of a combination
        if not down and vk in self._swallow and vk != self._vk:   # the release of a key captured
            self._swallow.discard(vk)
            self._listener.suppress_event()
            return
        if vk == self._vk:
            if vk in MOD_OF:   # a modifier alone: a tap is its release with nothing pressed in between
                if down:
                    if not self._lone and mods == self._mods and vk not in self._swallow:
                        self._lone = True
                    self._swallow.add(vk)
                    return True
                self._swallow.discard(vk)
                if not self._lone:
                    return True
                self._lone = False
                self.on_tap()
                # its release goes out after an unassigned key: Alt or Win alone would open a menu
                _send((_MASK, False), (_MASK, True), (vk, True))
                self._listener.suppress_event()
                return
            if down:
                if vk in self._swallow:   # auto-repeat
                    self._listener.suppress_event()
                    return
                if mods == self._mods:
                    self._swallow.add(vk)
                    self._fire()
                    self._listener.suppress_event()
                    return
            elif vk in self._swallow:
                self._swallow.discard(vk)
                self._listener.suppress_event()
                return
        if down and self.on_other_key and vk not in MOD_OF:
            self.on_other_key(vk)
        return True

    def _capture_key(self, vk: int, down: bool, mods: frozenset):
        if down:
            if vk == _ESC and not mods:
                self._finish_capture(None)
            elif vk in MOD_OF:
                if self._cap_mod is None and not mods:
                    self._cap_mod = vk
            else:
                self._cap_mod = None
                self._swallow.add(vk)   # its release is not passed on either
                self._finish_capture(hotkey_spec(mods, vk_main(vk)))
        elif vk == self._cap_mod:   # a modifier pressed and released alone
            self._finish_capture(vk_main(vk))

    def _win32_mouse_filter(self, msg, data):
        if data.flags & _LLMHF_INJECTED:
            return False
        hit = _button(msg, data.mouseData)
        if hit is None:
            return False   # never passed on to pynput's (unused) callbacks
        name, down = hit
        if down:
            self._lone = False
            self._cap_mod = None
        if self._capture is not None:
            if name == "mouse_left":
                if down:
                    self._finish_capture(None)
                return False
            if down:
                self._swallow.add(name)
                self._finish_capture(hotkey_spec(self._held_mods(), name))
            else:
                self._swallow.discard(name)
            self._mouse_listener.suppress_event()
            return
        if name == self._main and self._vk is None:
            if down and self._held_mods() == self._mods:
                self._swallow.add(name)
                self._fire()
                self._mouse_listener.suppress_event()
                return
            if not down and name in self._swallow:
                self._swallow.discard(name)
                self._mouse_listener.suppress_event()
                return
        elif not down and name in self._swallow:   # a captured button's release
            self._swallow.discard(name)
            self._mouse_listener.suppress_event()
            return
        return False

    def _fire(self):
        if self._mods & {"alt", "win"}:   # Alt or Win held: their release alone would open a menu
            _send((_MASK, False), (_MASK, True))
        self.on_tap()
