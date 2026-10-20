"""The three 麥克風 cards' small illustrations (design round 13, L1-L3, with the user's notes of 2026-10-21), drawn
here rather than taken from the canvas: what the browser showed was not what Qt draws.

- keys: K1a's line keyboard, its set key pressed, then a mouse's side button; each time the recording circle pops.
- box: the caret at a text box's left; the pointer clicks further right, the bubble pops right of the click over the
  box's edge, the pointer clicks it, it bursts and the recording circle shows beside it.
- float: the pointer comes over the floating button, it grows; pressed, it dips and springs back smaller and spins
  faster; the recording circle shows.
A click is a cartoon burst of eight short rays, not a ring. The pointer stays where it clicked and fades.

Each is a 4s loop played only while the pointer is on its card (the user left it to us: three loops running at
once read as noise next to the cards' breathing state pills, and cost frames for nothing); at rest it holds its
most telling frame, in color. 節流模式 (kit.calm) never plays them."""
import math
import time

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from .kit import T, calm

W, H = 236, 56       # the drawing, as on the canvas
LOOP = 4.0           # seconds
_STILL = {"keys": 0.2, "box": 0.47, "float": 0.3}   # the frame held at rest, as a fraction of the loop
_ORB = ["#3d7bff", "#a259ff", "#ff4fa3", "#ff9f43", "#29d3ff", "#3d7bff"]


def _in_out(x):
    return x * x * (3 - 2 * x)


def _back(x):   # overshoots a little, as a pop
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def _kf(t, frames, ease=_in_out):
    """The value at t (0..1) along (time, value) frames, eased between them; values may be tuples."""
    if t <= frames[0][0]:
        return frames[0][1]
    for (t0, v0), (t1, v1) in zip(frames, frames[1:]):
        if t <= t1:
            k = ease((t - t0) / (t1 - t0)) if t1 > t0 else 1
            if isinstance(v0, tuple):
                return tuple(a + (b - a) * k for a, b in zip(v0, v1))
            return v0 + (v1 - v0) * k
    return frames[-1][1]


def _burst(p, x, y, t, start, length=0.08):
    """A click: eight short rays thrown out from (x, y), long and short in turn, between start and start + length."""
    k = (t - start) / length
    if not 0 <= k <= 1:
        return
    p.save()
    p.setOpacity(1 - k ** 2)
    p.setPen(QPen(T("acc"), 1.8, Qt.SolidLine, Qt.RoundCap))
    for i in range(8):
        a = math.radians(i * 45 - 90)
        long = i % 2 == 0
        r0 = 5 + (9 if long else 6) * k
        r1 = r0 + (6 if long else 4) * (1 - 0.6 * k)
        p.drawLine(QPointF(x + r0 * math.cos(a), y + r0 * math.sin(a)),
                   QPointF(x + r1 * math.cos(a), y + r1 * math.sin(a)))
    p.restore()


