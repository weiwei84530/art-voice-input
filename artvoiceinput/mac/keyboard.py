"""macOS: the clipboard (NSPasteboard) and keystrokes (CGEventPost). output.py holds the logic both platforms share
and calls these. Keys come as Windows virtual-key codes (keys.py) and are translated here. Every event we post
carries system.MARK, so our own taps let it through and do not take it for the user's."""
import Quartz as Q
from AppKit import NSPasteboard, NSPasteboardTypeString

from .system import MARK, logical

# Windows virtual-key code -> macOS key code (kVK_*)
VK_TO_MAC = {
    0x08: 51, 0x09: 48, 0x0D: 36, 0x10: 56, 0x11: 59, 0x12: 58, 0x14: 57, 0x1B: 53, 0x20: 49,
    0x21: 116, 0x22: 121, 0x23: 119, 0x24: 115, 0x25: 123, 0x26: 126, 0x27: 124, 0x28: 125,
    0x2D: 114, 0x2E: 117, 0x5B: 55, 0x5C: 54, 0xA0: 56, 0xA1: 60, 0xA2: 59, 0xA3: 62, 0xA4: 58, 0xA5: 61,
    0xBA: 41, 0xBB: 24, 0xBC: 43, 0xBD: 27, 0xBE: 47, 0xBF: 44, 0xC0: 50, 0xDB: 33, 0xDC: 42, 0xDD: 30, 0xDE: 39,
}
VK_TO_MAC.update(dict(zip(range(0x30, 0x3A), (29, 18, 19, 20, 21, 23, 22, 26, 28, 25))))   # 0-9
VK_TO_MAC.update(dict(zip(range(0x41, 0x5B), (0, 11, 8, 2, 14, 3, 5, 4, 34, 38, 40, 37, 46, 45, 31, 35, 12, 15,
                                               1, 17, 32, 9, 13, 7, 16, 6))))           # A-Z
_F_KEYS = (122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, 105, 107, 113, 106, 64, 79, 80, 90)
VK_TO_MAC.update({0x70 + i: code for i, code in enumerate(_F_KEYS)})                    # F1-F20
# the user's keys: the generic Shift / Ctrl / Alt / Win come as their left or right one
MAC_TO_VK = {code: vk for vk, code in VK_TO_MAC.items() if vk not in (0x10, 0x11, 0x12)}
MAC_TO_VK.update({56: 0xA0, 60: 0xA1, 59: 0xA2, 62: 0xA3, 58: 0xA4, 61: 0xA5, 55: 0x5B, 54: 0x5C})
UNMAPPED = 0x1000   # a key with no Windows counterpart: UNMAPPED + its macOS key code (a hotkey may still be one)

_MODIFIER_FLAGS = {0x10: Q.kCGEventFlagMaskShift, 0xA0: Q.kCGEventFlagMaskShift, 0xA1: Q.kCGEventFlagMaskShift,
                   0x11: Q.kCGEventFlagMaskControl, 0xA2: Q.kCGEventFlagMaskControl,
                   0xA3: Q.kCGEventFlagMaskControl,
                   0x12: Q.kCGEventFlagMaskAlternate, 0xA4: Q.kCGEventFlagMaskAlternate,
                   0xA5: Q.kCGEventFlagMaskAlternate,
                   0x5B: Q.kCGEventFlagMaskCommand, 0x5C: Q.kCGEventFlagMaskCommand}
# arrows and the navigation keys are function-row / keypad keys on a Mac keyboard: real presses carry these flags
_ARROW = Q.kCGEventFlagMaskNumericPad | Q.kCGEventFlagMaskSecondaryFn
_NAV = {123: _ARROW, 124: _ARROW, 125: _ARROW, 126: _ARROW,
        115: Q.kCGEventFlagMaskSecondaryFn, 116: Q.kCGEventFlagMaskSecondaryFn, 117: Q.kCGEventFlagMaskSecondaryFn,
        119: Q.kCGEventFlagMaskSecondaryFn, 121: Q.kCGEventFlagMaskSecondaryFn}
