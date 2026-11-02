"""macOS: windows, focus, the mouse tap, sounds and the like (system.py picks this module or win/system.py; both have
the same functions).

Screen points: the shared code works in "physical pixels" as Windows' hooks and UI Automation give them, and turns
them into Qt's logical pixels with each screen's devicePixelRatio. Quartz events and the Accessibility API give
points, which are Qt's logical pixels on a Mac, so this module hands out points scaled the same way (`physical`)
and the shared conversion undoes it.

Qt widgets are NSViews; their NSWindow is reached through pyobjc so the floating button, the bubble, the glow and
the 選字 menu behave like their Windows counterparts: never activating the app, above full-screen apps, on every
Space. The "window handles" here are process ids for other apps (what is in front) and registered widgets for ours.
"""
import logging
import os
import subprocess
import threading

import objc
import Quartz as Q
from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSApplicationActivationPolicyRegular,
                    NSColor, NSEvent, NSRunningApplication, NSSound, NSStatusWindowLevel, NSWorkspace)
from PySide6.QtCore import QPoint

log = logging.getLogger("artvoiceinput")

MARK = 0x41525456   # "ARTV": kCGEventSourceUserData of the events we post, which our own taps let through
# key combinations of the clipboard commands (全選 / 複製 / 剪下 / 貼上): Command
SHORTCUT_MOD = 0x5B

_NONACTIVATING_PANEL = 1 << 7
# NSWindowCollectionBehaviorCanJoinAllSpaces | Stationary | IgnoresCycle | FullScreenAuxiliary
_EVERYWHERE = (1 << 0) | (1 << 4) | (1 << 6) | (1 << 8)
_widgets: dict[int, object] = {}   # window_handle -> widget, for on_window on the tap's thread
_screens: list[tuple] = []         # (x, y, w, h, ratio) of each screen, logical pixels; refreshed on the main thread
_sounds: list = []                 # the NSSound playing (kept referenced until the next one)
_qapp = None


# --- screens and points ---

def _read_screens():
    global _screens
    from PySide6.QtGui import QGuiApplication
    out = []
    for s in QGuiApplication.screens():
        g = s.geometry()
        out.append((g.x(), g.y(), g.width(), g.height(), s.devicePixelRatio()))
    _screens = out


def physical(x: float, y: float) -> tuple[int, int]:
    """A point (Quartz, Accessibility) in the shared code's physical pixels."""
    for gx, gy, gw, gh, r in _screens:
        if gx <= x < gx + gw and gy <= y < gy + gh:
            return int(gx + (x - gx) * r), int(gy + (y - gy) * r)
    return int(x), int(y)


def logical(x: float, y: float) -> tuple[float, float]:
    """The other way: physical pixels back to a point."""
    for gx, gy, gw, gh, r in _screens:
        if gx <= x < gx + gw * r and gy <= y < gy + gh * r:
            return gx + (x - gx) / r, gy + (y - gy) / r
    return x, y


def physical_rect(x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
    px, py = physical(x, y)
    ex, ey = physical(x + w, y + h)
    return px, py, max(0, ex - px), max(0, ey - py)


# --- the app ---

def setup(qapp) -> None:
    """Before the first window: no Dock icon while no window shows (the user's choice, 2026-11-02: like the Windows
    tray, the menu bar icon is enough; set_dock(True) while the settings window is open), the screens read."""
    global _qapp
    _qapp = qapp
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    _read_screens()
    qapp.screenAdded.connect(lambda *_: _read_screens())
    qapp.screenRemoved.connect(lambda *_: _read_screens())
    qapp.primaryScreenChanged.connect(lambda *_: _read_screens())
    for s in qapp.screens():
        s.geometryChanged.connect(lambda *_: _read_screens())


def set_dock(shown: bool) -> None:
    """The Dock icon (and the app in Command-Tab) while the settings window is open."""
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular if shown else NSApplicationActivationPolicyAccessory)
    if shown:
        app.activateIgnoringOtherApps_(True)


def bring_to_front(widget) -> None:
    """The settings window, opened from the menu bar: an app without a Dock icon has to activate itself."""
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    widget.raise_()
    widget.activateWindow()


def double_click_time() -> float:
    return float(NSEvent.doubleClickInterval())


def foreground() -> int:
    """The app in front (its process id): typing in another app ends what is known about the text."""
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return int(app.processIdentifier()) if app is not None else 0


def window_pid(handle) -> int:
    return int(handle)


def foreground_pid() -> int:
    return foreground()


def is_ours(handle: int) -> bool:
    return handle == os.getpid() or handle in _widgets


def front_is(handle: int) -> bool:
    """Our window `handle` takes the keys: our app is active (the floating button, bubble and 選字 menu never
    activate it, so that is the settings window or the wizard)."""
    return bool(NSRunningApplication.currentApplication().isActive())


