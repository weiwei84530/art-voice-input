"""Building blocks of the redesigned settings window: icons, the switch, cards, chips, segmented buttons, ⓘ."""
import ctypes
import math
import time

from PySide6.QtCore import (Property, QByteArray, QEasingCurve, QEvent, QObject, QPoint, QPointF, QPropertyAnimation,
                            QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from . import theme

_calm = False


def calm() -> bool:
    """節流模式 (config.orb_lite, on the 系統 page): the settings window skips its animations (page transition,
    hovers, the switch knob, the glow editor's slide) and its endless ones (the ready dot, the state pills)."""
    return _calm


def set_calm(on: bool):
    global _calm
    _calm = on
    Pill._tick()
    for w in QApplication.topLevelWidgets():
        w.update()

# 24x24 line icons (stroke), with an optional filled part
ICONS = {
    "mic": ("M9 6a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0zM5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21", ""),
    "look": ("M12 3.5a8.5 8.5 0 1 1 0 17a8.5 8.5 0 1 1 0-17z", "M12 3.5a8.5 8.5 0 0 1 0 17z"),
    "cmd": ("M4 5h16v11H10l-6 4zM8.5 9.5h7M8.5 12.5h4", ""),
    "bank": ("M5 5.5A2.5 2.5 0 0 1 7.5 3H19v15H7.5A2.5 2.5 0 0 0 5 20.5zM5 20.5A2.5 2.5 0 0 1 7.5 18H19v3H7.5", ""),
    "log": ("M9 6h11M9 12h11M9 18h11M4 5.6v.8M4 11.6v.8M4 17.6v.8", ""),
    "sys": ("M4 7h10M18 7h2M4 17h4M12 17h8M14 7a2 2 0 1 0 4 0a2 2 0 1 0-4 0M8 17a2 2 0 1 0 4 0a2 2 0 1 0-4 0", ""),
    "back": ("M15 5l-7 7 7 7", ""),
    "x": ("M6 6l12 12M18 6L6 18", ""),
    "plus": ("M12 5v14M5 12h14", ""),
    "minus": ("M5 12h14", ""),
    "copy": ("M9 9h10v11H9zM5 15V4h10", ""),
    "arrow": ("M5 12h14M13 6l6 6-6 6", ""),
    "chev": ("M9 6l6 6-6 6", ""),
    "down": ("M12 3v12M7 10l5 5 5-5M4 15v5h16v-5", ""),
    "sun": ("M12 8a4 4 0 1 1 0 8a4 4 0 1 1 0-8zM12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4"
            "M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4", ""),
    "moon": ("M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z", ""),
    "pc": ("M3.5 5h17v11h-17zM9 20h6M12 16v4", ""),
    "search": ("M10.5 4a6.5 6.5 0 1 1 0 13a6.5 6.5 0 1 1 0-13zM15.5 15.5L20 20", ""),
}
# the logo: the microphone, filled, as on the brand block
LOGO = ('<rect x="22" y="6" width="20" height="34" rx="10" fill="{c}"/>'
        '<path d="M15.1 38.8A18 17 0 0 0 48.9 38.8M32 50v8" stroke="{c}" stroke-width="5" stroke-linecap="round" '
        'fill="none"/>')


def svg_renderer(name: str, color: QColor, width: float = 1.9) -> QSvgRenderer:
    d, f = ICONS[name]
    c = color.name()
    a = color.alphaF()
    body = (f'<path d="{d}" fill="none" stroke="{c}" stroke-opacity="{a}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')
    if f:
        body += f'<path d="{f}" fill="{c}" fill-opacity="{a}"/>'
    xml = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'
    return QSvgRenderer(QByteArray(xml.encode()))


def logo_renderer(color: str = "#FFFFFF") -> QSvgRenderer:
    xml = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">{LOGO.format(c=color)}</svg>'
    return QSvgRenderer(QByteArray(xml.encode()))


def draw_icon(p: QPainter, name: str, rect: QRectF, color: QColor, width: float = 1.9):
    if color.alphaF() >= 1 or not ICONS[name][1]:
        svg_renderer(name, color, width).render(p, rect)
        return
    # stroke and fill drawn opaque on a layer, then faded together: where they overlap is not darker
    scale = 2 * max(1.0, p.device().devicePixelRatioF(), abs(p.worldTransform().m11()), abs(p.worldTransform().m22()))
    img = QImage(max(1, round(rect.width() * scale)), max(1, round(rect.height() * scale)),
                 QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    q = QPainter(img)
    q.setRenderHint(QPainter.Antialiasing)
    opaque = QColor(color)
    opaque.setAlphaF(1.0)
    svg_renderer(name, opaque, width).render(q, QRectF(0, 0, img.width(), img.height()))
    q.end()
    p.save()
    p.setOpacity(p.opacity() * color.alphaF())
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.drawImage(rect, img)
    p.restore()


def icon(name: str, color: QColor, size: int = 16, width: float = 2.0, dpr: float = 2.0) -> QIcon:
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    draw_icon(p, name, QRectF(0, 0, size, size), color, width)
    p.end()
    return QIcon(pm)


def crossfade(win: QWidget, ms: int = 220):
    """The window as it looks now laid over it and faded out while what changes under it comes in (外觀模式, the
    setup wizard coming and going); not with 節流模式."""
    if calm() or not win.isVisible():
        return
    cover = QLabel(win)
    cover.setPixmap(win.grab())
    cover.setGeometry(win.rect())
    cover.setAttribute(Qt.WA_TransparentForMouseEvents)
    fx = QGraphicsOpacityEffect(cover, opacity=1.0)
    cover.setGraphicsEffect(fx)
    cover.show()
    cover.raise_()
    anim = QPropertyAnimation(fx, b"opacity", cover, duration=ms, startValue=1.0, endValue=0.0,
                              easingCurve=QEasingCurve.InOutQuad)
    anim.finished.connect(cover.deleteLater)
    anim.start()


def prop(w, **props):
    """Set style-sheet properties (pri=True, dim=True …) and re-polish."""
    for k, v in props.items():
        w.setProperty(k, v)
    w.style().unpolish(w)
    w.style().polish(w)
    return w


def label(text: str = "", **props) -> QLabel:
    lab = QLabel(text)
    for k, v in props.items():
        lab.setProperty(k, v)
    return lab


def dim(text: str = "", wrap: bool = False) -> QLabel:
    lab = label(text, dim=True)
    lab.setWordWrap(wrap)
    return lab


def button(text: str, slot=None, **props) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    for k, v in props.items():
        b.setProperty(k, v)
    if slot is not None:
        b.clicked.connect(slot)
    return b


def card(layout_cls=QVBoxLayout, margins=(18, 16, 18, 16), spacing: int = 12) -> tuple[QFrame, object]:
    f = QFrame(objectName="card")
    f.setAttribute(Qt.WA_StyledBackground)
    lay = layout_cls(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


def sep() -> QFrame:
    f = QFrame(objectName="sep")
    f.setAttribute(Qt.WA_StyledBackground)
    return f


def hbox(*items, spacing: int = 12, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setContentsMargins(*margins)
    h.setSpacing(spacing)
    for it in items:
        if it is None:
            h.addStretch(1)
        elif isinstance(it, int):
            h.addSpacing(it)
        elif isinstance(it, QWidget):
            h.addWidget(it)
        else:
            h.addLayout(it)
    return h


def vbox(*items, spacing: int = 2, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    v = QVBoxLayout()
    v.setContentsMargins(*margins)
    v.setSpacing(spacing)
    for it in items:
        if it is None:
            v.addStretch(1)
        elif isinstance(it, int):
            v.addSpacing(it)
        elif isinstance(it, QWidget):
            v.addWidget(it)
        else:
            v.addLayout(it)
    return v


def titled(title: str, sub: str = "", size: int = 14, weight: int = 500) -> QWidget:
    """A bold name over a gray line (a setting's name and what it does)."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(1)
    t = QLabel(title)
    t.setFont(theme.font(size, weight))
    v.addWidget(t)
    if sub:
        s = dim(sub, wrap=True)
        v.addWidget(s)
        w.sub = s
    w.title = t
    return w


class Hub:
    """The theme of the window, for painted widgets (set by the window)."""
    current = None


def T(key: str, alpha: float | None = None) -> QColor:
    if Hub.current is None:
        c = theme.qcolor(theme.LIGHT[key])
        if alpha is not None:
            c.setAlphaF(alpha)
        return c
    return Hub.current.color(key, alpha)


def dark_frame(w, dark: bool):
    """A window's title bar dark or light (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
    try:
        hwnd = int(w.winId())
        v = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v))
    except (AttributeError, OSError):
        pass


class Switch(QAbstractButton):
    """The 40x22 switch: gray off, orange on, the knob slides."""

    def __init__(self, checked: bool = False, name: str = ""):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)
        self.setAccessibleName(name)
        self._pos = 1.0 if checked else 0.0
        # not "pos": that is QWidget's own position, and animating it moved the switch to its parent's top left
        self._anim = QPropertyAnimation(self, b"knob", self, duration=150, easingCurve=QEasingCurve.OutCubic)
        self.slides = False   # slides even when calm (節流模式's own: calm still held when it was turned off)
        self.toggled.connect(self._slide)

    def _slide(self, on: bool):
        self._anim.stop()
        if calm() and not self.slides:
            self._set(1.0 if on else 0.0)
            return
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def set_quiet(self, on: bool):
        """Checked without signals or the slide."""
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def _get(self):
        return self._pos

    def _set(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get, _set)

    def sizeHint(self):
        return QSize(40, 22)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        off, on = T("line"), T("acc")
        k = self._pos
        c = QColor(round(off.red() + (on.red() - off.red()) * k), round(off.green() + (on.green() - off.green()) * k),
                   round(off.blue() + (on.blue() - off.blue()) * k))
        if not self.isEnabled():
            c.setAlphaF(0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor(0, 0, 0, 60))
        x = 3 + 18 * k
        p.drawEllipse(QRectF(x, 4, 16, 16))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, 3, 16, 16))
        if self.hasFocus() and self.focusPolicy() != Qt.NoFocus and self._keyboard:
            p.setPen(QPen(T("acc"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(-1, -1, 42, 24), 12, 12)

    _keyboard = False

    def focusInEvent(self, e):
        self._keyboard = e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(e)


class Tip(QWidget):
    """The settings window's own tooltip (ⓘ, 回首頁): fades in and out in 120ms. QToolTip's Windows fade looked
    choppy, and it ignored a showText of the tip it was just hiding (same text, same widget)."""
    _one = None
    FADE_MS = 120

    @classmethod
    def ready(cls) -> "Tip":
        """The one tip, laid out and painted once ahead: the first showing took ~300ms and stalled the fade."""
        if cls._one is None:
            cls._one = t = Tip()
            t.text = "說明 ⓘ"
            t._size()
            t.grab()
        return cls._one

    @classmethod
    def show_text(cls, pos: QPoint, text: str, owner: QWidget):
        cls.ready()._show(pos, text, owner)

    @classmethod
    def flash(cls, pos: QPoint, text: str, owner: QWidget, ms: int = 1800):
        """Shown at once and gone after ms (已複製, a word the 詞庫 can't take)."""
        cls.show_text(pos, text, owner)
        tip = cls._one
        tip._flash = getattr(tip, "_flash", None) or QTimer(tip, singleShot=True)
        try:
            tip._flash.timeout.disconnect()
        except (RuntimeError, TypeError):
            pass
        tip._flash.timeout.connect(lambda: cls.hide_text(owner))
        tip._flash.start(ms)

    @classmethod
    def hide_text(cls, owner: QWidget):
        if cls._one is not None and cls._one.owner is owner:
            cls._one._fade(0.0)

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.owner = None
        self.text = ""
        self._arming = False
        self._op = 0.0             # our own record: windowOpacity() read back 1.0 at times (a one-frame flash)
        self._anim = QVariantAnimation(self, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_op)
        self._anim.finished.connect(self._finished)

    def _set_op(self, v):
        if self._arming:   # setting a stopped animation's values reports its old end value
            return
        self._op = float(v)
        self.setWindowOpacity(self._op)

    def _show(self, pos: QPoint, text: str, owner: QWidget):
        self.owner, self.text = owner, text
        self._size()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        self.move(min(max(pos.x(), a.left()), a.right() - self.width()), min(pos.y(), a.bottom() - self.height()))
        self.update()
        if not self.isVisible():
            self._anim.stop()
            self._set_op(0.0)
            self.show()
        self._fade(1.0)

    def _size(self):
        r = QFontMetrics(theme.font(12)).boundingRect(QRect(0, 0, 300, 2000), Qt.TextWordWrap, self.text)
        self.resize(r.width() + 20 + 1, r.height() + 14)

    def _fade(self, end: float):
        if not self.isVisible():
            return
        self._anim.stop()
        self._arming = True
        self._anim.setDuration(max(1, round(self.FADE_MS * abs(end - self._op))))
        self._anim.setStartValue(self._op)
        self._anim.setEndValue(end)
        self._arming = False
        self._anim.start()

    def _finished(self):
        if self._anim.endValue() == 0.0:
            self.hide()
            self.owner = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(T("ink"))
        p.drawRoundedRect(QRectF(self.rect()), 5, 5)
        p.setPen(T("bg"))
        p.setFont(theme.font(12))
        p.drawText(QRectF(self.rect()).adjusted(10, 7, -10, -7), Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
                   self.text)


class TipRouter(QObject):
    """Every tooltip (setToolTip) of a window shown as a Tip: after the pointer rests DELAY on the widget (the user's
    choice, 2026-10-20, for icon buttons, swatches, chips … where an ⓘ beside them doesn't fit), or at once for a
    widget marked quick_tip (辨識紀錄's rows, book and copy: a page read by sweeping the pointer, 2026-10-21); leaving
    one inside another quick_tip widget shows the outer one's again. Qt's own tooltip never shows there."""
    DELAY = 1000

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.window = window
        self.target = None
        self.timer = QTimer(self, singleShot=True, interval=self.DELAY)
        self.timer.timeout.connect(self._fire)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, e):
        t = e.type()
        if t not in _TIP_EVENTS or not isinstance(obj, QWidget) or obj.window() is not self.window:
            return False
        if t == QEvent.ToolTip:
            w = obj
            while w is not None and not w.toolTip():
                w = w.parentWidget()
            if w is not None and w.property("quick_tip"):
                Tip.show_text(e.globalPos() + QPoint(12, 18), w.toolTip(), w)
            return True
        if t == QEvent.Enter:
            if obj.toolTip() and obj.property("quick_tip"):
                Tip.show_text(QCursor.pos() + QPoint(12, 18), obj.toolTip(), obj)
            elif obj.toolTip():
                self.target = obj
                self.timer.start()
        else:
            if obj is self.target:
                self.timer.stop()
                self.target = None
            Tip.hide_text(obj)
            if t == QEvent.Leave and obj.property("quick_tip"):
                w = obj.parentWidget()
                while w is not None and not (w.property("quick_tip") and w.toolTip()):
                    w = w.parentWidget()
                if w is not None and w.underMouse():
                    Tip.show_text(QCursor.pos() + QPoint(12, 18), w.toolTip(), w)
        return False

    def _fire(self):
        w = self.target
        if w is not None and w.isVisible() and w.underMouse() and w.toolTip():
            Tip.show_text(QCursor.pos() + QPoint(12, 18), w.toolTip(), w)


_TIP_EVENTS = {QEvent.ToolTip, QEvent.Enter, QEvent.Leave, QEvent.MouseButtonPress, QEvent.Hide}


class Info(QLabel):
    """ⓘ after a name: its explanation shows (fading in) while the pointer is on it."""

    def __init__(self, tip: str):
        super().__init__()
        self.tip = tip
        self.setFixedSize(16, 16)
        self.setCursor(Qt.WhatsThisCursor)
        Tip.ready()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = T("muted")
        p.setPen(QPen(c, 1.2))
        p.drawEllipse(QRectF(0.8, 0.8, 14.4, 14.4))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(7.1, 3.9, 1.8, 1.8))
        p.drawRoundedRect(QRectF(7.2, 6.6, 1.6, 5.6), 0.8, 0.8)

    def enterEvent(self, e):
        Tip.show_text(self.mapToGlobal(QPoint(0, self.height() + 6)), self.tip, self)

    def leaveEvent(self, e):
        Tip.hide_text(self)

    def hideEvent(self, e):
        Tip.hide_text(self)


