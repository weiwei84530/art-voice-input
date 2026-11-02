"""Windows: windows, focus, the mouse hook, sounds and the like (system.py picks this module or mac/system.py; both
have the same functions). Screen points are physical pixels, as the low-level hooks and UI Automation give them."""
import ctypes
import ctypes.wintypes as wt
import logging
import os
import winreg
import winsound

log = logging.getLogger("artvoiceinput")

_u32 = ctypes.windll.user32
_u32.WindowFromPoint.argtypes = [wt.POINT]
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST, _WS_EX_TRANSPARENT, _WS_EX_NOACTIVATE = 0x00000008, 0x00000020, 0x08000000
_TASKBAR = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
            "TopLevelWindowForOverflowXamlIsland", "Windows.UI.Core.CoreWindow")

# key combinations of the clipboard commands (全選 / 複製 / 剪下 / 貼上): Ctrl
SHORTCUT_MOD = 0x11


def setup(qapp) -> None:
    """Nothing to do before the first window on Windows."""


def double_click_time() -> float:
    return _u32.GetDoubleClickTime() / 1000


def foreground() -> int:
    """The foreground window: typing in another one ends what is known about the text before the caret."""
    return _u32.GetForegroundWindow()


def window_pid(hwnd) -> int:
    pid = wt.DWORD()
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def foreground_pid() -> int:
    return window_pid(foreground())


def is_ours(hwnd: int) -> bool:
    """The window is Art VoiceInput's own."""
    return window_pid(hwnd) == os.getpid()


def window_handle(widget) -> int:
    """A top-level widget's handle, for on_window (from any thread)."""
    return int(widget.winId())


def root_at(x: int, y: int) -> int:
    """The top-level window under a screen point."""
    hwnd = _u32.WindowFromPoint(wt.POINT(x, y))
    return _u32.GetAncestor(hwnd, 2) if hwnd else 0   # GA_ROOT


def on_window(handles, x: int, y: int) -> bool:
    """The screen point is on one of the windows (handles from window_handle; mouse hook thread)."""
    return root_at(x, y) in handles


def owns(handle: int, hwnd: int) -> bool:
    """hwnd is the window `handle` or a child of it."""
    return bool(hwnd) and _u32.GetAncestor(hwnd, 2) == handle   # GA_ROOT


def _ex_style(widget, add: int) -> None:
    hwnd = int(widget.winId())
    _u32.SetWindowLongW(hwnd, _GWL_EXSTYLE, _u32.GetWindowLongW(hwnd, _GWL_EXSTYLE) | add)


def no_activate(widget) -> None:
    """Clicking the window never takes the focus from the app typed into (floating button, bubble, 選字 menu)."""
    _ex_style(widget, _WS_EX_NOACTIVATE | _WS_EX_TOPMOST)


def click_through(widget) -> None:
    """Clicks pass through the window, which stays on top and never takes the focus (the glow)."""
    _ex_style(widget, _WS_EX_NOACTIVATE | _WS_EX_TRANSPARENT | _WS_EX_TOPMOST)


def dark_title(widget, dark: bool) -> None:
    """The title bar and frame drawn by Windows follow the theme (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
    v = ctypes.c_int(1 if dark else 0)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), 20, ctypes.byref(v), ctypes.sizeof(v))


def round_corners(widget) -> None:
    """Windows 11 rounds a frameless window's corners when asked (DWMWA_WINDOW_CORNER_PREFERENCE)."""
    pref = ctypes.c_int(2)   # DWMWCP_ROUND
    ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), 33, ctypes.byref(pref), ctypes.sizeof(pref))


def key_held(vk: int) -> bool:
    return bool(_u32.GetAsyncKeyState(vk) & 0x8000)


def is_taskbar(hwnd: int) -> bool:
    """The taskbar, its tray overflow or the Start menu (where a click on the tray icon puts the foreground)."""
    cls = ctypes.create_unicode_buffer(64)
    _u32.GetClassNameW(hwnd, cls, 64)
    return cls.value in _TASKBAR


