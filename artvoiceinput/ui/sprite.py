"""The tutorial's guide (2026-10-24, the user's design: B of https://claude.ai/artifact/A8FNxjZPgBfCV3z3Tvod8G with
C's expressions): the app icon's square come alive, a face of white lines (eyes and a mouth) looking left or right
at what it talks about, blinking, bobbing a little; it moves next to what the user should look at, and its card
(`Card`) talks beside it."""
import math
import random
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import appicon
from . import theme
from .kit import T, button, calm
from .wizard import TextLink

ICON = 40          # the square's side
SIDE = 76          # the widget: room for the jump, the listening ring and the sparkles
FACES = ("idle", "happy", "listen", "oops", "proud", "think")


class Sprite(QWidget):
    """The icon with a face. `face` one of FACES; `look_at` turns the eyes toward a point (the desk's)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(SIDE, SIDE)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.face = "idle"
        self._eye = QPointF(0, 0)        # where the eyes look, -1..1 each way
        self._eye_to = QPointF(0, 0)
        self._blink_at = time.monotonic() + 2.5
        self._t0 = time.monotonic()
        self._jump = 0.0                 # px up
        self._shake = 0.0                # px sideways
        self._timer = QTimer(self, interval=1000 // 30, timeout=self._tick)
        self._move = QPropertyAnimation(self, b"pos", self, duration=520, easingCurve=QEasingCurve.OutBack)
        self._react = None

    # --- what it does ---
    def set_face(self, face: str):
        self.face = face if face in FACES else "idle"
        self.update()

    def look_at(self, pt: QPoint | None):
        """Eyes toward pt (None: straight ahead)."""
        if pt is None:
            self._eye_to = QPointF(0, 0)
        else:
            c = self.geometry().center()
            dx, dy = pt.x() - c.x(), pt.y() - c.y()
            d = max(1.0, math.hypot(dx, dy))
            self._eye_to = QPointF(dx / d, dy / d * 0.7)
        if calm():
            self._eye = QPointF(self._eye_to)
        self.update()

    def go(self, pos: QPoint):
        """To pos (its top left), with a little overshoot."""
        if calm() or not self.isVisible():
            self.move(pos)
            return
        self._move.stop()
        self._move.setStartValue(self.pos())
        self._move.setEndValue(pos)
        self._move.start()

    def bounce(self):
        """Pleased: a hop."""
        self._react = ("jump", time.monotonic())

    def shake(self):
        """Not quite: a shake of the head."""
        self._react = ("shake", time.monotonic())

    # --- the frames ---
    def showEvent(self, e):
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()

    def _tick(self):
        now = time.monotonic()
        self._eye += (self._eye_to - self._eye) * 0.25
        self._jump = self._shake = 0.0
        if self._react:
            kind, at = self._react
            t = now - at
            if kind == "jump" and t < 0.5:
                self._jump = 14 * math.sin(t / 0.5 * math.pi)
            elif kind == "shake" and t < 0.5:
                self._shake = 4 * math.sin(t * 40) * (1 - t / 0.5)
            else:
                self._react = None
        if now > self._blink_at + 0.14:
            self._blink_at = now + random.uniform(2.2, 4.8)
        if calm() and not self._react:
            self._eye = QPointF(self._eye_to)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        now = time.monotonic()
        bob = 0.0 if calm() else 1.6 * math.sin((now - self._t0) * math.tau / 2.4)
        x = (SIDE - ICON) / 2 + self._shake
        y = SIDE - ICON - 12 - self._jump + bob
        # its shadow on the ground
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40 if not self._jump else 26))
        p.drawEllipse(QPointF(SIDE / 2, SIDE - 7), 14 - self._jump * 0.3, 3.2)
        if self.face == "listen" and not calm():
            t = ((now - self._t0) % 1.4) / 1.4
            ring = QColor(theme.ACCENT)
            ring.setAlphaF(0.55 * (1 - t))
            p.setPen(QPen(ring, 2))
            p.setBrush(Qt.NoBrush)
            grow = 4 + 10 * t
            p.drawRoundedRect(QRectF(x - grow, y - grow, ICON + 2 * grow, ICON + 2 * grow), 12 + grow, 12 + grow)
        p.save()
        p.translate(x, y)
        appicon.tile(p, ICON)
        self._paint_face(p, now)
        p.restore()
        if self.face == "proud":
            self._sparkles(p, x, y, now)
        if self.face == "oops":
            drop = QPainterPath(QPointF(x + ICON + 2, y + 2))
            drop.quadTo(x + ICON + 7, y + 10, x + ICON + 2, y + 12)
            drop.quadTo(x + ICON - 3, y + 10, x + ICON + 2, y + 2)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#7cc4ff"))
            p.drawPath(drop)

    def _paint_face(self, p: QPainter, now: float):
        white = QColor("#ffffff")
        ex, ey = self._eye.x() * 3.0, self._eye.y() * 2.0
        blink = self._blink_at <= now <= self._blink_at + 0.14
        pen = QPen(white, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        left, right, eye_y = 14 + ex, 26 + ex, 17 + ey
        face = self.face
        if face in ("happy", "proud"):     # eyes closed in a smile: ^ ^
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            for cx in (left, right):
                path = QPainterPath(QPointF(cx - 3.2, eye_y + 1.5))
                path.quadTo(cx, eye_y - 3.5, cx + 3.2, eye_y + 1.5)
                p.drawPath(path)
        elif blink:
            p.setPen(pen)
            for cx in (left, right):
                p.drawLine(QPointF(cx - 2.4, eye_y), QPointF(cx + 2.4, eye_y))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(white)
            big = 1.25 if face == "oops" else 1.0
            for cx in (left, right):
                p.drawRoundedRect(QRectF(cx - 1.9 * big, eye_y - 3.2 * big, 3.8 * big, 6.4 * big), 1.9 * big, 1.9 * big)
        # the mouth
        mx, my = 20 + ex * 0.6, 28 + ey * 0.5
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if face == "happy" or face == "proud":
            path = QPainterPath(QPointF(mx - 5.5, my - 1.5))
            path.quadTo(mx, my + 6, mx + 5.5, my - 1.5)
            path.closeSubpath()
            p.setBrush(white)
            p.drawPath(path)
        elif face == "listen":
            p.drawEllipse(QPointF(mx, my), 2.2, 1.8)
        elif face == "oops":
            p.drawEllipse(QPointF(mx, my + 0.5), 2.6, 3.0)
        elif face == "think":
            p.drawLine(QPointF(mx - 3.5, my + 0.5), QPointF(mx + 3.5, my - 0.8))
        else:
            path = QPainterPath(QPointF(mx - 4.5, my - 1))
            path.quadTo(mx, my + 3.5, mx + 4.5, my - 1)
            p.drawPath(path)

    def _sparkles(self, p: QPainter, x: float, y: float, now: float):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFC531"))
        for i, (dx, dy, s) in enumerate(((-8, 2, 4.0), (ICON + 6, -2, 5.0), (ICON + 2, ICON - 6, 3.0))):
            k = 0.6 + 0.4 * math.sin(now * 4 + i * 2) if not calm() else 1.0
            r = s * k
            star = QPainterPath(QPointF(x + dx, y + dy - r))
            for a, b in ((r * 0.3, -r * 0.3), (r, 0), (r * 0.3, r * 0.3), (0, r), (-r * 0.3, r * 0.3), (-r, 0),
                         (-r * 0.3, -r * 0.3)):
                star.lineTo(x + dx + a, y + dy + b)
            star.closeSubpath()
            p.drawPath(star)


class Level(QWidget):
    """Five bars of the microphone's level beside 正在聽…"""

    def __init__(self):
        super().__init__()
        self.setFixedSize(22, 14)
        self.level = 0.0

    def set(self, level: float):
        self.level = self.level * 0.5 + level * 0.5
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(T("acc"))
        for i, k in enumerate((0.5, 0.8, 1.0, 0.7, 0.45)):
            h = 3 + 11 * min(1.0, self.level * 1.4) * k
            p.drawRoundedRect(QRectF(i * 4.5, 14 - h, 3, h), 1.5, 1.5)