def with_info(widget: QWidget, tip: str) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    h.addWidget(widget)
    h.addWidget(Info(tip))
    h.addStretch(1)
    return w


class Choice(QWidget):
    """One of several buttons checked: chips (rounded, orange when picked) or a segmented control."""
    picked = Signal(object)
    settled = Signal()   # a segmented control's card got to the picked segment (at once without a slide)

    def __init__(self, items, value=None, kind: str = "chip", big: bool = False, wrap_cols: int = 0,
                 small: bool = False):
        super().__init__()
        self.group = QButtonGroup(self, exclusive=True)
        self.buttons = {}
        if kind == "seg":
            box = QFrame(objectName="segbox")
            box.setAttribute(Qt.WA_StyledBackground)
            inner = QHBoxLayout(box)
            inner.setContentsMargins(3, 3, 3, 3)
            inner.setSpacing(2)
            outer = QHBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(box)
            outer.addStretch(1)
            lay = inner
            # the picked segment's card, under the buttons: it slides to the one picked (2026-10-21; 外觀模式 waits
            # for it before its cross-fade, which covered it)
            self._pill = _SegPill(box)
            self._pill_anim = QPropertyAnimation(self._pill, b"geometry", self, duration=200,
                                                 easingCurve=QEasingCurve.OutCubic)
            self._pill_anim.finished.connect(self.settled.emit)
            box.installEventFilter(self)
        else:
            lay = FlowLayout(self, spacing=4 if small else 6)
        for key, text, *rest in items:
            b = _Segment(text) if kind == "seg" else QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty(kind, True)
            if big:
                b.setProperty("big", True)
            if small:
                b.setProperty("small", True)
            if rest and rest[0] is not None:
                b.setIcon(rest[0])
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[key] = b
            self.setText(key, text)
            b.clicked.connect(lambda _=False, k=key: self.picked.emit(k))
            if kind == "seg":
                b.toggled.connect(lambda on: on and self._place_pill(True))
        self.set(value)

    def setText(self, key, text: str):
        self.buttons[key].setText(text)

    def set(self, value):
        for k, b in self.buttons.items():
            if k == value:
                b.setChecked(True)
                self._place_pill()
                return
        self.group.setExclusive(False)
        for b in self.buttons.values():
            b.setChecked(False)
        self.group.setExclusive(True)

    def value(self):
        return next((k for k, b in self.buttons.items() if b.isChecked()), None)

    def _place_pill(self, slide: bool = False):
        pill = getattr(self, "_pill", None)
        b = next((b for b in self.buttons.values() if b.isChecked()), None) if pill is not None else None
        if b is None:
            if pill is not None:
                pill.hide()
            return
        self._pill_anim.stop()
        pill.show()
        pill.lower()
        if slide and not calm() and pill.isVisible() and b.width() > 0 and pill.geometry() != b.geometry():
            self._pill_anim.setStartValue(pill.geometry())
            self._pill_anim.setEndValue(b.geometry())
            self._pill_anim.start()
            return
        pill.setGeometry(b.geometry())
        if slide:
            self.settled.emit()

    def eventFilter(self, obj, e):
        # the segments laid out (shown, resized, a text changed): the card goes under the picked one at once
        if e.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            QTimer.singleShot(0, lambda: self._pill_anim.state() != QPropertyAnimation.Running
                              and self._place_pill())
        return False


