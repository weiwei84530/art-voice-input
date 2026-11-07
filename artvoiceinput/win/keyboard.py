"""Windows: the clipboard (Win32, owned by a hidden window) and keystrokes (SendInput). output.py holds the logic
both platforms share and calls these."""
import ctypes
import ctypes.wintypes as wt
import time

from ..keys import EXTENDED

_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32.OpenClipboard.argtypes = [wt.HWND]
_u32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
_u32.SetClipboardData.restype = wt.HANDLE
_u32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
_u32.CreateWindowExW.restype = wt.HWND
_k32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
_k32.GlobalAlloc.restype = wt.HGLOBAL
_k32.GlobalLock.argtypes = [wt.HGLOBAL]
_k32.GlobalLock.restype = wt.LPVOID
_k32.GlobalUnlock.argtypes = [wt.HGLOBAL]
_k32.GlobalFree.argtypes = [wt.HGLOBAL]
_owner = None             # a hidden window owning what we put on the clipboard (SetClipboardData needs one)


def set_clipboard(text: str) -> bool:
    global _owner
    if _owner is None:
        _owner = _u32.CreateWindowExW(0, "STATIC", "Art VoiceInput clipboard", 0, 0, 0, 0, 0, None, None, None, None)
    for _ in range(20):
        if _u32.OpenClipboard(_owner):
            break
        time.sleep(0.01)
    else:
        return False
    try:
        _u32.EmptyClipboard()
        data = ctypes.create_unicode_buffer(text)
        h = _k32.GlobalAlloc(0x0002, ctypes.sizeof(data))   # GMEM_MOVEABLE
        p = _k32.GlobalLock(h)
        ctypes.memmove(p, data, ctypes.sizeof(data))
        _k32.GlobalUnlock(h)
        if not _u32.SetClipboardData(13, h):   # CF_UNICODETEXT; the clipboard owns h once this succeeds
            _k32.GlobalFree(h)
            return False
        for name, value in _NO_HISTORY:
            _set_bytes(_format(name), value)
        return True
    finally:
        _u32.CloseClipboard()


# Formats telling Windows' clipboard history (Win+V), cloud clipboard and clipboard managers to leave this out: every
# dictated piece used to land in Win+V's list, and the clipboard put back after it a second time (2026-11-07)
_NO_HISTORY = (("ExcludeClipboardContentFromMonitorProcessing", b"\0"),
               ("CanIncludeInClipboardHistory", b"\0\0\0\0"), ("CanUploadToCloudClipboard", b"\0\0\0\0"))
_u32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
_u32.RegisterClipboardFormatW.restype = wt.UINT
_u32.GetClipboardSequenceNumber.restype = wt.DWORD


def _format(name: str) -> int:
    return _u32.RegisterClipboardFormatW(name)


def _set_bytes(fmt: int, value: bytes) -> None:
    """While the clipboard is open."""
    h = _k32.GlobalAlloc(0x0002, len(value))
    p = _k32.GlobalLock(h)
    ctypes.memmove(p, value, len(value))
    _k32.GlobalUnlock(h)
    if not _u32.SetClipboardData(fmt, h):
        _k32.GlobalFree(h)


def clipboard_seq() -> int:
    """A number that changes whenever anything puts something on the clipboard."""
    return _u32.GetClipboardSequenceNumber()


def send_paste() -> None:
    """Ctrl+V."""
    press_chord(0x11, 0x56)


def press_delete() -> None:
    press_key(0x2E, 1)


def press_key(vk: int, n: int) -> None:
    """Press a key n times. All presses go out in one SendInput call so the app receives them
    as one burst, before the paste that usually follows."""
    if n <= 0:
        return
    ext = 1 if vk in EXTENDED else 0   # KEYEVENTF_EXTENDEDKEY: the arrow keys, not the keypad's
    events = (_INPUT * (2 * n))()
    for i in range(2 * n):
        events[i].type = 1   # INPUT_KEYBOARD
        events[i].ki = _KEYBDINPUT(vk, 0, ext | (2 if i % 2 else 0), 0, None)   # KEYEVENTF_KEYUP on odd
    ctypes.windll.user32.SendInput(len(events), events, ctypes.sizeof(_INPUT))


# mouse button VK -> (MOUSEEVENTF down flag, its up flag, mouseData): right, middle, X1, X2
_MOUSE = {0x02: (0x0008, 0x0010, 0), 0x04: (0x0020, 0x0040, 0), 0x05: (0x0080, 0x0100, 1),
          0x06: (0x0080, 0x0100, 2)}


def press_chord(*vks: int) -> None:
    """Press keys together (Shift+Enter: press_chord(0x10, 0x0D)) in one SendInput call; a mouse button's VK
    (keys.MOUSE_VKS) is clicked where the pointer is."""
    events = (_INPUT * (2 * len(vks)))()
    for i, (vk, up) in enumerate([(vk, 0) for vk in vks] + [(vk, 2) for vk in reversed(vks)]):
        if vk in _MOUSE:
            down_flag, up_flag, data = _MOUSE[vk]
            events[i].type = 0   # INPUT_MOUSE
            events[i].mi = _MOUSEINPUT(0, 0, data, up_flag if up else down_flag, 0, None)
            continue
        events[i].type = 1   # INPUT_KEYBOARD
        events[i].ki = _KEYBDINPUT(vk, 0, up | (1 if vk in EXTENDED else 0), 0, None)
    ctypes.windll.user32.SendInput(len(events), events, ctypes.sizeof(_INPUT))


def replay(events: list) -> None:
    """Input held back by a hook sent again in its order: ("key", vk, down) or ("mouse", msg, x, y) with msg a
    WM_xBUTTONDOWN / UP of the left or right button, at that point (the pointer goes back where it is now)."""
    flags = {0x201: 0x0002, 0x202: 0x0004, 0x204: 0x0008, 0x205: 0x0010}   # MOUSEEVENTF_LEFTDOWN …
    u32 = ctypes.windll.user32
    now = wt.POINT()
    u32.GetCursorPos(ctypes.byref(now))
    for ev in events:
        one = (_INPUT * 1)()
        if ev[0] == "key":
            _, vk, down = ev
            one[0].type = 1
            one[0].ki = _KEYBDINPUT(vk, 0, (0 if down else 2) | (1 if vk in EXTENDED else 0), 0, None)
        else:
            _, msg, x, y = ev
            u32.SetCursorPos(x, y)
            one[0].type = 0
            one[0].mi = _MOUSEINPUT(0, 0, 0, flags[msg], 0, None)
        u32.SendInput(1, one, ctypes.sizeof(_INPUT))
    if any(ev[0] == "mouse" for ev in events):
        u32.SetCursorPos(now.x, now.y)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _UNION)]