def window_handle(widget) -> int:
    handle = int(widget.winId())
    _widgets[handle] = widget
    return handle


def on_window(handles, x: int, y: int) -> bool:
    """The screen point (physical pixels) is on one of our windows (any thread)."""
    lx, ly = logical(x, y)
    pt = QPoint(int(lx), int(ly))
    for h in handles:
        w = _widgets.get(h)
        if w is not None and w.isVisible() and w.frameGeometry().contains(pt):
            return True
    return False


def owns(handle: int, other: int) -> bool:
    return handle == other


def is_taskbar(handle: int) -> bool:
    """A click on the menu bar icon leaves the app in front where it was: nothing to give back."""
    return False


def set_foreground(handle: int) -> None:
    pass


def allow_set_foreground() -> None:
    pass


def watch_foreground(changed):
    return None


def key_held(vk: int) -> bool:
    from .keyboard import VK_TO_MAC, _MODIFIER_FLAGS
    if vk in _MODIFIER_FLAGS:
        return bool(Q.CGEventSourceFlagsState(Q.kCGEventSourceStateCombinedSessionState) & _MODIFIER_FLAGS[vk])
    code = VK_TO_MAC.get(vk)
    return code is not None and bool(Q.CGEventSourceKeyState(Q.kCGEventSourceStateCombinedSessionState, code))


def key_name(vk: int, extended: bool) -> str:
    return ""


# --- our windows ---

def _window(widget):
    try:
        view = objc.objc_object(c_void_p=int(widget.winId()))
        return view.window()
    except Exception:
        log.exception("no NSWindow for %s", widget)
        return None


def _float(win) -> None:
    win.setHidesOnDeactivate_(False)
    win.setLevel_(NSStatusWindowLevel)
    win.setCollectionBehavior_(_EVERYWHERE)


def no_activate(widget) -> None:
    """Clicking the window never takes the focus from the app typed into (floating button, bubble, 選字 menu): a
    nonactivating panel above other windows and full-screen apps."""
    win = _window(widget)
    if win is None:
        return
    _float(win)
    try:
        win.setStyleMask_(win.styleMask() | _NONACTIVATING_PANEL)
        if hasattr(win, "setBecomesKeyOnlyIfNeeded_"):
            win.setBecomesKeyOnlyIfNeeded_(True)
    except Exception:
        log.debug("nonactivating style refused", exc_info=True)


def click_through(widget) -> None:
    """Clicks pass through the window, which stays on top (the glow)."""
    win = _window(widget)
    if win is not None:
        _float(win)
        win.setIgnoresMouseEvents_(True)


def dark_title(widget, dark: bool) -> None:
    """Frameless windows draw their own title: nothing to do."""


def round_corners(widget) -> None:
    """The frameless settings window gets rounded corners and the system shadow, as Windows 11 gives it."""
    win = _window(widget)
    if win is None:
        return
    try:
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        view = win.contentView()
        view.setWantsLayer_(True)
        view.layer().setCornerRadius_(10.0)
        view.layer().setMasksToBounds_(True)
        win.setHasShadow_(True)
        win.invalidateShadow()
    except Exception:
        log.debug("rounded corners refused", exc_info=True)


def promote_tray(on: bool) -> bool:
    """The menu bar always shows the icon."""
    return True


# --- sounds, files, the on-screen keyboard ---

def play_sound(path: str) -> None:
    """Asynchronous; a new sound cuts the one playing."""
    for s in _sounds:
        s.stop()
    _sounds.clear()
    sound = NSSound.alloc().initWithContentsOfFile_byReference_(path, True)
    if sound is not None:
        _sounds.append(sound)
        sound.play()


def open_path(path) -> None:
    subprocess.Popen(["open", str(path)])


def open_osk() -> bool:
    """鍵盤: the Keyboard Viewer (鍵盤檢視器)."""
    for app in ("/System/Library/Input Methods/KeyboardViewer.app",
                "/System/Library/CoreServices/Input Methods/KeyboardViewer.app"):
        if os.path.exists(app):
            subprocess.Popen(["open", "-a", app])
            return True
    return False


# --- permissions ---

_PANES = {"accessibility": "Privacy_Accessibility", "input": "Privacy_ListenEvent", "microphone": "Privacy_Microphone"}


def open_privacy(pane: str) -> None:
    subprocess.Popen(["open", f"x-apple.systempreferences:com.apple.preference.security?{_PANES[pane]}"])