def _pointer(p, x, y, alpha):
    if alpha <= 0:
        return
    path = QPainterPath(QPointF(0, 0))
    for px, py in ((0, 13.5), (3.4, 10.4), (5.9, 15.8), (8.1, 14.8), (5.7, 9.6), (10.2, 9.6)):
        path.lineTo(px, py)
    path.closeSubpath()
    p.save()
    p.setOpacity(alpha)
    p.translate(x, y + 1)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 60))
    p.drawPath(path)
    p.translate(0, -1)
    p.setPen(QPen(QColor("#15171A"), 1.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(QColor("#FFFFFF"))
    p.drawPath(path)
    p.restore()


def _rec(p, cx, cy, k, alpha, ring):
    """The recording circle: red, a white microphone, a ring spreading while it records (ring: 0..1, None still)."""
    if alpha <= 0 or k <= 0:
        return
    p.save()
    p.setOpacity(alpha)
    p.translate(cx, cy)
    if ring is not None:
        p.save()
        p.setOpacity(alpha * 0.6 * (1 - ring))
        p.setPen(QPen(T("acc"), 2))
        p.setBrush(Qt.NoBrush)
        r = 12 * (1 + 0.9 * ring)
        p.drawEllipse(QPointF(0, 0), r, r)
        p.restore()
    p.scale(k, k)
    p.setPen(Qt.NoPen)
    p.setBrush(T("acc"))
    p.drawEllipse(QPointF(0, 0), 12, 12)
    p.setPen(QPen(QColor("#FFFFFF"), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(-2.6, -7, 5.2, 9), 2.6, 2.6)
    p.drawArc(QRectF(-5.2, -4.5, 10.4, 9.5), 200 * 16, 140 * 16)
    p.drawLine(QPointF(0, 5), QPointF(0, 7.2))
    p.restore()


def _orb(p, cx, cy, r, angle, shadow=True):
    if shadow:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QPointF(cx, cy + r * 0.25 + 3), r * 0.9, r * 0.9)
    g = QConicalGradient(QPointF(cx, cy), -angle)
    for i, c in enumerate(_ORB):
        g.setColorAt(i / (len(_ORB) - 1), QColor(c))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(cx, cy), r, r)
    hl = QRadialGradient(QPointF(cx, cy - r * 0.28), r * 0.8)
    hl.setColorAt(0, QColor(255, 255, 255, 205))
    hl.setColorAt(0.5, QColor(255, 255, 255, 0))
    p.setBrush(hl)
    p.drawEllipse(QPointF(cx, cy), r, r)


class Illustration(QWidget):
    """One of the three (kind: keys, box, float), centered in its width; played while the pointer is on `card`."""

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.setFixedHeight(H + 8)
        self._t0 = None
        self._timer = QTimer(self, interval=33, timeout=self.update)
        self._watcher = None

    def watch(self, card: QWidget):
        self._watcher = _Hover(card, self)

    def play(self, on: bool):
        if on and not calm():
            self._t0 = time.monotonic()
            self._timer.start()
        else:
            self._t0 = None
            self._timer.stop()
        self.update()

    def hideEvent(self, e):
        self.play(False)

    def _t(self) -> float:
        if self._t0 is None:
            return _STILL[self.kind]
        return ((time.monotonic() - self._t0) / LOOP) % 1.0

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(T("tile2"))
        p.drawRoundedRect(r, 6, 6)
        p.translate(round((self.width() - W) / 2), 4)
        t = self._t()
        ring = ((time.monotonic() - self._t0) % 1.0) if self._t0 is not None else None
        getattr(self, "_" + self.kind)(p, t, ring)
        p.end()

    # --- L1: keyboard, then mouse
    def _keys(self, p, t, ring):
        line = QColor(T("muted"))
        p.save()
        p.setOpacity(_kf(t, [(0, 1.0), (0.46, 1.0), (0.5, 0.4), (0.96, 0.4), (1, 1.0)]))
        p.setPen(QPen(line, 1.5))
        p.setBrush(Qt.NoBrush)
        kb = QRectF(10, 8, 108, 40)
        p.drawRoundedRect(kb, 7, 7)
        cw, ch, gap = (108 - 9 - 7 * 2.5) / 8, (40 - 9 - 2 * 2.5) / 3, 2.5
        cells = [(r, c, 1) for r in range(2) for c in range(8)] + [(2, 0, 1), (2, 1, 4), (2, 5, 1), (2, 6, 1),
                                                                     (2, 7, 1)]
        press = _kf(t, [(0.08, 0.0), (0.11, 1.0), (0.18, 1.0), (0.22, 0.0)])
        for row, col, span in cells:
            cell = QRectF(kb.x() + 4.5 + col * (cw + gap), kb.y() + 4.5 + row * (ch + gap),
                          cw * span + gap * (span - 1), ch)
            hot = (row, col) == (1, 2)
            p.save()
            if hot:
                k = 1 - 0.15 * press
                c = cell.center()
                p.translate(c.x(), c.y() + press)
                p.scale(k, k)
                p.translate(-c.x(), -c.y())
                p.setPen(QPen(T("acc"), 1.2))
                p.setBrush(T("acc") if press > 0.5 else Qt.NoBrush)
            else:
                p.setOpacity(p.opacity() * 0.55)
                p.setPen(QPen(line, 1))
                p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(cell, 2, 2)
            p.restore()
        p.restore()
        p.save()
        p.setOpacity(_kf(t, [(0, 0.4), (0.46, 0.4), (0.5, 1.0), (0.96, 1.0), (1, 0.4)]))
        p.setPen(QPen(line, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(132, 6, 30, 44), 14, 14)
        p.setPen(Qt.NoPen)
        p.setBrush(line)
        p.drawRoundedRect(QRectF(146, 12, 2, 9), 1, 1)
        lit = _kf(t, [(0.58, 0.0), (0.61, 1.0), (0.68, 1.0), (0.72, 0.0)])
        side = QRectF(129, 26, 5, 12)
        if lit > 0:
            glow = QColor(T("acc"))
            glow.setAlphaF(0.3 * lit)
            p.setBrush(glow)
            p.drawRoundedRect(side.adjusted(-3, -3, 3, 3), 5, 5)
        c = QColor(T("acc")) if lit > 0.5 else line
        p.setBrush(c)
        p.drawRoundedRect(side, 2.5, 2.5)
        p.restore()
        k = _kf(t, [(0.12, 0.0), (0.17, 1.0), (0.40, 1.0), (0.46, 0.6), (0.62, 0.6), (0.67, 1.0), (0.90, 1.0),
                    (0.96, 0.6)], _back)
        a = _kf(t, [(0.12, 0.0), (0.15, 1.0), (0.40, 1.0), (0.46, 0.0), (0.62, 0.0), (0.65, 1.0), (0.90, 1.0),
                    (0.96, 0.0)])
        _rec(p, 202, 28, k, a, ring)

    # --- L2: a text box, the bubble, recording
    def _box(self, p, t, ring):
        focused = _kf(t, [(0.16, 0.0), (0.20, 1.0), (0.94, 1.0), (1.0, 0.0)])
        box = QRectF(8, 12, 142, 30)
        p.setBrush(T("tile"))
        line = QColor(T("line"))
        acc = QColor(T("acc"))
        mix = QColor.fromRgbF(*(line.getRgbF()[i] + (acc.getRgbF()[i] - line.getRgbF()[i]) * focused for i in range(3)))
        p.setPen(QPen(mix, 1.5))
        p.drawRoundedRect(box, 5, 5)
        blink = 0.20 <= t < 0.30 or 0.41 <= t < 0.50 or 0.61 <= t < 0.94
        if blink:
            p.setPen(Qt.NoPen)
            p.setBrush(T("ink"))
            p.drawRect(QRectF(18, 20, 1.5, 14))
        click, bub, rec = (128, 31), (145, 27), (180, 27)
        _burst(p, *click, t, 0.16)
        k = _kf(t, [(0.20, 0.0), (0.28, 1.0), (0.52, 1.0), (0.58, 1.5)], _back)
        a = _kf(t, [(0.20, 0.0), (0.24, 1.0), (0.52, 1.0), (0.58, 0.0)])
        if a > 0:
            p.save()
            p.setOpacity(a)
            _orb(p, *bub, 11 * k, 30, shadow=False)
            p.restore()
        _burst(p, *bub, t, 0.51)
        k = _kf(t, [(0.56, 0.0), (0.62, 1.0), (0.92, 1.0), (0.98, 0.6)], _back)
        a = _kf(t, [(0.56, 0.0), (0.59, 1.0), (0.92, 1.0), (0.98, 0.0)])
        _rec(p, *rec, k, a, ring)
        x, y = _kf(t, [(0.0, (80.0, 58.0)), (0.16, click), (0.30, click), (0.44, bub)])
        alpha = _kf(t, [(0.0, 0.0), (0.06, 1.0), (0.62, 1.0), (0.74, 0.0)])
        _pointer(p, x, y, alpha)

    # --- L3: the floating button
    def _float(self, p, t, ring):
        secs = t * LOOP
        fast = min(max(secs - 1.52, 0.0), 2.16)
        angle = 360 * (secs / 6 + fast * (1 / 1.4 - 1 / 6))
        # hover grows it; pressed it dips past its size and springs back to the smaller one
        k = _kf(t, [(0.10, 1.0), (0.20, 1.12), (0.37, 1.12), (0.40, 0.78), (0.44, 0.95), (0.47, 0.85), (0.50, 0.88),
                    (0.92, 0.88), (1.0, 1.0)])
        _orb(p, 80, 28, 20 * k, angle)
        _burst(p, 84, 30, t, 0.37)
        kr = _kf(t, [(0.42, 0.0), (0.50, 1.0), (0.92, 1.0), (0.98, 0.6)], _back)
        a = _kf(t, [(0.42, 0.0), (0.46, 1.0), (0.92, 1.0), (0.98, 0.0)])
        _rec(p, 162, 28, kr, a, ring)
        x, y = _kf(t, [(0.0, (120.0, 48.0)), (0.18, (84.0, 30.0))])
        alpha = _kf(t, [(0.0, 0.0), (0.08, 1.0), (0.50, 1.0), (0.62, 0.0)])
        _pointer(p, x, y, alpha)


class _Hover(QObject):
    """Plays the illustration while the pointer is on its card."""

    def __init__(self, card: QWidget, ill: Illustration):
        super().__init__(card)
        self.ill = ill
        card.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Enter:
            self.ill.play(True)
        elif e.type() in (QEvent.Leave, QEvent.Hide):
            self.ill.play(False)
        return False
