"""The tray icon (2026-10-21, the user's design): the app icon (`appicon`); while listening the microphone becomes a
white ring turning on the icon's square. A left click turns listening on or off, the right button opens the menu.

`promote` puts the icon on the taskbar itself instead of the ^ overflow (系統's 在工作列顯示圖示; system.promote_tray,
Windows only: the menu bar always shows it)."""
import logging

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSystemTrayIcon

from . import appicon, system

log = logging.getLogger(__name__)

SIZES = (16, 20, 24, 32, 40, 48, 64)   # drawn for each, so 16px is not a scaled-down 64px
FRAMES = 30                            # one turn of the ring
TURN_MS = 1200                         # one turn


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
        self._menu = menu
        if system.MAC:
            # a menu set on it would open at every click (the menu bar's way): a click does what it does on Windows
            # (the user's choice, 2026-11-02), the right button or Control-click opens the menu
            self.icon.activated.connect(self._activated)
        else:
            self.icon.setContextMenu(menu)
            self.icon.activated.connect(lambda r: self.clicked.emit() if r == QSystemTrayIcon.Trigger else None)

    def _activated(self, reason):
        if reason == QSystemTrayIcon.Context:
            self._menu.popup(QCursor.pos())
        elif reason == QSystemTrayIcon.Trigger:
            self.clicked.emit()

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


def promote(on: bool) -> bool:
    """The icon on the taskbar itself (True) or in the overflow; False when Windows has not listed it yet."""
    return system.promote_tray(on)
