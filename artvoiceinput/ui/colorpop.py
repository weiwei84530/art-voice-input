"""The color picker (2026-10-22, the user's request, in place of Qt's color dialog): a small card popping up beside
the swatch clicked, a hue ring round a square (left to right paler to fuller, top to bottom lighter to darker), so
every color has its place and no numbers show. The color follows the pointer (`changed`); a click outside or Enter
keeps it, Esc puts the first one back. Used by 草稿反白顏色's 自訂 and the glow's colors."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QConicalGradient, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .kit import T

SHADE = 14        # room round the card for its shadow
SIZE = 196        # the card
RING = 16         # the hue ring's width
GAP = 10          # between the ring and the square


class ColorPop(QWidget):
    changed = Signal(QColor)
    closed = Signal()

    def __init__(self, color: QColor, anchor: QWidget):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedSize(SIZE + 2 * SHADE, SIZE + 2 * SHADE)
        self.setCursor(Qt.CrossCursor)
        self.setAccessibleName("選顏色：外圈選色相，中間的方塊左右是濃淡、上下是深淺")
        self._first = QColor(color)
        h, s, v, _ = color.getHsvF()
        self.h, self.s, self.v = max(h, 0.0), s, v   # a gray has no hue (-1): the ring starts at red
        self._drag = None   # "ring" or "square" while the button is down
        self._place(anchor)

    # --- geometry ---
    @property
    def _center(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    @property
    def _outer(self) -> float:
        return SIZE / 2 - 12

    @property
    def _square(self) -> QRectF:
        half = (self._outer - RING - GAP) / math.sqrt(2)
        c = self._center
        return QRectF(c.x() - half, c.y() - half, 2 * half, 2 * half)

    def _place(self, anchor: QWidget):
        """Under the swatch, centered on it, or above it when the screen ends; within the window and the screen."""
        below = anchor.mapToGlobal(anchor.rect().bottomLeft())
        x = anchor.mapToGlobal(anchor.rect().center()).x() - self.width() // 2
        y = below.y() + 6 - SHADE
        screen = QGuiApplication.screenAt(below) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        if y + self.height() > a.bottom():
            y = anchor.mapToGlobal(anchor.rect().topLeft()).y() - 6 - self.height() + SHADE
        w = anchor.window().frameGeometry()
        x = min(max(x, w.left() + 8 - SHADE), w.right() - 8 + SHADE - self.width())
        x = min(max(x, a.left()), a.right() - self.width())
        self.move(x, y)

    def color(self) -> QColor:
        return QColor.fromHsvF(self.h, self.s, self.v)

    # --- drawing ---
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(SHADE, SHADE, SIZE, SIZE)
        for i, a in enumerate((14, 9, 5)):   # a soft shadow, a little lower
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(card.adjusted(-i - 1, i + 1, i + 1, i + 4), 14, 14)
        p.setPen(QPen(T("line"), 1))
        p.setBrush(T("tile"))
        p.drawRoundedRect(card, 12, 12)

        c, outer = self._center, self._outer
        hues = QConicalGradient(c, 0)   # counterclockwise from 3 o'clock, as the angle read in _hue_at
        for i in range(7):
            hues.setColorAt(i / 6, QColor.fromHsvF((i % 6) / 6, 1, 1))
        ring = QPainterPath()
        ring.addEllipse(c, outer, outer)
        ring.addEllipse(c, outer - RING, outer - RING)
        p.setPen(Qt.NoPen)
        p.fillPath(ring, hues)

        sq = self._square
        p.fillRect(sq, QColor.fromHsvF(self.h, 1, 1))
        pale = QLinearGradient(sq.topLeft(), sq.topRight())
        pale.setColorAt(0, QColor(255, 255, 255))
        pale.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(sq, pale)
        dark = QLinearGradient(sq.topLeft(), sq.bottomLeft())
        dark.setColorAt(0, QColor(0, 0, 0, 0))
        dark.setColorAt(1, QColor(0, 0, 0))
        p.fillRect(sq, dark)

        angle = self.h * 2 * math.pi
        mid = outer - RING / 2
        self._marker(p, QPointF(c.x() + mid * math.cos(angle), c.y() - mid * math.sin(angle)),
                     QColor.fromHsvF(self.h, 1, 1))
        self._marker(p, QPointF(sq.left() + self.s * sq.width(), sq.top() + (1 - self.v) * sq.height()), self.color())

    @staticmethod
    def _marker(p: QPainter, at: QPointF, fill: QColor):
        p.setBrush(fill)
        p.setPen(QPen(QColor(0, 0, 0, 90), 3))
        p.drawEllipse(at, 7, 7)
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        p.drawEllipse(at, 7, 7)

    # --- the pointer and keys ---
    def mousePressEvent(self, e):
        pos = e.position()
        d = math.dist((pos.x(), pos.y()), (self._center.x(), self._center.y()))
        if self._outer - RING - 4 <= d <= self._outer + 4:
            self._drag = "ring"
        elif self._square.adjusted(-4, -4, 4, 4).contains(pos):
            self._drag = "square"
        elif not QRectF(SHADE, SHADE, SIZE, SIZE).contains(pos):
            self.close()   # outside the card (its shadow): kept, as a click elsewhere
            return
        self._follow(pos)

    def mouseMoveEvent(self, e):
        self._follow(e.position())

    def mouseReleaseEvent(self, e):
        self._drag = None

    def _follow(self, pos: QPointF):
        if self._drag == "ring":
            c = self._center
            self.h = (math.degrees(math.atan2(c.y() - pos.y(), pos.x() - c.x())) % 360) / 360
        elif self._drag == "square":
            sq = self._square
            self.s = min(max((pos.x() - sq.left()) / sq.width(), 0.0), 1.0)
            self.v = min(max(1 - (pos.y() - sq.top()) / sq.height(), 0.0), 1.0)
        else:
            return
        self.update()
        self.changed.emit(self.color())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:   # back to the color it opened with
            self.changed.emit(self._first)
            self.close()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)


def pop_color(anchor: QWidget, color: QColor, changed, closed) -> ColorPop:
    """The picker beside anchor: changed(QColor) as the color moves, closed() once it is gone."""
    global _open
    pop = _open = ColorPop(color, anchor)   # kept here: a window with no parent and no reference is collected
    pop.changed.connect(changed)
    pop.closed.connect(closed)
    pop.closed.connect(_forget)
    pop.show()
    return pop


_open = None


def _forget():
    global _open
    _open = None
