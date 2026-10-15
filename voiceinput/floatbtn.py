"""The floating microphone button (2026-10-16, the user's request; a 一般 checkbox): always on top while listening is
off, a click turns listening on. It never takes focus, so the text goes to the window that had it, as with the
key. Dragged, it stays where it was dropped; its place is kept as a fraction of the screen, and it shows on the
screen the pointer is on at that same place (the user has three screens).
"""
import ctypes

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

_SIZE = 44
_GWL_EXSTYLE, _WS_EX_NOACTIVATE, _WS_EX_TOPMOST = -20, 0x08000000, 0x8


class Bubble(QWidget):
    """The small microphone bubble next to a text box the focus just came into (on_focus "bubble", 2026-10-16, the
    user's request): a click turns listening on; it goes after 5s, when the focus leaves or listening starts. Never
    takes focus."""
    clicked = Signal()
    SIZE = 28

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setToolTip("開啟麥克風")
        self._hover = False
        self._timer = QTimer(self, singleShot=True, interval=5000, timeout=self.hide)

    def hwnd(self) -> int:
        return int(self.winId())

    def show_by(self, rect):
        """rect: (x, y, w, h) in physical pixels of the text box or the terminal cursor; the bubble goes right of
        its bottom end, kept on screen."""
        x, y, w, h = (int(v) for v in rect)
        p, ratio = _logical(x + w, y + h)
        screen = QGuiApplication.screenAt(p) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        top = p.y() - self.SIZE if h / ratio > self.SIZE else p.y() - round(h / ratio / 2) - self.SIZE // 2
        self.move(min(max(p.x() + 6, a.left()), a.right() - self.SIZE), min(max(top, a.top()), a.bottom() - self.SIZE))
        self.show()
        hwnd = self.hwnd()
        u32 = ctypes.windll.user32
        u32.SetWindowLongW(hwnd, _GWL_EXSTYLE, u32.GetWindowLongW(hwnd, _GWL_EXSTYLE) | _WS_EX_NOACTIVATE | _WS_EX_TOPMOST)
        self._timer.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.SIZE / _SIZE
        p.scale(s, s)
        _paint_mic(p, self._hover)
        p.end()

    def enterEvent(self, e):
        self._hover = True
        self._timer.stop()
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self._timer.start()
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.hide()
            self.clicked.emit()


def _logical(x: int, y: int):
    for s in QGuiApplication.screens():
        g, r = s.geometry(), s.devicePixelRatio()
        if g.x() <= x < g.x() + g.width() * r and g.y() <= y < g.y() + g.height() * r:
            return QPoint(g.x() + int((x - g.x()) / r), g.y() + int((y - g.y()) / r)), r
    return QPoint(x, y), 1.0


def _paint_mic(p: QPainter, hover: bool):
    p.setPen(QPen(QColor(255, 255, 255, 60), 1))
    p.setBrush(QColor(58, 58, 68, 235) if hover else QColor(32, 32, 36, 220))
    p.drawEllipse(QRectF(1, 1, _SIZE - 2, _SIZE - 2))
    c = QColor(240, 240, 240)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(18, 10, 8, 14), 4, 4)            # mic capsule
    pen = QPen(c, 2)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(14.5, 14, 15, 14), 200 * 16, 140 * 16)   # holder
    p.drawLine(QPointF(22, 28), QPointF(22, 33))


class FloatButton(QWidget):
    clicked = Signal()
    moved = Signal(float, float)   # the new place, as fractions of the screen's free range

    def __init__(self, place=(0.98, 0.88)):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(_SIZE, _SIZE)
        self.setToolTip("開啟麥克風")
        self.place = tuple(place)
        self._screen = None
        self._press = None     # (global point, window position) while the button is down
        self._dragged = False
        self._hover = False
        self._follow = QTimer(self, interval=300, timeout=self._follow_pointer)

    def hwnd(self) -> int:
        return int(self.winId())

    def appear(self):
        if not self.isVisible():
            self._screen = None
            self._follow_pointer()
            self.show()
            hwnd = self.hwnd()
            u32 = ctypes.windll.user32
            u32.SetWindowLongW(hwnd, _GWL_EXSTYLE, u32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
                               | _WS_EX_NOACTIVATE | _WS_EX_TOPMOST)
            self._follow.start()

    def vanish(self):
        self._follow.stop()
        self.hide()

    def _follow_pointer(self):
        if self._press is not None:
            return
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is not self._screen:
            self._screen = screen
            a = screen.availableGeometry()
            fx, fy = self.place
            self.move(a.left() + round(fx * (a.width() - _SIZE)), a.top() + round(fy * (a.height() - _SIZE)))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        _paint_mic(p, self._hover)
        p.end()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = (e.globalPosition().toPoint(), self.pos())
            self._dragged = False

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        start, origin = self._press
        delta = e.globalPosition().toPoint() - start
        if self._dragged or abs(delta.x()) + abs(delta.y()) > 4:
            self._dragged = True
            self.move(origin + delta)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press is None:
            return
        self._press = None
        if not self._dragged:
            self.clicked.emit()
            return
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        x = min(max(self.x(), a.left()), a.right() - _SIZE)
        y = min(max(self.y(), a.top()), a.bottom() - _SIZE)
        self.move(QPoint(x, y))
        self._screen = screen
        self.place = ((x - a.left()) / max(1, a.width() - _SIZE), (y - a.top()) / max(1, a.height() - _SIZE))
        self.moved.emit(*self.place)
