"""The tray icon (2026-10-21, the user's design): the app icon (`appicon`); while listening the microphone becomes a
white ring turning on the icon's square. A left click turns listening on or off, the right button opens the menu.

`promote` puts the icon on the taskbar itself instead of the ^ overflow (系統's 在工作列顯示圖示): Windows 11 keeps
one key per icon under HKCU\\Control Panel\\NotifyIconSettings, named by Explorer once the icon has been shown, and
its IsPromoted value is that choice in Windows' own settings."""
import ctypes
import logging
import winreg

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSystemTrayIcon

from . import appicon

log = logging.getLogger(__name__)

SIZES = (16, 20, 24, 32, 40, 48, 64)   # drawn for each, so 16px is not a scaled-down 64px
FRAMES = 30                            # one turn of the ring
TURN_MS = 1200                         # one turn
_KEY = r"Control Panel\NotifyIconSettings"


def _ring(s: int, turn: float) -> QPixmap:
    """A faint whole ring and a bright arc on it, `turn` 0..1 of the way round (clockwise)."""
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    appicon.tile(p, s)
    w = max(2, round(s / 8))                  # whole pixels, centred on the grid: sharp at 16px
    rad = round(s * 0.28)
    r = QRectF(s / 2 - rad, s / 2 - rad, 2 * rad, 2 * rad)
    pen = QPen(QColor(255, 255, 255, 90), w)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(r)
    pen.setColor(QColor(255, 255, 255))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawArc(r, round((90 - 360 * turn) * 16), -110 * 16)
    p.end()
    return pm


def _icon(draw) -> QIcon:
    icon = QIcon()
    for s in SIZES:
        icon.addPixmap(draw(s))
    return icon


class Tray(QObject):
    """QSystemTrayIcon with the two looks; `clicked` on a left click, the menu on the right button."""
    clicked = Signal()

    def __init__(self, menu, parent=None):
        super().__init__(parent)
        self.idle = _icon(appicon.pixmap)
        self._frames = [_icon(lambda s, i=i: _ring(s, i / FRAMES)) for i in range(FRAMES)]
        self._frame = 0
        self._step = 1
        self._timer = QTimer(self, timeout=self._turn)
        self.icon = QSystemTrayIcon(self.idle)
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(lambda reason: self.clicked.emit() if reason == QSystemTrayIcon.Trigger else None)

    def show(self):
        self.icon.show()

    def hide(self):
        self._timer.stop()
        self.icon.hide()

    def set_lite(self, lite: bool):
        """節流模式: the ring turns at half the frames."""
        self._step = 2 if lite else 1
        self._timer.setInterval(TURN_MS * self._step // FRAMES)

    def set_listening(self, on: bool):
        if on:
            self._frame = 0
            self.icon.setIcon(self._frames[0])
            self._timer.start(TURN_MS * self._step // FRAMES)
        else:
            self._timer.stop()
            self.icon.setIcon(self.idle)

    def _turn(self):
        self._frame = (self._frame + self._step) % FRAMES
        self.icon.setIcon(self._frames[self._frame])


def _exe() -> str:
    """This process's own executable: a venv's pythonw.exe starts the base interpreter, which owns the icon."""
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetModuleFileNameW(None, buf, len(buf))
    return buf.value


def promote(on: bool) -> bool:
    """Set IsPromoted on this executable's icon entries; False when Explorer has not listed the icon yet."""
    exe, found = _exe().lower(), False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as root:
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