def set_foreground(hwnd: int) -> None:
    _u32.SetForegroundWindow(hwnd)


def allow_set_foreground() -> None:
    """This process has the foreground: the running copy we ask to show itself may take it."""
    _u32.AllowSetForegroundWindow(-1)   # ASFW_ANY


def watch_foreground(changed):
    """changed(hwnd) on this thread whenever another window comes to the foreground. Keep what it returns."""
    proto = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_long,
                               ctypes.c_long, ctypes.c_uint32, ctypes.c_uint32)
    callback = proto(lambda _hook, _event, hwnd, *_: changed(hwnd) if hwnd else None)
    hook = _u32.SetWinEventHook(0x0003, 0x0003, None, callback, 0, 0, 0)   # EVENT_SYSTEM_FOREGROUND
    return hook, callback   # the callback must outlive the hook


def open_osk() -> bool:
    """Windows' on-screen keyboard. ShellExecute, since osk.exe asks for UI access and CreateProcess refuses it; a
    second call leaves the one already open."""
    return ctypes.windll.shell32.ShellExecuteW(None, "open", "osk.exe", None, None, 1) > 32


def play_sound(path: str) -> None:
    """Asynchronous; a new sound cuts the one playing."""
    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


def key_name(vk: int, extended: bool) -> str:
    """The keyboard layout's name of a key, "" when it has none."""
    scan = _u32.MapVirtualKeyW(vk, 4)   # MAPVK_VK_TO_VSC_EX: an extended key's scan code has 0xE0 above it
    if scan & 0xFF:
        ext = (scan >> 8) in (0xE0, 0xE1) or extended
        buf = ctypes.create_unicode_buffer(64)
        if _u32.GetKeyNameTextW(((scan & 0xFF) << 16) | ((1 << 24) if ext else 0), buf, 64):
            return buf.value
    return ""


class MouseHook:
    """A low-level mouse hook: on_event(msg, x, y, mouse_data) for every button and wheel event the user makes
    (WM_* codes, physical pixels; ours, injected, are skipped) returns True to swallow the event."""

    def __init__(self, on_event):
        from pynput import mouse

        def hook(msg, data):
            if data.flags & 1:   # LLMHF_INJECTED
                return False
            if msg == 0x200:     # a move
                return False
            if on_event(msg, data.pt.x, data.pt.y, data.mouseData):
                self._listener.suppress_event()
                return None
            return False   # never passed on to pynput's (unused) callbacks: keeps the hook cheap
        self._listener = mouse.Listener(win32_event_filter=hook)
        self._listener.daemon = True

    def start(self):
        self._listener.start()
        return self

    def stop(self):
        self._listener.stop()


def front_is(handle: int) -> bool:
    """The window `handle` (window_handle) is the foreground window."""
    return foreground() == handle


_TRAY_KEY = r"Control Panel\NotifyIconSettings"


def _exe() -> str:
    """This process's own executable: a venv's pythonw.exe starts the base interpreter, which owns the icon."""
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetModuleFileNameW(None, buf, len(buf))
    return buf.value


def promote_tray(on: bool) -> bool:
    """系統's 在工作列顯示圖示: Windows 11 keeps one key per icon under HKCU\\Control Panel\\NotifyIconSettings,
    named by Explorer once the icon has been shown, and its IsPromoted value is that choice in Windows' own settings.
    Set on this executable's entries; False when Explorer has not listed the icon yet."""
    exe, found = _exe().lower(), False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _TRAY_KEY) as root:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                with winreg.OpenKey(root, name, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
                    try:
                        path = winreg.QueryValueEx(k, "ExecutablePath")[0]
                    except OSError:
                        continue
                    if path.lower() == exe:
                        winreg.SetValueEx(k, "IsPromoted", 0, winreg.REG_DWORD, 1 if on else 0)
                        found = True
    except OSError:
        log.exception("tray promote failed")
    return found


def open_path(path) -> None:
    """A file or folder opened as Explorer would."""
    os.startfile(path)