class Card(QWidget):
    """What the guide says: its name, the line, a sentence to read (`quote`), what was heard (`heard`, rich text),
    and a row with ‹ 上一句 and either 繼續 or what it waits for (`status`), 跳過這步 when offered. A click on the card
    is 繼續 too."""
    W = 300
    TAIL = 9
    next_clicked = Signal()
    back_clicked = Signal()
    skip_clicked = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedWidth(self.W)
        self.side = "left"          # where the tail is: toward the guide
        v = QVBoxLayout(self)
        v.setContentsMargins(16 + self.TAIL, 12, 16 + self.TAIL, 12)
        v.setSpacing(6)
        self.name = QLabel("阿特")
        self.name.setFont(theme.font(12, 700))
        v.addWidget(self.name)
        self.text = QLabel()
        self.text.setFont(theme.font(14))
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        v.addWidget(self.text)
        self.quote = QLabel()
        self.quote.setFont(theme.font(16, 700))
        self.quote.setWordWrap(True)
        v.addWidget(self.quote)
        self.heard = QLabel()
        self.heard.setFont(theme.font(14))
        self.heard.setWordWrap(True)
        self.heard.setTextFormat(Qt.RichText)
        v.addWidget(self.heard)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.back = TextLink("‹ 上一句")
        self.back.clicked.connect(self.back_clicked.emit)
        row.addWidget(self.back)
        row.addStretch(1)
        self.skip = TextLink("跳過這步")
        self.skip.clicked.connect(self.skip_clicked.emit)
        row.addWidget(self.skip)
        self.dot = QLabel("●")
        self.dot.setFont(theme.font(10))
        self.level = Level()
        self.status = QLabel()
        self.status.setFont(theme.font(12.5, 500))
        row.addWidget(self.dot)
        row.addWidget(self.level)
        row.addWidget(self.status)
        self.next = button("繼續", self.next_clicked.emit, pri=True)
        self.next.setMinimumHeight(30)
        row.addWidget(self.next)
        v.addLayout(row)
        self.restyle()

    def restyle(self):
        self.name.setStyleSheet(f"color: {T('acct').name()};")
        self.dot.setStyleSheet(f"color: {T('acc').name()};")
        self.status.setStyleSheet(f"color: {T('acct').name()};")
        self.quote.setStyleSheet(f"background: {T('acc', 0.08).name(QColor.HexArgb)}; border-radius: 8px;"
                                 f"padding: 8px 10px; color: {T('ink').name()};")
        self.heard.setStyleSheet(f"background: {T('tile2').name()}; border-radius: 8px; padding: 8px 10px;"
                                 f"color: {T('ink').name()};")

    def show_line(self, text: str, quote: str = "", heard: str = "", status: str = "", listening: bool = False,
                  skip: bool = False, back: bool = True, next_text: str = "繼續"):
        """status "" shows 繼續 (next_text); else what the guide waits for, with the level bars while listening."""
        self.text.setText(text)
        self.quote.setText(quote)
        self.quote.setVisible(bool(quote))
        self.heard.setText(heard)
        self.heard.setVisible(bool(heard))
        self.status.setText(status)
        waiting = bool(status)
        self.status.setVisible(waiting)
        self.dot.setVisible(waiting and not listening)
        self.level.setVisible(waiting and listening)
        self.next.setVisible(not waiting)
        self.next.setText(next_text)
        self.skip.setVisible(skip)
        self.back.setVisible(back)
        self.adjustSize()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.next.isVisible():
            self.next_clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        body = QRectF(self.rect()).adjusted(self.TAIL, 2, -self.TAIL, -4)
        for i in range(8, 0, -2):
            a = (34 if T("bg").lightnessF() < 0.3 else 14) * (1 - i / 8) ** 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, round(a)))
            p.drawRoundedRect(body.adjusted(-i / 2, -i / 2 + 2, i / 2, i / 2 + 3), 12 + i / 2, 12 + i / 2)
        path = QPainterPath()
        path.addRoundedRect(body, 12, 12)
        ty = min(max(self.tail_y, 22), body.bottom() - 22)
        tail = QPainterPath()
        if self.side == "left":
            tail.moveTo(body.x() + 1, ty - 8)
            tail.lineTo(body.x() - self.TAIL + 1, ty)
            tail.lineTo(body.x() + 1, ty + 8)
        else:
            tail.moveTo(body.right() - 1, ty - 8)
            tail.lineTo(body.right() + self.TAIL - 1, ty)
            tail.lineTo(body.right() - 1, ty + 8)
        tail.closeSubpath()
        p.fillPath(path.united(tail), T("tile"))

    tail_y = 28