class _SegPill(QWidget):
    """The picked segment's raised card (was the checked button's own style-sheet background)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(T("line"), 1))
        p.setBrush(T("tile"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)


class _Segment(QPushButton):
    """A segment: as wide as its text in bold (the picked look), so picking it cuts nothing off. Measured in the font
    the style sheet gave the button, which is not the window's font."""

    def sizeHint(self):
        s = super().sizeHint()
        bold = QFont(self.font())
        bold.setWeight(QFont.Bold)
        extra = QFontMetrics(bold).horizontalAdvance(self.text()) - self.fontMetrics().horizontalAdvance(self.text())
        return QSize(s.width() + max(0, extra) + 4, s.height())

    def minimumSizeHint(self):
        return self.sizeHint()


class FlowLayout(QLayout):
    """Items left to right, wrapping to new lines (the chips)."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._space = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        """All on one line."""
        items = [it.sizeHint() for it in self._items]
        if not items:
            return QSize()
        return QSize(sum(s.width() for s in items) + self._space * (len(items) - 1), max(s.height() for s in items))

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line = rect.x(), rect.y(), 0
        for it in self._items:
            if it.widget() is not None and not it.widget().isVisible() and not test and it.widget().isHidden():
                continue
            hint = it.sizeHint()
            nx = x + hint.width() + self._space
            if nx - self._space > rect.right() + 1 and line > 0:
                x, y = rect.x(), y + line + self._space
                nx, line = x + hint.width() + self._space, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x, line = nx, max(line, hint.height())
        return y + line - rect.y()


class Pill(QLabel):
    """A small rounded state label (design M2, 2026-10-20, the user's pick): on, a solid orange pill with a white dot
    that breathes, a soft orange ring around it at its widest when the dot is brightest; off, gray and still. All pills
    breathe together: the phase is the clock's, not the time each was turned on (the user's request)."""
    PERIOD = 1.8      # one breath, seconds
    ROOM = 3          # around the pill, for its ring
    _all = []         # live pills, for the one shared timer
    _timer = None

    def __init__(self, text: str = "", on: bool = False):
        super().__init__(text)
        self.on = on
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.set(text, on)
        Pill._all.append(self)

    def set(self, text: str, on: bool):
        self.on = on
        self.setText(text)
        self.setFont(theme.font(11.5, 700 if on else 500))
        g = self.ROOM
        self.setContentsMargins(g + 9 + (10 if on else 0), g + 2, g + 10, g + 2)
        self._tick()
        self.update()

    @classmethod
    def _tick(cls):
        """Start the shared timer while a breathing pill shows, stop it otherwise."""
        live = not calm() and any(_alive(p) and p.on and p.isVisible() for p in cls._all)
        if cls._timer is None:
            cls._timer = QTimer(interval=33)
            cls._timer.timeout.connect(cls._frame)
        if live and not cls._timer.isActive():
            cls._timer.start()
        elif not live and cls._timer.isActive():
            cls._timer.stop()

    @classmethod
    def _frame(cls):
        cls._all = [p for p in cls._all if _alive(p)]
        for p in cls._all:
            if p.on and p.isVisible():
                p.update()
        cls._tick()

    def showEvent(self, e):
        super().showEvent(e)
        Pill._tick()

    def hideEvent(self, e):
        super().hideEvent(e)
        QTimer.singleShot(0, Pill._tick)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = self.ROOM
        r = QRectF(self.rect()).adjusted(g + 0.5, g + 0.5, -g - 0.5, -g - 0.5)
        rad = r.height() / 2
        if not self.on:
            p.setPen(QPen(T("line"), 1))
            p.setBrush(T("tile2"))
            p.drawRoundedRect(r, rad, rad)
            p.setPen(T("muted"))
            p.setFont(self.font())
            p.drawText(self.contentsRect(), Qt.AlignVCenter | Qt.AlignLeft, self.text())
            return
        # breath 0..1 from the clock: 1 = the ring widest and the dot brightest
        still = calm()
        b = 0.0 if still else 0.5 - 0.5 * math.cos(2 * math.pi * (time.monotonic() % self.PERIOD) / self.PERIOD)
        p.setPen(Qt.NoPen)
        if b > 0.01:
            ring = QColor(theme.ACCENT)
            ring.setAlphaF(0.16 * b + 0.06)
            p.setBrush(ring)
            w = g * b
            p.drawRoundedRect(r.adjusted(-w, -w, w, w), rad + w, rad + w)
        p.setBrush(T("acc"))
        p.drawRoundedRect(r, rad, rad)
        dot = QColor("#FFFFFF")
        dot.setAlphaF(1.0 if still else 0.45 + 0.55 * b)
        p.setBrush(dot)
        p.drawEllipse(QPointF(r.x() + 9 + 3, r.center().y()), 3, 3)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(self.font())
        p.drawText(self.contentsRect(), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class Slides(QWidget):
    """Panes side by side, one shown: going to another slides the shown one out to the left and the next in from the
    right (design A1, 2026-10-20, the user's pick for the glow editor). As tall as the tallest pane."""
    MS = 420

    def __init__(self, *panes: QWidget):
        super().__init__()
        self.panes = list(panes)
        for w in self.panes:
            w.setParent(self)
        self.index = 0
        self._pos = 0.0
        self._anim = QVariantAnimation(self, duration=self.MS, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)

    def go(self, index: int):
        if index == self.index and not self._anim.state():
            return
        self.index = index
        self._anim.stop()
        if calm() or not self.isVisible():
            self._set_pos(float(index))
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(float(index))
        self._anim.start()

    def _set_pos(self, v):
        self._pos = float(v)
        self._place()

    def _place(self):
        w, h = self.width(), self.height()
        for i, pane in enumerate(self.panes):
            x = round((i - self._pos) * (w + 24))
            pane.setGeometry(x, 0, w, h)
            pane.setVisible(-w - 24 < x < w + 24)

    def resizeEvent(self, e):
        self._place()

    def sizeHint(self):
        hints = [p.sizeHint() for p in self.panes]
        return QSize(max(s.width() for s in hints), max(s.height() for s in hints))

    def minimumSizeHint(self):
        hints = [p.minimumSizeHint() for p in self.panes]
        return QSize(max(s.width() for s in hints), max(s.height() for s in hints))


def _alive(w) -> bool:
    try:
        w.objectName()
        return True
    except RuntimeError:   # the C++ widget is gone
        return False


class Keycap(QWidget):
    """A key drawn as a keycap: a glyph over its name (標點), or one big glyph."""

    def __init__(self, glyph: str, name: str = "", size=(0, 54), glyph_px: int = 22):
        super().__init__()
        self.glyph, self.name, self.glyph_px = glyph, name, glyph_px
        if size[0]:
            self.setFixedWidth(size[0])
        self.setFixedHeight(size[1])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(T("line"), 1))
        p.setBrush(T("line"))
        p.drawRoundedRect(r, 6, 6)
        p.setBrush(T("tile2"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(r.adjusted(1, 1, -1, -3), 5, 5)
        p.setPen(T("ink"))
        long = len(self.glyph) > 1 and not self.glyph.isascii()
        if self.name:
            # centered by the glyph's own ink: ，。、 sit in the bottom left of their square
            p.setFont(theme.font(15 if long else self.glyph_px, 700))
            ink = p.fontMetrics().tightBoundingRect(self.glyph)
            box = QRectF(0, 4, self.width(), 30)
            p.drawText(QPointF(box.center().x() - ink.center().x(), box.center().y() - ink.center().y()), self.glyph)
            p.setPen(T("muted"))
            p.setFont(theme.font(11.5))
            # names on lines of their own (逗號 over 逗點), the block centered under the glyph
            lines = self.name.split("\n")
            top = 33 + (self.height() - 54 - 16 * (len(lines) - 1)) / 2
            for i, line in enumerate(lines):
                p.drawText(QRectF(0, top + 16 * i, self.width(), 16), Qt.AlignCenter, line)
        else:
            p.setFont(theme.font(self.glyph_px, 600))
            p.drawText(QRectF(0, 0, self.width(), self.height() - 3), Qt.AlignCenter, self.glyph)
