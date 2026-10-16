"""The floating microphone button (2026-10-16, the user's request; on_focus "float"): on top, fading in while listening
is off and the focus is where text can be typed; a click turns listening on. It never takes focus, so the text goes
to the window that had it, as with the key. Dragged, it stays where it was dropped; its place is kept as a fraction of the screen, and it shows on the
screen the pointer is on at that same place (the user has three screens).
Both draw the look picked on the 外觀 tab (orbs.py: the microphone, or one of nine energy orbs in the glow's
colors), animated only while shown.

Motions (`OrbButton`, 2026-10-16, the user's design): one look at rest, no hover color. The pointer over it shrinks it
a little, springing (the user's pick of smooth, bouncing and springy, compared on the 外觀 tab for a few hours). When listening starts it grows quickly
and fades out as the glow fades in (`glow.FADE_MS`); when listening ends it shrinks back from that size and fades in
as the glow fades out. With 按下後不隱藏 (`float_keep`) the floating button stays: a click makes it jump a little and
come back, and while listening a click turns listening off. Its window has room around the button (`_ROOM`) for the
orb's light and for growing; the room is transparent, so clicks there go through. The button's place is the middle
of it.
With 只在可以打字的地方顯示 unticked (`float_text_only`, the 外觀 tab, 2026-10-16, the user's request) the floating
button shows wherever the focus is. 按鈕大小 (`button_scale`, 75-125%) scales both buttons.
"""
import ctypes

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .glow import FADE_MS
from .orbs import OrbPlayer

_SIZE = 44      # the floating button at 100%
_ROOM = 2.2      # the window, times the button: the orb's light grown on a click still fits
_HOVER = 0.88    # the size under the pointer
_BURST = 1.5     # the size it grows to as it fades out
_GWL_EXSTYLE, _WS_EX_NOACTIVATE, _WS_EX_TOPMOST = -20, 0x08000000, 0x8



def _hover_curve():
    """How it shrinks under the pointer and comes back: a spring, a few small swings."""
    c = QEasingCurve(QEasingCurve.OutElastic)
    c.setAmplitude(1.0)
    c.setPeriod(0.42)
    return c, 520


def _paint_mic(p: QPainter):
    p.setPen(QPen(QColor(255, 255, 255, 60), 1))
    p.setBrush(QColor(32, 32, 36, 220))
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


