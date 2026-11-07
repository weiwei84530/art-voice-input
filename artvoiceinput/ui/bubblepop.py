"""語音氣泡's card (2026-11-07, the user's design B of the mockups, opened by the small button on its row like the
color picker): where the bubble shows and when it goes by itself.

- The dial is drawn at real size: the text cursor (I-beam) in the middle stands for the click, which is its middle,
  the bubble (the look picked on 外觀與聲音, at its size) sits gap px from it in its direction, on a ring that grows
  with the gap. Dragging the bubble (or pressing anywhere on the dial) sets direction and gap at once.
- 距離 in px, 自動收起 0-15 seconds in steps of one (0: 不收起).
- With a time set, a faint gray arc round the bubble empties over it, then the bubble fades out, stays away a moment
  and comes back (the user asked for gray and quiet: an orange arc read as part of the real bubble). Nothing moves
  with 節流模式.
Values go to the config as they change (`changed`); the page saves when a drag or slider is let go and on close."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QSlider, QVBoxLayout, QWidget

from .. import config
from ..floatbtn import Bubble, OrbButton, bubble_offset
from . import theme
from .kit import Hub, T, calm, dim, label, sep

SHADE = 14            # room round the card for its shadow
WIDTH = 268           # the card
DIAL_H = 184          # the widest ring (gap 60) with the bubble and its light fits
_GONE_MS = 450        # how long the bubble stays away after its time ran out in the preview
_FADE_MS = 160        # the real bubble's fade


def hide_text(s: int) -> str:
    return f"{s} 秒" if s else "不收起"


class Dial(QWidget):
    """The click (an I-beam) in the middle, the bubble around it."""
    moved = Signal()      # angle / gap changed by the pointer or the keys
    released = Signal()

    def __init__(self, angle: int, gap: int, size: int):
        super().__init__()
        self.setFixedHeight(DIAL_H)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("氣泡的方向和距離：拖動氣泡，或用方向鍵轉動")
        self.angle, self.gap, self.size = angle, gap, size
        self.left = 1.0       # the countdown arc, 1 full .. 0 empty
        self.orb = OrbButton(Bubble.SIZE, parent=self)
        self.orb.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._drag = False
        self.setCursor(Qt.OpenHandCursor)

    def center(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    def orb_center(self) -> QPointF:
        x, y = bubble_offset(self.angle, self.gap, self.size)
        return self.center() + QPointF(x, y)

    def place_orb(self):
        c = self.orb_center()
        self.orb.move(round(c.x() - self.orb.width() / 2), round(c.y() - self.orb.height() / 2))
        self.update()

    def resizeEvent(self, e):
        self.place_orb()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.center()
        r = self.gap + self.size / 2
        ring = QPen(T("muted", 0.45), 1, Qt.CustomDashLine)
        ring.setDashPattern([2, 3])
        p.setPen(ring)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, r, r)
        # the I-beam, drawn as Windows draws it: black with a white outline, its middle the click
        beam = [(QPointF(c.x(), c.y() - 8), QPointF(c.x(), c.y() + 8)),
                (QPointF(c.x() - 3.5, c.y() - 9), QPointF(c.x() + 3.5, c.y() - 9)),
                (QPointF(c.x() - 3.5, c.y() + 9), QPointF(c.x() + 3.5, c.y() + 9))]
        for color, width in ((QColor(255, 255, 255), 3.6), (QColor(0, 0, 0), 1.4)):
            p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
            for a, b in beam:
                p.drawLine(a, b)
        if self.left < 1.0 or self.property("counting"):
            o = self.orb_center()
            rr = self.size / 2 + 4
            p.setPen(QPen(T("muted", 0.35), 1.5, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(o.x() - rr, o.y() - rr, 2 * rr, 2 * rr), 90 * 16, round(-360 * 16 * self.left))

    # --- the pointer and keys
    def _follow(self, pos: QPointF):
        d = pos - self.center()
        self.angle = round(math.degrees(math.atan2(d.y(), d.x()))) % 360
        lo, hi = config.BUBBLE_GAP_RANGE
        self.gap = min(max(round(math.hypot(d.x(), d.y()) - self.size / 2), lo), hi)
        self.place_orb()
        self.moved.emit()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = True
            self.setCursor(Qt.ClosedHandCursor)
            self._follow(e.position())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._follow(e.position())

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.setCursor(Qt.OpenHandCursor)
            self.released.emit()

    def keyPressEvent(self, e):
        step = {Qt.Key_Right: 15, Qt.Key_Down: 15, Qt.Key_Left: -15, Qt.Key_Up: -15}.get(e.key())
        if step is None:
            return super().keyPressEvent(e)
        self.angle = (self.angle + step) % 360
        self.place_orb()
        self.moved.emit()
        self.released.emit()


class BubblePop(QWidget):
    changed = Signal()    # cfg.bubble_* changed
    done = Signal()       # a drag or slider let go: save
    closed = Signal()

    def __init__(self, cfg, colors: list, anchor: QWidget):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        if Hub.current is not None:
            self.setStyleSheet(theme.qss(Hub.current.t))
        self.setFont(theme.font(13))
        self.cfg = cfg
        size = round(Bubble.SIZE * cfg.button_scale / 100)

        v = QVBoxLayout(self)
        v.setContentsMargins(SHADE + 16, SHADE + 14, SHADE + 16, SHADE + 14)
        v.setSpacing(6)
        title = label("氣泡位置", b14=True)
        self.reset = theme_link("恢復預設", self._reset)
        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self.reset)
        v.addLayout(top)
        v.addWidget(dim("直接拖動氣泡，就能改變方向和距離"))

        self.dial = Dial(cfg.bubble_angle, cfg.bubble_gap, size)
        self.dial.orb.set_look(cfg.button_look, colors, cfg.orb_lite, cfg.button_scale)
        self.dial.moved.connect(self._dial_moved)
        self.dial.released.connect(self.done)
        v.addWidget(self.dial)

        lo, hi = config.BUBBLE_GAP_RANGE
        self.gap_value = value_label()
        self.gap = slider(lo, hi, cfg.bubble_gap, "氣泡和游標的距離")
        self.gap.valueChanged.connect(self._gap_moved)
        self.gap.sliderReleased.connect(self.done)
        v.addLayout(row(label("距離"), self.gap_value))
        v.addWidget(self.gap)
        v.addSpacing(4)
        v.addWidget(sep())
        v.addSpacing(4)

        self.hide_value = value_label()
        self.hide_slider = slider(0, config.BUBBLE_HIDE_MAX, cfg.bubble_hide, "沒點它就自動收起的秒數")
        self.hide_slider.valueChanged.connect(self._hide_moved)
        self.hide_slider.sliderReleased.connect(self.done)
        v.addLayout(row(label("沒點它就自動收起"), self.hide_value))
        v.addWidget(self.hide_slider)
        v.addLayout(row(dim("不收起"), dim(f"{config.BUBBLE_HIDE_MAX} 秒")))

        # the countdown preview: the arc empties, the bubble fades out, stays away, comes back
        self._count = QVariantAnimation(self, startValue=1.0, endValue=0.0)
        self._count.valueChanged.connect(self._tick)
        self._count.finished.connect(self._out)
        self._back = QTimer(self, singleShot=True, interval=_GONE_MS + _FADE_MS, timeout=self._in)
        self._show_values()
        self.setFixedWidth(WIDTH + 2 * SHADE)
        self.adjustSize()
        self._place(anchor)
        self._restart()

    # --- values
    def _show_values(self):
        self.gap_value.setText(f"{self.cfg.bubble_gap} px")
        self.hide_value.setText(hide_text(self.cfg.bubble_hide))
        self.reset.setVisible((self.cfg.bubble_angle, self.cfg.bubble_gap) != (0, 10))

    def _dial_moved(self):
        self.cfg.bubble_angle, self.cfg.bubble_gap = self.dial.angle, self.dial.gap
        self.gap.blockSignals(True)
        self.gap.setValue(self.dial.gap)
        self.gap.blockSignals(False)
        self._show_values()
        self.changed.emit()

    def _gap_moved(self, value: int):
        self.cfg.bubble_gap = self.dial.gap = value
        self.dial.place_orb()
        self._show_values()
        self.changed.emit()

    def _hide_moved(self, value: int):
        self.cfg.bubble_hide = value
        self._show_values()
        self.changed.emit()
        self._restart()

    def _reset(self):
        self.cfg.bubble_angle, self.cfg.bubble_gap = 0, 10
        self.dial.angle, self.dial.gap = 0, 10
        self.gap.blockSignals(True)
        self.gap.setValue(10)
        self.gap.blockSignals(False)
        self.dial.place_orb()
        self._show_values()
        self.changed.emit()
        self.done.emit()

    # --- the countdown preview
    def _restart(self, fresh: bool = True):
        self._count.stop()
        self._back.stop()
        if fresh:   # back at once (a value changed); after its time ran out it fades in instead (_in)
            orb = self.dial.orb
            orb._fade.stop()
            orb.leaving, orb.alpha = False, 1.0
            orb.show()
            orb.update()
        seconds = self.cfg.bubble_hide
        self.dial.setProperty("counting", bool(seconds))
        self.dial.left = 1.0
        if seconds and not calm():
            self._count.setDuration(seconds * 1000)
            self._count.start()
        self.dial.update()

    def _tick(self, v):
        self.dial.left = float(v)
        self.dial.update()

    def _out(self):
        self.dial.orb.fade_out(_FADE_MS)
        self._back.start()

    def _in(self):
        self.dial.orb.fade_in(_FADE_MS)
        self._restart(fresh=False)

    # --- the card
    def _place(self, anchor: QWidget):
        """Under the button, its right edge near the button's, or above it when the screen ends."""
        below = anchor.mapToGlobal(anchor.rect().bottomRight())
        x = below.x() - self.width() + SHADE + 24
        y = below.y() + 6 - SHADE
        screen = QGuiApplication.screenAt(below) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        if y + self.height() > a.bottom():
            y = anchor.mapToGlobal(anchor.rect().topLeft()).y() - 6 - self.height() + SHADE
        x = min(max(x, a.left()), a.right() - self.width())
        self.move(x, max(y, a.top()))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(self.rect()).adjusted(SHADE, SHADE, -SHADE, -SHADE)
        for i, a in enumerate((14, 9, 5)):   # colorpop's soft shadow, a little lower
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(card.adjusted(-i - 1, i + 1, i + 1, i + 4), 14, 14)
        p.setPen(QPen(T("line"), 1))
        p.setBrush(T("tile"))
        p.drawRoundedRect(card, 12, 12)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            self.close()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        self._count.stop()
        self._back.stop()
        self.closed.emit()
        super().closeEvent(e)


def theme_link(text: str, slot):
    from .kit import button
    b = button(text, slot, link=True)
    b.setFont(theme.font(12))
    return b


def value_label():
    lab = label("")
    lab.setFont(theme.font(13, 600, num=True))
    return lab


def slider(lo: int, hi: int, value: int, name: str) -> QSlider:
    s = QSlider(Qt.Horizontal, minimum=lo, maximum=hi, singleStep=1, pageStep=5)
    s.setValue(value)
    s.setCursor(Qt.PointingHandCursor)
    s.setAccessibleName(name)
    return s


def row(left: QWidget, right: QWidget) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(left)
    h.addStretch(1)
    h.addWidget(right)
    return h


_open = None


def pop_bubble(cfg, colors: list, anchor: QWidget, changed, done, closed) -> BubblePop:
    """The card under anchor (kept referenced here: a window with no parent and no reference is collected)."""
    global _open
    pop = _open = BubblePop(cfg, colors, anchor)
    pop.changed.connect(changed)
    pop.done.connect(done)
    pop.closed.connect(closed)
    pop.closed.connect(_forget)
    pop.show()
    return pop


def _forget():
    global _open
    _open = None
