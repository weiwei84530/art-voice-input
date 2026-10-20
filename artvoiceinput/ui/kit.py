"""Building blocks of the redesigned settings window: icons, the switch, cards, chips, segmented buttons, ⓘ."""
from PySide6.QtCore import (Property, QByteArray, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF,
                            QSize, Qt, Signal)
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton,
                               QSizePolicy, QToolTip, QVBoxLayout, QWidget)

from . import theme

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
    svg_renderer(name, color, width).render(p, rect)


def icon(name: str, color: QColor, size: int = 16, width: float = 2.0, dpr: float = 2.0) -> QIcon:
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    draw_icon(p, name, QRectF(0, 0, size, size), color, width)
    p.end()
    return QIcon(pm)


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
        self._anim = QPropertyAnimation(self, b"pos", self, duration=150, easingCurve=QEasingCurve.OutCubic)
        self.toggled.connect(self._slide)

    def _slide(self, on: bool):
        self._anim.stop()
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

    pos = Property(float, _get, _set)

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


class Info(QLabel):
    """ⓘ after a name: its explanation shows while the pointer is on it."""

    def __init__(self, tip: str):
        super().__init__()
        self.tip = tip
        self.setFixedSize(16, 16)
        self.setCursor(Qt.WhatsThisCursor)

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
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height() + 6)), self.tip, self)

    def leaveEvent(self, e):
        QToolTip.hideText()


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

    def __init__(self, items, value=None, kind: str = "chip", big: bool = False, wrap_cols: int = 0):
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
        else:
            lay = FlowLayout(self, spacing=6)
        for key, text, *rest in items:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty(kind, True)
            if big:
                b.setProperty("big", True)
            if rest and rest[0] is not None:
                b.setIcon(rest[0])
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[key] = b
            self.setText(key, text)
            b.clicked.connect(lambda _=False, k=key: self.picked.emit(k))
        self.set(value)

    def setText(self, key, text: str):
        """A button's text; a segment keeps room for its bold (picked) look."""
        b = self.buttons[key]
        b.setText(text)
        if b.property("seg"):
            f = theme.font(13.5 if b.property("big") else 13, 700)
            extra = 24 + (22 if not b.icon().isNull() else 0) + (8 if b.property("big") else 0)
            b.setMinimumWidth(QFontMetrics(f).horizontalAdvance(text) + extra)

    def set(self, value):
        for k, b in self.buttons.items():
            if k == value:
                b.setChecked(True)
                return
        self.group.setExclusive(False)
        for b in self.buttons.values():
            b.setChecked(False)
        self.group.setExclusive(True)

    def value(self):
        return next((k for k, b in self.buttons.items() if b.isChecked()), None)


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
    """A small rounded state label: 已設定 (orange dot) or 未使用 (gray)."""

    def __init__(self, text: str = "", on: bool = False):
        super().__init__(text)
        self.on = on
        self.setFont(theme.font(11.5, 500))
        self.setContentsMargins(9 + 11, 2, 9, 2)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set(self, text: str, on: bool):
        self.on = on
        self.setText(text)
        self.setContentsMargins(9 + (11 if on else 0), 2, 9, 2)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.on:
            p.setPen(Qt.NoPen)
            p.setBrush(T("accbg"))
        else:
            p.setPen(QPen(T("line"), 1))
            p.setBrush(T("tile2"))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.on:
            p.setBrush(T("acc"))
            p.drawEllipse(QPointF(9 + 3, r.center().y()), 3, 3)
        p.setPen(T("acct") if self.on else T("muted"))
        p.setFont(self.font())
        p.drawText(self.contentsRect(), Qt.AlignVCenter | Qt.AlignLeft, self.text())


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
            p.drawText(QRectF(0, 33, self.width(), 16), Qt.AlignCenter, self.name)
        else:
            p.setFont(theme.font(self.glyph_px, 600))
            p.drawText(QRectF(0, 0, self.width(), self.height() - 3), Qt.AlignCenter, self.glyph)