# mouse button VK (keys.MOUSE_VKS) -> (down type, up type, button number): right, middle, back, forward
_MOUSE = {0x02: (Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp, 1),
          0x04: (Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp, 2),
          0x05: (Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp, 3),
          0x06: (Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp, 4)}
_source = None


def _src():
    """A private event source: the modifiers the user holds do not leak into our keys."""
    global _source
    if _source is None:
        _source = Q.CGEventSourceCreate(Q.kCGEventSourceStatePrivate)
    return _source


def _post(e) -> None:
    Q.CGEventSetIntegerValueField(e, Q.kCGEventSourceUserData, MARK)
    Q.CGEventPost(Q.kCGHIDEventTap, e)


def post_key(code: int, down: bool, flags: int = 0) -> None:
    e = Q.CGEventCreateKeyboardEvent(_src(), code, down)
    Q.CGEventSetFlags(e, flags | _NAV.get(code, 0))
    _post(e)


def _click(vk: int, down: bool) -> None:
    down_type, up_type, number = _MOUSE[vk]
    pt = Q.CGEventGetLocation(Q.CGEventCreate(None))
    e = Q.CGEventCreateMouseEvent(_src(), down_type if down else up_type, pt, min(number, 2))
    Q.CGEventSetIntegerValueField(e, Q.kCGMouseEventButtonNumber, number)
    _post(e)


# nspasteboard.org's marker: clipboard managers leave out what a paste only borrowed the clipboard for
TRANSIENT = "org.nspasteboard.TransientType"


def set_clipboard(text: str) -> bool:
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    ok = bool(pb.setString_forType_(text, NSPasteboardTypeString))
    if ok:
        pb.setString_forType_("", TRANSIENT)
    return ok


def clipboard_seq() -> int:
    """A number that changes whenever anything puts something on the clipboard."""
    return int(NSPasteboard.generalPasteboard().changeCount())


def send_paste() -> None:
    """Command+V."""
    press_chord(0x5B, 0x56)


def press_delete() -> None:
    """Forward delete: deletes the selection."""
    press_key(0x2E, 1)


def press_key(vk: int, n: int) -> None:
    code = VK_TO_MAC.get(vk)
    if code is None:
        return
    for _ in range(n):
        post_key(code, True)
        post_key(code, False)


def press_chord(*vks: int) -> None:
    """Modifiers become the flags of the other keys (Shift+Enter: Enter with the Shift flag); a mouse button's VK is
    clicked where the pointer is."""
    flags = 0
    for vk in vks:
        flags |= _MODIFIER_FLAGS.get(vk, 0)
    keys = [vk for vk in vks if vk not in _MODIFIER_FLAGS and (vk in VK_TO_MAC or vk in _MOUSE)]
    for vk in keys:
        _click(vk, True) if vk in _MOUSE else post_key(VK_TO_MAC[vk], True, flags)
    for vk in reversed(keys):
        _click(vk, False) if vk in _MOUSE else post_key(VK_TO_MAC[vk], False, flags)


_REPLAY = {0x201: (Q.kCGEventLeftMouseDown, 0), 0x202: (Q.kCGEventLeftMouseUp, 0),
           0x204: (Q.kCGEventRightMouseDown, 1), 0x205: (Q.kCGEventRightMouseUp, 1)}


def replay(events: list) -> None:
    """Input held back by a tap sent again in its order: ("key", vk, down) or ("mouse", msg, x, y) (physical
    pixels); the pointer goes back where it is now."""
    now = Q.CGEventGetLocation(Q.CGEventCreate(None))
    moved = False
    for ev in events:
        if ev[0] == "key":
            _, vk, down = ev
            code = VK_TO_MAC.get(vk, vk - UNMAPPED if vk >= UNMAPPED else None)
            if code is not None:
                post_key(code, down)
            continue
        _, msg, x, y = ev
        etype, button = _REPLAY[msg]
        e = Q.CGEventCreateMouseEvent(_src(), etype, logical(x, y), button)
        _post(e)
        moved = True
    if moved:
        Q.CGWarpMouseCursorPosition(now)