def trusted(prompt: bool = False) -> bool:
    """Accessibility allowed (reading the selection, typing, the event taps); prompt: macOS's own question, which
    leads to System Settings."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))
    except Exception:
        log.exception("accessibility check failed")
        return True


def permissions(notify) -> None:
    """At launch: ask for what macOS needs the user to allow: the microphone, Accessibility (reading the selection,
    typing, the event taps) and Input Monitoring (keys in the event tap). The taps are tried again until allowed,
    so no restart is needed."""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        if status == 0:     # not determined: macOS asks
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, lambda ok: None)
        elif status in (1, 2):   # restricted / denied
            notify("麥克風沒有開放：請在「系統設定 › 隱私權與安全性 › 麥克風」打開 Art VoiceInput")
            open_privacy("microphone")
    except Exception:
        log.exception("microphone permission check failed")
    ok = trusted(prompt=True)
    try:
        if not Q.CGPreflightListenEventAccess():
            Q.CGRequestListenEventAccess()
            ok = False
    except Exception:
        log.exception("input monitoring check failed")
    if not ok:
        notify("請在「系統設定 › 隱私權與安全性」的「輔助使用」和「輸入監控」打開 Art VoiceInput")
        threading.Timer(1.0, open_privacy, ("accessibility",)).start()


# --- the mouse tap ---

class EventTap:
    """An active Quartz event tap at the session level on a thread of its own: callback(etype, event) returns True
    to swallow the event. Needs Accessibility; until it is allowed CGEventTapCreate fails and it is tried again
    every 2 seconds. Events we post ourselves (MARK) pass untouched."""

    def __init__(self, types, callback, name: str):
        self._mask = 0
        for t in types:
            self._mask |= Q.CGEventMaskBit(t)
        self._callback = callback
        self._name = name
        self._tap = None
        self._loop = None
        self._stopped = False
        self._cb = self._handle   # kept referenced while the tap lives
        self.ready = threading.Event()

    def start(self):
        threading.Thread(target=self._run, name=self._name, daemon=True).start()
        return self

    def stop(self):
        self._stopped = True
        if self._tap is not None:
            Q.CGEventTapEnable(self._tap, False)
        if self._loop is not None:
            Q.CFRunLoopStop(self._loop)

    def _run(self):
        import time
        warned = False
        while not self._stopped:
            self._tap = Q.CGEventTapCreate(Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap,
                                           Q.kCGEventTapOptionDefault, self._mask, self._cb, None)
            if self._tap is not None:
                break
            if not warned:
                log.warning("%s refused: Accessibility / Input Monitoring not allowed yet", self._name)
                warned = True
            time.sleep(2)
        if self._stopped:
            return
        log.info("%s installed", self._name)
        source = Q.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._loop = Q.CFRunLoopGetCurrent()
        Q.CFRunLoopAddSource(self._loop, source, Q.kCFRunLoopCommonModes)
        Q.CGEventTapEnable(self._tap, True)
        self.ready.set()
        Q.CFRunLoopRun()

    def _handle(self, proxy, etype, event, refcon):
        try:
            if etype in (Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput):
                Q.CGEventTapEnable(self._tap, True)   # macOS turns a slow tap off
                return event
            if Q.CGEventGetIntegerValueField(event, Q.kCGEventSourceUserData) == MARK:
                return event
            return None if self._callback(etype, event) else event
        except Exception:
            log.exception("%s callback failed", self._name)
            return event


_MOUSE_TYPES = (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp, Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp,
                Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp, Q.kCGEventScrollWheel)


def mouse_message(etype, event) -> tuple[int, int] | None:
    """(WM_* code, mouseData) of a Quartz mouse event as Windows' hook would give it, None for others."""
    if etype == Q.kCGEventLeftMouseDown:
        return 0x201, 0
    if etype == Q.kCGEventLeftMouseUp:
        return 0x202, 0
    if etype == Q.kCGEventRightMouseDown:
        return 0x204, 0
    if etype == Q.kCGEventRightMouseUp:
        return 0x205, 0
    if etype in (Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp):
        down = etype == Q.kCGEventOtherMouseDown
        n = Q.CGEventGetIntegerValueField(event, Q.kCGMouseEventButtonNumber)
        if n == 2:
            return (0x207 if down else 0x208), 0
        if n in (3, 4):   # back / forward: X1 / X2
            return (0x20B if down else 0x20C), (n - 2) << 16
        return None
    if etype == Q.kCGEventScrollWheel:
        return 0x20A, 0
    return None


class MouseHook:
    """on_event(msg, x, y, mouse_data) for every button and wheel event the user makes (WM_* codes, physical
    pixels) returns True to swallow the event."""

    def __init__(self, on_event):
        def callback(etype, event):
            m = mouse_message(etype, event)
            if m is None:
                return False
            pt = Q.CGEventGetLocation(event)
            x, y = physical(pt.x, pt.y)
            return bool(on_event(m[0], x, y, m[1]))
        self._tap = EventTap(_MOUSE_TYPES, callback, "mouse tap")

    def start(self):
        self._tap.start()
        return self

    def stop(self):
        self._tap.stop()
