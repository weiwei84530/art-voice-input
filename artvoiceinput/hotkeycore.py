"""What the hotkey's hooks decide, the same on both platforms (win/hotkey.py: low-level hooks; mac/hotkey.py: a
Quartz event tap). They turn each key or mouse button event the user makes into key(vk, down) / mouse(name, down),
keys as Windows virtual-key codes, and swallow the event when it returns True.

A press of the hotkey is one tap (2026-10-17, the user's choice: no hold or double tap given back to the key,
nothing to wait for): a keyboard key or mouse button fires at its press and is suppressed, down and up, so the app
under it never sees it. A modifier alone (右 Ctrl) fires at its release when nothing else was pressed while it was
down, and is not suppressed, so it still works in combinations. On Windows, when Alt or Win took part, an
unassigned key (0xE8) is sent before they come up, so a menu bar or the Start menu does not open (AutoHotkey's
menu mask; `mask`, given by the platform).

capture() takes the next press instead (the settings' 麥克風快捷鍵 button): any key, with the modifiers held, or a
mouse button but the left one; Esc or a left click cancels. Injected events (our own keystrokes) always pass: the
platform skips them before they get here.
"""
from .keys import MOD_OF, hotkey_spec, parse_hotkey, vk_main

_ESC = 0x1B
_DOWNS = {0x201: "mouse_left", 0x204: "mouse_right", 0x207: "mouse_middle", 0x20B: None}
_UPS = {0x202: "mouse_left", 0x205: "mouse_right", 0x208: "mouse_middle", 0x20C: None}


def button(msg: int, mouse_data: int) -> tuple[str, bool] | None:
    """(button, is down) for a mouse button event (WM_* code), None for moves and the wheel."""
    for table, down in ((_DOWNS, True), (_UPS, False)):
        if msg in table:
            name = table[msg]
            if name is None:   # XBUTTON1 / 2 in the high word of mouseData
                name = {1: "mouse_x1", 2: "mouse_x2"}.get(mouse_data >> 16)
            return (name, down) if name else None
    return None


class HotkeyCore:
    """Calls on_tap() when the hotkey is pressed, and on_other_key(vk) for any other key the user presses.

    mask(release_vk) is the platform's: called on a lone modifier's tap (with its vk, before its release goes out)
    and when the hotkey fires with Alt or Win held (release_vk None); it returns True when it sent the release
    itself, so the real one is swallowed."""

    def __init__(self, on_tap, on_other_key=None, mask=None):
        self.on_tap = on_tap
        self.on_other_key = on_other_key
        self.mask = mask or (lambda release_vk: False)
        self.hold = None                   # hold(vk, down) -> True: the key event is held back (not a modifier)
        self._mods, self._main, self._vk = frozenset(), "", None
        self._down: set[int] = set()       # modifier keys down now (the user's, not injected)
        self._swallow: set = set()         # the hotkey's key or button, down: its repeats and release suppressed
        self._lone = False                 # the hotkey, a modifier alone, is down with nothing pressed since
        self._capture = None               # capture(): called with the spec pressed, or None when cancelled
        self._cap_mod = None               # capture: a modifier pressed with nothing after it yet

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
        hit = button(msg, mouse_data)
        if hit is None or hit[0] == "mouse_left":
            return False
        name, down = hit
        if self._capture is not None or name in self._swallow:
            return True
        # the app's hook may see the press before this one does
        return down and name == self._main and self._vk is None and self._held_mods() == self._mods

    def _finish_capture(self, spec):
        done, self._capture = self._capture, None
        if done:
            done(spec)

    def key(self, vk: int, down: bool) -> bool:
        """A key the user pressed or released; True: swallow it."""
        mods = self._held_mods(vk)
        if vk in MOD_OF:
            (self._down.add if down else self._down.discard)(vk)
        if self._capture is not None:
            self._capture_key(vk, down, mods)
            return True
        if down and vk != self._vk:
            self._lone = False   # another key: the lone modifier is part of a combination
        if not down and vk in self._swallow and vk != self._vk:   # the release of a key captured
            self._swallow.discard(vk)
            return True
        if vk == self._vk:
            if vk in MOD_OF:   # a modifier alone: a tap is its release with nothing pressed in between
                if down:
                    if not self._lone and mods == self._mods and vk not in self._swallow:
                        self._lone = True
                    self._swallow.add(vk)
                    return False
                self._swallow.discard(vk)
                if not self._lone:
                    return False
                self._lone = False
                self.on_tap()
                return self.mask(vk)   # Alt or Win alone would open a menu
            if down:
                if vk in self._swallow:   # auto-repeat
                    return True
                if mods == self._mods:
                    self._swallow.add(vk)
                    self._fire()
                    return True
            elif vk in self._swallow:
                self._swallow.discard(vk)
                return True
        if vk not in MOD_OF and self.hold is not None and self.hold(vk, down):
            return True   # held back, sent again later (App._hold_key)
        if down and self.on_other_key and vk not in MOD_OF:
            self.on_other_key(vk)
        return False

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

    def mouse(self, msg: int, mouse_data: int) -> bool:
        """A mouse button event the user made (WM_* code); True: swallow it."""
        hit = button(msg, mouse_data)
        if hit is None:
            return False
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
            return True
        if name == self._main and self._vk is None:
            if down and self._held_mods() == self._mods:
                self._swallow.add(name)
                self._fire()
                return True
            if not down and name in self._swallow:
                self._swallow.discard(name)
                return True
        elif not down and name in self._swallow:   # a captured button's release
            self._swallow.discard(name)
            return True
        return False

    def _fire(self):
        if self._mods & {"alt", "win"}:   # Alt or Win held: their release alone would open a menu
            self.mask(None)
        self.on_tap()