class OrbButton(QWidget):
    """The look (orb or microphone) of a button of `size` px in the middle of a widget `room` times as big, with its
    motions: its scale (k) and opacity (alpha) animated with easing."""
    clicked = Signal()

    def __init__(self, size: int, room: float = _ROOM, parent=None, flags=Qt.WindowType.Widget):
        super().__init__(parent, flags)
        self.base, self.room = size, room   # the size at 100%
        self.bsize = size
        self.orb = OrbPlayer(self, size)
        self._fit()
        self.k = 1.0
        self.alpha = 1.0
        self.leaving = False   # growing and fading out: hidden at the end
        self._then = None      # the next scale after this one (a jump: up, then back)
        self._grow = QVariantAnimation(self)
        self._grow.valueChanged.connect(self._set_k)
        self._grow.finished.connect(self._grown)
        self._fade = QVariantAnimation(self)
        self._fade.valueChanged.connect(self._set_alpha)
        self._fade.finished.connect(self._faded)

    def _fit(self):
        side = round(self.bsize * self.room)
        self.margin = (side - self.bsize) // 2
        self.setFixedSize(side, side)

    def set_look(self, look: str, colors: list, lite: bool = False, scale: int = 100):
        size = round(self.base * scale / 100)
        if size != self.bsize:
            center = self.geometry().center()
            self.bsize = size
            self._fit()
            self.orb.resize(size)
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
            self._resized()
        if (self.orb.look, self.orb.colors, self.orb.lite) != (look, list(colors), lite):
            self.orb.set_look(look, colors, lite)
            if self.isVisible():
                self.orb.start()

    def _resized(self):
        """The button's size changed (its window was kept centered where it was)."""

    # --- animation
    def _set_k(self, v):
        self.k = float(v)
        self.update()

    def _set_alpha(self, v):
        self.alpha = float(v)
        self.update()

    def _scale_to(self, k: float, ms: int, curve, then=None):
        self._grow.stop()
        self._then = then
        self._grow.setStartValue(self.k)
        self._grow.setEndValue(float(k))
        self._grow.setDuration(ms)
        self._grow.setEasingCurve(curve)
        self._grow.start()

    def _grown(self):
        if self._then:
            k, ms, curve = self._then
            self._scale_to(k, ms, curve)

    def _fade_to(self, alpha: float, ms: int):
        self._fade.stop()
        self._fade.setStartValue(self.alpha)
        self._fade.setEndValue(float(alpha))
        self._fade.setDuration(ms)
        self._fade.setEasingCurve(QEasingCurve.OutQuad)
        self._fade.start()

    def _faded(self):
        if self.leaving and self.alpha <= 0.0:
            self._gone()

    def _gone(self):
        self.hide()

    def _appear(self):
        """Shown (a window: without taking the focus)."""
        self.show()

    def fade_in(self, ms: int = 180):
        """In at its size (the focus came where it shows)."""
        if self.isVisible() and not self.leaving:
            return
        self.leaving = False
        if not self.isVisible():
            self.k, self.alpha = 1.0, 0.0
            self._appear()
        self._scale_to(1.0, ms, QEasingCurve(QEasingCurve.OutCubic))
        self._fade_to(1.0, ms)

    def burst(self):
        """Listening started: it grows quickly and fades out as the glow fades in, then hides."""
        if not self.isVisible():
            return
        self.leaving = True
        self._scale_to(_BURST, FADE_MS, QEasingCurve(QEasingCurve.OutCubic))
        self._fade_to(0.0, FADE_MS)

    def come_back(self):
        """Listening ended: back from the grown size to its own, fading in as the glow fades out."""
        self.leaving = False
        if not self.isVisible():
            self.k, self.alpha = _BURST, 0.0
            self._appear()
        self._scale_to(1.0, FADE_MS, QEasingCurve(QEasingCurve.OutCubic))
        self._fade_to(1.0, FADE_MS)

    def jump(self):
        """A click that does not hide it: up a little, quickly, and back with a bounce."""
        back = QEasingCurve(QEasingCurve.OutBack)
        back.setOvershoot(2.0)
        self._scale_to(1.22, 110, QEasingCurve(QEasingCurve.OutCubic), then=(1.0, 320, back))

    # --- events
    def showEvent(self, e):
        self.orb.start()

    def hideEvent(self, e):
        self.orb.stop()
        self._grow.stop()
        self._fade.stop()
        self.leaving = False

    def enterEvent(self, e):
        if not self.leaving:
            curve, ms = _hover_curve()
            self._scale_to(_HOVER, ms, curve)

    def leaveEvent(self, e):
        if not self.leaving:
            curve, ms = _hover_curve()
            self._scale_to(1.0, ms, curve)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(max(0.0, min(1.0, self.alpha)))
        c = self.width() / 2
        p.translate(c, c)
        p.scale(self.k, self.k)
        if self.orb.look == "mic":
            p.scale(self.bsize / _SIZE, self.bsize / _SIZE)
            p.translate(-_SIZE / 2, -_SIZE / 2)
            _paint_mic(p)
        else:
            p.translate(-self.orb.size / 2, -self.orb.size / 2)
            self.orb.paint(p)
        p.end()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class _OnTop(OrbButton):
    """A button in a window of its own on top that never takes the focus."""

    def __init__(self, size: int):
        super().__init__(size, flags=Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setToolTip("開啟麥克風")

    def hwnd(self) -> int:
        return int(self.winId())

    def _appear(self):
        self.show()
        hwnd = self.hwnd()
        u32 = ctypes.windll.user32
        u32.SetWindowLongW(hwnd, _GWL_EXSTYLE, u32.GetWindowLongW(hwnd, _GWL_EXSTYLE) | _WS_EX_NOACTIVATE | _WS_EX_TOPMOST)


class Bubble(_OnTop):
    """The small microphone bubble by the point a click put the caret in a text box (on_focus "bubble"; 2026-10-16,
    the user's requests: by the caret at first, but Notion, LINE and web pages reported the caret's place wrong, so
    by the click, which is where the user looks): a click on it turns listening on; it goes when the user types,
    scrolls or the focus leaves; it grows and fades out when listening starts and comes back in its place when
    listening ends. Never takes focus."""
    SIZE = 28

    def __init__(self):
        super().__init__(self.SIZE)
        self._at = None   # the click it shows by (physical pixels)

    def show_at(self, pt):
        """By the click at pt (x, y) in physical pixels: just right of it, centered on it, kept on screen. Fading in,
        also when it showed by another click: that one goes at once (the user's design, 2026-10-16)."""
        self._at = tuple(pt)
        if self.isVisible():
            self._grow.stop()
            self._fade.stop()
            self.k, self.alpha, self.leaving = 1.0, 0.0, False
            self._place()
            self.update()
            self._fade_to(1.0, 160)
            return
        self._place()
        self.fade_in(160)

    def fade_out(self, ms: int = 160):
        """Out where it is (the focus went where nothing can be typed), then hidden."""
        if not self.isVisible() or self.leaving:
            return
        self.leaving = True
        self._grow.stop()
        self._fade_to(0.0, ms)

    def _place(self):
        if self._at is None:
            return
        p, _ratio = _logical(*self._at)
        screen = QGuiApplication.screenAt(p) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        size, m = self.bsize, self.margin
        self.move(min(max(p.x() + 10, a.left()), a.right() - size) - m,
                  min(max(p.y() - size // 2, a.top()), a.bottom() - size) - m)

    def _resized(self):
        self._place()

    def come_back_here(self):
        """Listening ended: back in its place, shrinking from the grown size as the glow fades out."""
        if self._at is not None:
            self._place()
            self.come_back()


def _logical(x: int, y: int):
    for s in QGuiApplication.screens():
        g, r = s.geometry(), s.devicePixelRatio()
        if g.x() <= x < g.x() + g.width() * r and g.y() <= y < g.y() + g.height() * r:
            return QPoint(g.x() + int((x - g.x()) / r), g.y() + int((y - g.y()) / r)), r
    return QPoint(x, y), 1.0


class FloatButton(_OnTop):
    moved = Signal(float, float)   # the new place, as fractions of the screen's free range

    def __init__(self, place=(0.98, 0.88)):
        super().__init__(_SIZE)
        self.place = tuple(place)
        self._screen = None
        self._press = None     # (global point, window position) while the button is down
        self._dragged = False
        self._follow = QTimer(self, interval=300, timeout=self._follow_pointer)

    def _appear(self):
        self._screen = None
        self._follow_pointer()
        super()._appear()

    def showEvent(self, e):
        super().showEvent(e)
        self._follow.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._follow.stop()

    def appear(self):
        self.fade_in()   # fades in (the user's request: it shows when text can be typed)

    def vanish(self):
        if not self.leaving:   # a burst hides it when it ends
            self.hide()

    def _follow_pointer(self):
        if self._press is not None:
            return
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is not self._screen:
            self._screen = screen
            a = screen.availableGeometry()
            fx, fy = self.place
            self.move(a.left() + round(fx * (a.width() - self.bsize)) - self.margin,
                      a.top() + round(fy * (a.height() - self.bsize)) - self.margin)

    def _resized(self):
        self._screen = None
        self._follow_pointer()

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
        m = self.margin   # the button kept on screen, not the room around it
        size = self.bsize
        x = min(max(self.x() + m, a.left()), a.right() - size)
        y = min(max(self.y() + m, a.top()), a.bottom() - size)
        self.move(QPoint(x - m, y - m))
        self._screen = screen
        self.place = ((x - a.left()) / max(1, a.width() - size), (y - a.top()) / max(1, a.height() - size))
        self.moved.emit(*self.place)
