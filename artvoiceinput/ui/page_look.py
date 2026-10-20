"""外觀與聲音: a preview (a window with the draft marked, the floating button, the glow along the edges) beside the
edge glow (styles and motion; 自訂顏色、速度與邊緣 slides its parameters, colors and edges in their place), both staying
put; below them, scrolling, the button look and size beside the draft's mark color, the sounds across."""
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QColorDialog, QComboBox, QGridLayout, QScrollArea, QSlider, QVBoxLayout, QWidget)

from .. import cues
from .. import glow as glowmod
from ..config import BUTTON_SCALE_RANGE
from ..floatbtn import _SIZE as _MIC_SIZE, OrbButton, _hover_curve, _paint_mic
from ..highlight import COLORS as MARK_COLORS
from ..orbs import LOOKS, draw as draw_orb, palette
from . import theme
from .kit import Choice, Info, Slides, T, button, calm, card, dim, hbox, icon, label, sep

PREVIEW_H = 132     # the preview at least (it is as tall as the glow card beside it)
_BAR = 10           # the scroll bar's width (theme)
_NAME_W = 60        # the glow editor's names column
BUSY = "錄音中無法使用"   # ▶ 預覽 / ▶ 試聽 while listening
PREVIEW_MS = 3300   # a glow previewed shows this long, its fade-out included (App._preview_glow)
_SET_PAUSE = 0.8    # seconds between the start and the end sound of a set
SLIDERS = (("turn", "旋轉速度", 0, 40), ("pulse", "呼吸", 0, 100), ("depth", "寬度", 40, 200), ("bright", "亮度", 30, 160))


def _colors_of(style_id: str, edits: dict) -> list:
    return palette(glowmod.style_for(style_id, edits)) if style_id else palette(None)


class OrbSample(OrbButton):
    """The floating button's look, animated, at its real size; a click plays listening starting and ending as the
    floating button would: grown and faded out with 錄音時隱藏按鈕 (`keep()` False), else smaller and faster."""

    def __init__(self, parent, size: int = 44):
        super().__init__(size, room=1.7, parent=parent)
        self.keep = lambda: False   # the page gives float_keep
        self._back = QTimer(self, singleShot=True, timeout=self._end)
        self.clicked.connect(self._demo)
        self.setToolTip("點一下看開關麥克風時的動畫")
        self.setMouseTracking(True)

    def _fit(self):
        side = round(self.base * BUTTON_SCALE_RANGE[1] / 100 * self.room)
        self.margin = (side - self.bsize) // 2
        self.setFixedSize(side, side)

    def _gone(self):
        pass

    # its widget is much bigger than the look (room for the burst): only the look answers the pointer, else it
    # stayed grown with the pointer beside it (2026-10-21, the user's report)
    def _on_look(self, pos) -> bool:
        c = self.width() / 2
        return (pos.x() - c) ** 2 + (pos.y() - c) ** 2 <= (self.bsize * 0.56) ** 2

    def _hover(self, over: bool):
        if over == self._over:
            return
        self._over = over
        self.setCursor(Qt.PointingHandCursor if over else Qt.ArrowCursor)
        if not self.leaving:
            curve, ms = _hover_curve()
            self._scale_to(self._rest(), ms, curve)

    def enterEvent(self, e):
        self._hover(self._on_look(e.position()))

    def mouseMoveEvent(self, e):
        self._hover(self._on_look(e.position()))

    def leaveEvent(self, e):
        self._hover(False)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._on_look(e.position()):
            self.clicked.emit()

    def _demo(self):
        if self._back.isActive() or self.leaving:
            return
        if self.keep():
            self.set_active(True)
            self._back.start(1600)
        else:
            self.burst()
            self._back.start(900)

    def _end(self):
        if self.active:
            self.set_active(False)
        else:
            self.come_back()


class Preview(QWidget):
    """A window on a desk: text with the draft marked, the floating button, and the glow moving along the edges."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(PREVIEW_H)
        self.colors = palette(None)
        self.glow_on = True
        self.mark = QColor(MARK_COLORS[0][0])
        self.orb = OrbSample(self)
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=40, timeout=lambda: None if calm() else self.update())

    def showEvent(self, e):
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()

    def resizeEvent(self, e):
        self.orb.move(self.width() - 52 - self.orb.width() // 2, (self.height() - self.orb.height()) // 2)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, T("wall0"))
        g.setColorAt(0.6, T("wall1"))
        g.setColorAt(1, T("wall2"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, 6, 6)
        p.save()
        p.setClipRect(r)
        if self.glow_on:
            self._edges(p, r)
        # the window
        w = QRectF(22, 22, r.width() - 22 - 104, r.height() - 44)
        for i, a in enumerate((10, 6, 3)):
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(w.adjusted(-i, 4 + i, i, 8 + i), 7, 7)
        p.setBrush(T("tile"))
        p.setPen(QPen(T("line"), 1))
        p.drawRoundedRect(w, 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(T("tile2"))
        p.drawRoundedRect(QRectF(w.x() + 0.5, w.y() + 0.5, w.width() - 1, 18), 6, 6)
        p.setFont(theme.font(13.5))
        fm = p.fontMetrics()
        a, b = "明天下午三點開會，", "記得帶上週的報告"
        x, y = w.x() + 12, w.y() + 30
        p.setPen(T("ink"))
        p.drawText(QPointF(x, y + fm.ascent()), a)
        bx = x + fm.horizontalAdvance(a)
        p.setPen(Qt.NoPen)
        p.setBrush(self.mark)
        p.drawRoundedRect(QRectF(bx, y, fm.horizontalAdvance(b), fm.height()), 2, 2)
        p.setPen(T("ink"))
        p.drawText(QPointF(bx, y + fm.ascent()), b)
        p.restore()
        p.setPen(QPen(T("line"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

    def _edges(self, p, r):
        """The colors run along the four edges, fading inward."""
        shift = 0.0 if calm() else ((time.monotonic() - self._t0) / 4.0) % 1.0
        cols = [QColor(c) for c in self.colors] + [QColor(self.colors[0])]
        for horizontal, rect, start, end in (
                (True, QRectF(r.left(), r.top(), r.width(), 14), r.topLeft(), r.topRight()),
                (True, QRectF(r.left(), r.bottom() - 14, r.width(), 14), r.bottomLeft(), r.bottomRight()),
                (False, QRectF(r.left(), r.top(), 14, r.height()), r.topLeft(), r.bottomLeft()),
                (False, QRectF(r.right() - 14, r.top(), 14, r.height()), r.topRight(), r.bottomRight())):
            g = QLinearGradient(start, end)
            g.setSpread(QLinearGradient.RepeatSpread)
            n = len(cols) - 1
            for i, c in enumerate(cols):
                g.setColorAt(((i / n) + shift) % 1.0 if i < n else 1.0, c)
            g.setColorAt(0.0, cols[0] if shift == 0 else _mix(cols, shift))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            # inward falloff by stacking thinner strips
            for k, a in ((14, 0.18), (9, 0.3), (5, 0.45)):
                p.setOpacity(a)
                rr = QRectF(rect)
                if horizontal:
                    rr.setHeight(k)
                    if rect.top() > r.top():
                        rr.moveBottom(rect.bottom())
                else:
                    rr.setWidth(k)
                    if rect.left() > r.left():
                        rr.moveRight(rect.right())
                p.drawRect(rr)
        p.setOpacity(1)


def _mix(cols, k):
    n = len(cols) - 1
    pos = (1 - k) * n
    i = int(pos) % n
    f = pos - int(pos)
    a, b = cols[i], cols[i + 1]
    return QColor(round(a.red() + (b.red() - a.red()) * f), round(a.green() + (b.green() - a.green()) * f),
                  round(a.blue() + (b.blue() - a.blue()) * f))


class LookTile(QAbstractButton):
    """A button look: a frame of it over its name."""

    def __init__(self, key: str, name: str):
        super().__init__()
        self.key, self.name = key, name
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(64)
        self.setAccessibleName(name)
        self.colors = palette(None)
        self._pm = None

    def set_colors(self, colors):
        self.colors = colors
        self._pm = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        if self.isChecked() or self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(T("accbg") if self.isChecked() else T("tile2"))
            p.drawRoundedRect(r, 6, 6)
        if self.key == "mic":
            p.save()
            p.translate(r.center().x() - 17, 4)
            p.scale(34 / _MIC_SIZE, 34 / _MIC_SIZE)
            _paint_mic(p)
            p.restore()
        else:
            if self._pm is None:
                self._pm = draw_orb(self.key, 48, self.devicePixelRatioF(), 0.3, 0.0, self.colors)
            p.drawPixmap(QPointF(r.center().x() - 24, -3), self._pm)
        p.setPen(T("ink") if self.isChecked() else T("muted"))
        p.setFont(theme.font(11.5, 700 if self.isChecked() else 400))
        name = self.name.replace("（原始）", "")
        p.drawText(QRectF(0, 44, r.width(), 18), Qt.AlignCenter, name)


class GlowTile(QAbstractButton):
    """A glow style: a bar of its colors over its name (已編輯 when changed); 關閉 for none."""

    def __init__(self, key: str, name: str):
        super().__init__()
        self.key, self.name = key, name
        self.colors, self.edited = [], False
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        self.setAccessibleName(name)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        p.setPen(QPen(T("acc"), 2) if on else QPen(T("line"), 1))
        p.setBrush(T("tile") if on else T("tile2"))
        p.drawRoundedRect(r, 5, 5)
        bar = QRectF(r.x() + 7, r.y() + 7, r.width() - 14, 8)
        p.setPen(Qt.NoPen)
        if self.colors:
            g = QLinearGradient(bar.topLeft(), bar.topRight())
            for i, c in enumerate(self.colors):
                g.setColorAt(i / max(1, len(self.colors) - 1), QColor(c))
            p.setBrush(g)
        else:
            p.setBrush(T("line"))
        p.drawRoundedRect(bar, 4, 4)
        p.setPen(T("ink") if on else T("muted"))
        p.setFont(theme.font(12, 700 if on else 400))
        p.drawText(QRectF(r.x() + 7, r.y() + 18, r.width() - 14, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   self.name + ("＊" if self.edited else ""))


class Swatch(QAbstractButton):
    """A color square (the draft's mark: 字 on it, as on a page)."""

    def __init__(self, color: str, text: str = "字", size: int = 32):
        super().__init__()
        self.color, self.text_ = color, text
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.isChecked():
            p.setPen(QPen(T("acc"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        p.setPen(QPen(T("line"), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(r, 5, 5)
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(r, 5, 5)
        if self.text_:
            p.setPen(QColor("#15171A"))
            p.setFont(theme.font(13, 700))
            p.drawText(r, Qt.AlignCenter, self.text_)


class MarkOption(QAbstractButton):
    """A mark color with its name (design A3); color "" draws a + (自訂 with no color of its own yet)."""

    def __init__(self, color: str, name: str):
        super().__init__()
        self.color, self.name = color, name
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setAccessibleName(name)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        if self.isChecked() or self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(T("accbg") if self.isChecked() else T("tile2"))
            p.drawRoundedRect(r, 6, 6)
        sw = QRectF(6, (r.height() - 22) / 2, 22, 22)
        if self.color:
            p.setPen(QPen(T("line"), 1))
            p.setBrush(QColor("#FFFFFF"))
            p.drawRoundedRect(sw, 5, 5)
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(sw, 5, 5)
        else:
            p.setPen(QPen(T("muted"), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(sw.adjusted(0.75, 0.75, -0.75, -0.75), 5, 5)
            p.drawLine(sw.center() - QPointF(5, 0), sw.center() + QPointF(5, 0))
            p.drawLine(sw.center() - QPointF(0, 5), sw.center() + QPointF(0, 5))
        p.setPen(T("ink") if self.color or self.isChecked() else T("muted"))
        p.setFont(theme.font(12.5, 700 if self.isChecked() else 500))
        p.drawText(QRectF(36, 0, r.width() - 38, r.height()), Qt.AlignLeft | Qt.AlignVCenter, self.name)


class LookPage(QWidget):
    title = "外觀與聲音"

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self.listening = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        # 2026-10-21, the user's design: the preview and the glow stay put (the glow's editor slides in its place,
        # design A1, so a change is seen while editing); the button looks, the mark colors and 提示音 scroll below
        top = QGridLayout()
        top.setSpacing(12)
        top.setContentsMargins(0, 0, _BAR, 0)   # as wide as the cards below, beside their scroll bar
        top.setColumnStretch(0, 1)
        top.setColumnStretch(1, 1)
        self.preview = Preview()
        self.preview.orb.keep = lambda: self.cfg.float_keep
        top.addWidget(self.preview, 0, 0)

        # 螢幕邊緣光暈: the styles, and 自訂顏色、速度與邊緣 sliding in their place (design A1)
        c_glow, c = card()
        c.setSpacing(10)
        self.preview_button = button("▶ 預覽", self._preview_glow)
        self._preview_done = QTimer(self, singleShot=True, interval=PREVIEW_MS, timeout=self._show_glow)
        self.custom_name = dim("")
        self.edited_badge = label("已編輯", badge=True)
        self.edited_badge.setFixedHeight(18)
        c.addLayout(hbox(label("螢幕邊緣光暈", h3=True), Info("麥克風開著時，螢幕邊緣亮起一圈光，講話時會變亮。"
                                                         "選了、調了或按「預覽」會先亮一下讓你看"),
                         self.custom_name, self.edited_badge, None, self.preview_button, spacing=6))
        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(8)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.glows = {}
        for i, (key, name) in enumerate([("", "關閉")] + [(st.id, st.name) for st in glowmod.STYLES]):
            t = GlowTile(key, name)
            t.clicked.connect(lambda _=False, k=key: self._glow(k))
            self.glows[key] = t
            grid.addWidget(t, i // 4, i % 4)
        mv.addLayout(grid)
        self.motions = Choice(list(glowmod.MOTIONS.items()))
        self.motions.picked.connect(self._motion)
        mv.addWidget(self.motions)
        mv.addStretch(1)
        self.custom_open = button("自訂顏色、速度與邊緣", lambda: self._custom(True), chip=True)
        self.custom_open.setIcon(icon("chev", T("muted"), 14, 2.0))
        self.custom_open.setLayoutDirection(Qt.RightToLeft)
        mv.addLayout(hbox(self.custom_open, None))

        # the editor: every name in one column, every control starting at the sliders' left; back where
        # 自訂顏色、速度與邊緣 was, 恢復預設 across from it
        edit = QWidget()
        ev = QVBoxLayout(edit)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(8)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(10)
        g.setColumnMinimumWidth(3, 10)
        for col in (1, 5):
            g.setColumnStretch(col, 1)

        def name(text: str):
            n = label(text)
            n.setFixedWidth(_NAME_W)
            return n

        self.color_row = hbox(spacing=4)
        g.addWidget(name("顏色"), 0, 0)
        g.addLayout(self.color_row, 0, 1, 1, 6)
        self.sliders, self.slider_values = {}, {}
        for i, (key, text, lo, hi) in enumerate(SLIDERS):
            sl = QSlider(Qt.Horizontal, minimum=lo, maximum=hi)
            sl.setCursor(Qt.PointingHandCursor)
            sl.valueChanged.connect(lambda val, k=key, w=sl: self._glow_edited(k, val / 100, save=not w.isSliderDown()))
            sl.valueChanged.connect(lambda val, k=key: self.slider_values[k].setText(str(val)))
            sl.sliderReleased.connect(lambda: self._glow_edited(None, None))
            n = label("")
            n.setFont(theme.font(13, 600, num=True))
            n.setFixedWidth(28)
            n.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.sliders[key], self.slider_values[key] = sl, n
            row, col = 1 + i // 2, (i % 2) * 4
            g.addWidget(name(text), row, col)
            g.addWidget(sl, row, col + 1)
            g.addWidget(n, row, col + 2)
        self.edges = Choice([(k, val[0]) for k, val in glowmod.EDGES.items()], small=True)
        self.edges.picked.connect(self._edges)
        g.addWidget(name("亮哪幾邊"), 3, 0)
        g.addWidget(self.edges, 3, 1, 1, 6)
        ev.addLayout(g)
        ev.addStretch(1)
        self.custom_back = button("回到光暈樣式", lambda: self._custom(False), chip=True)
        self.custom_back.setIcon(icon("back", T("muted"), 14, 2.0))
        self.reset_button = button("恢復預設", self._reset_glow, chip=True)
        ev.addLayout(hbox(self.custom_back, None, self.reset_button))
        self.glow_slides = Slides(main, edit)
        c.addWidget(self.glow_slides, 1)
        top.addWidget(c_glow, 0, 1)
        v.addLayout(top)

        # below, scrolling
        lower = QScrollArea()
        lower.setWidgetResizable(True)
        lower.setFrameShape(QScrollArea.NoFrame)
        lower.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lower.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        lower.setMinimumHeight(80)
        body = QWidget(objectName="scrollBody")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(12)
        lower.setWidget(body)
        v.addWidget(lower, 1)
        mid = QGridLayout()
        mid.setSpacing(12)
        mid.setColumnStretch(0, 1)
        mid.setColumnStretch(1, 1)
        # 按鈕樣式
        c_look, c = card()
        c.layout().setSpacing(10)
        c.addLayout(hbox(label("按鈕樣式", h3=True), Info("浮動按鈕和語音氣泡的樣子：原本的麥克風，或跟光暈同色的能量球"
                                                       "（沒開光暈時用彩虹的顏色）。上面預覽裡的按鈕可以點一下看動畫"),
                         None, spacing=6))
        grid = QGridLayout()
        grid.setSpacing(4)
        self.looks = {}
        for i, (key, text) in enumerate(LOOKS.items()):
            t = LookTile(key, text)
            t.clicked.connect(lambda _=False, k=key: self._look(k))
            self.looks[key] = t
            grid.addWidget(t, i // 6, i % 6)
        c.addLayout(grid)
        c.addWidget(sep())
        self.scale = QSlider(Qt.Horizontal, minimum=BUTTON_SCALE_RANGE[0], maximum=BUTTON_SCALE_RANGE[1],
                             singleStep=5, pageStep=5)
        self.scale.setCursor(Qt.PointingHandCursor)
        self.scale.valueChanged.connect(self._scale_moved)
        self.scale.sliderReleased.connect(self._scale_done)
        self.scale_text = label("")
        self.scale_text.setFont(theme.font(14, 600, num=True))
        self.scale_text.setFixedWidth(90)
        c.addLayout(hbox(label("大小", b14=True), self.scale, self.scale_text))
        c.addStretch(1)
        mid.addWidget(c_look, 0, 0)
        # 草稿反白顏色: named colors in three columns, 自訂 last (design A3)
        c_mark, c = card()
        c.addLayout(hbox(label("草稿反白顏色", h3=True), Info("麥克風開著時，講完還可能被修正的字會疊上這個顏色，定稿後消失"),
                         None, spacing=6))
        mark_grid = QGridLayout()
        mark_grid.setSpacing(4)
        self.marks = {}
        for i, (color, text) in enumerate(MARK_COLORS):
            m = MarkOption(color, text)
            m.clicked.connect(lambda _=False, col=color: self._mark(col))
            self.marks[color.upper()] = m
            mark_grid.addWidget(m, i // 3, i % 3)
        self.mark_custom = MarkOption("", "自訂")
        self.mark_custom.clicked.connect(self._pick_mark)
        mark_grid.addWidget(self.mark_custom, len(MARK_COLORS) // 3, len(MARK_COLORS) % 3)
        c.addLayout(mark_grid)
        c.addStretch(1)
        mid.addWidget(c_mark, 0, 1)
        bv.addLayout(mid)

        # 提示音, across
        c_sound, c = card()
        c.layout().setSpacing(10)
        self.listen_button = button("▶ 試聽", self._play_sounds)
        self._sound_done = QTimer(self, singleShot=True, timeout=self._show_sounds)
        self._set_timer = QTimer(self, singleShot=True, timeout=lambda: cues.play(self._set_timer.property("cue"), "stop"))
        c.addLayout(hbox(label("提示音", h3=True), Info("開始音在麥克風打開時、結束音在關掉時播放。同一組的開始音與結束音"
                                                     "一起選；選「自定義」可分別挑選"), None, self.listen_button, spacing=6))
        sets = [(cid, text) for cid, text, *_ in cues.SOUNDS] + [("", "無"), (None, "自定義")]
        self.sound_sets = Choice(sets)
        self.sound_sets.picked.connect(self._sound_set)
        c.addWidget(self.sound_sets)
        self.start_box, self.stop_box = QComboBox(), QComboBox()
        for box, kind in ((self.start_box, "start"), (self.stop_box, "stop")):
            for cid, text, *_ in cues.SOUNDS:
                box.addItem(text, cid)
            box.addItem("無", "")
            box.currentIndexChanged.connect(lambda _=0, b=box, k=kind: self._sound(b, k))
        self.custom_sounds = QWidget()
        self.custom_sounds.setLayout(hbox(label("開始"), self.start_box, 12, label("結束"), self.stop_box, None,
                                          spacing=6))
        c.addWidget(self.custom_sounds)
        bv.addWidget(c_sound)
        bv.addStretch(1)
        self._live = QTimer(self, singleShot=True, interval=80, timeout=self._preview_glow)

    # --- values ---
    def load(self):
        cfg = self.cfg
        for k, t in self.looks.items():
            t.setChecked(k == cfg.button_look)
        self.scale.blockSignals(True)
        self.scale.setValue(cfg.button_scale)
        self.scale.blockSignals(False)
        self._scale_text(cfg.button_scale)
        self.motions.set(cfg.glow_motion)
        self.edges.set(cfg.glow_edges)
        for box, cid in ((self.start_box, cfg.start_sound), (self.stop_box, cfg.stop_sound)):
            box.blockSignals(True)
            box.setCurrentIndex(max(0, box.findData(cid)))
            box.blockSignals(False)
        self.sound_sets.set(cfg.start_sound if cfg.start_sound == cfg.stop_sound else None)
        self._show_glow()
        self._show_mark()
        self._show_sounds()

    def summary(self) -> str:
        cfg = self.cfg
        look = LOOKS.get(cfg.button_look, "").replace("（原始）", "")
        glow = glowmod.BY_ID[cfg.glow].name + "光暈" if cfg.glow in glowmod.BY_ID else "不開光暈"
        sound = dict((c, n) for c, n, *_ in cues.SOUNDS).get(cfg.start_sound, "")
        sound = f"{sound} 提示音" if cfg.start_sound == cfg.stop_sound and sound else \
            "沒有提示音" if not (cfg.start_sound or cfg.stop_sound) else "自定義提示音"
        return f"{look}按鈕、{glow}、{sound}"

    def restyle(self):
        self.preview.update()
        self.custom_open.setIcon(icon("chev", T("muted"), 14, 2.0))
        self.custom_back.setIcon(icon("back", T("muted"), 14, 2.0))

    def hideEvent(self, e):
        """Back to the styles when the page is left."""
        self._custom(False)
        super().hideEvent(e)

    # --- button look ---
    def _look(self, key: str):
        self.cfg.button_look = key
        for k, t in self.looks.items():
            t.setChecked(k == key)
        self.win.save()
        self._show_orb()

    def _scale_text(self, value: int):
        self.scale_text.setText(f"{value}%（標準）" if value == 100 else f"{value}%")

    def _scale_moved(self, value: int):
        self._scale_text(value)
        self.cfg.button_scale = value
        self._show_orb()
        if not self.scale.isSliderDown():
            self.win.save()

    def _scale_done(self):
        self.cfg.button_scale = self.scale.value()
        self.win.save()

    def refresh_orb(self):
        """節流模式 changed (the 系統 page)."""
        self._show_orb()

    def _show_orb(self):
        colors = _colors_of(self.cfg.glow, self.cfg.glow_edits)
        self.preview.orb.set_look(self.cfg.button_look, colors, self.cfg.orb_lite, self.cfg.button_scale)
        for t in self.looks.values():
            if t.colors != colors:
                t.set_colors(colors)

    # --- glow ---
    def _glow(self, key: str):
        self.cfg.glow = key
        self.win.save()
        self._show_glow()
        self._preview_glow()

    def _motion(self, key: str):
        self.cfg.glow_motion = key
        self.win.save()
        self._preview_glow()

    def _edges(self, key: str):
        self.cfg.glow_edges = key
        self.win.save()
        self._preview_glow()

    def _params(self) -> dict:
        style_id = self.cfg.glow or glowmod.STYLES[0].id
        base = glowmod.params(glowmod.BY_ID[style_id])
        edits = self.cfg.glow_edits.get(style_id, {})
        return {**base, **{k: v for k, v in edits.items() if k in glowmod.PARAM_KEYS}}

    def _show_glow(self):
        cfg = self.cfg
        on = bool(cfg.glow)
        for k, t in self.glows.items():
            t.setChecked(k == cfg.glow)
            t.colors = palette(glowmod.style_for(k, cfg.glow_edits)) if k else []
            t.edited = bool(k) and glowmod.edited(k, cfg.glow_edits)
            t.update()
        self.motions.setEnabled(on)
        playing = self._preview_done.isActive()
        self.preview_button.setEnabled(on and not playing and not self.listening)
        self.preview_button.setText(BUSY if self.listening else "播放中…" if playing else "▶ 預覽")
        self.custom_open.setVisible(on)
        if not on and self.glow_slides.index:
            self.glow_slides.go(0)
        edited = on and glowmod.edited(cfg.glow, cfg.glow_edits)
        editing = self.glow_slides.index == 1
        self.edited_badge.setVisible(edited and editing)
        self.reset_button.setEnabled(edited)
        self.custom_name.setText(f"／ 自訂{glowmod.BY_ID[cfg.glow].name}" if on else "")
        self.custom_name.setVisible(editing)
        c = self._params()
        for key, s in self.sliders.items():
            s.blockSignals(True)
            s.setValue(round(float(c[key]) * 100))
            s.blockSignals(False)
            self.slider_values[key].setText(str(s.value()))
        while self.color_row.count():
            w = self.color_row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for i, color in enumerate(c["colors"]):
            sw = Swatch(color, "", 26)
            sw.setToolTip("點一下換顏色")
            sw.clicked.connect(lambda _=False, i=i: self._glow_color(i))
            self.color_row.addWidget(sw)
        if len(c["colors"]) < glowmod.MAX_COLORS:
            self.color_row.addWidget(button("＋", lambda: self._glow_color(-1), ib=True))
        if len(c["colors"]) > 2:
            self.color_row.addWidget(button("－", self._glow_fewer, ib=True))
        self.color_row.addStretch(1)
        self.preview.colors = _colors_of(cfg.glow, cfg.glow_edits)
        self.preview.glow_on = on
        self.preview.update()
        self._show_orb()

    def _custom(self, open_: bool):
        """自訂顏色、速度與邊緣 slides in over the styles (open_), or back."""
        self.glow_slides.go(1 if open_ and self.cfg.glow else 0)
        self._show_glow()

    def set_listening(self, on: bool):
        """Listening started or ended: nothing previews or plays meanwhile (the glow shows already, a sound would be
        recorded)."""
        self.listening = on
        self._show_glow()
        self._show_sounds()

    def _glow_edited(self, key, value, save: bool = True):
        """A parameter of the style picked changed (key None: a slider let go). While a slider is dragged the glow
        follows it (at most every 0.08s), saved when let go. Only what differs from the style is kept."""
        style_id = self.cfg.glow
        if not style_id:
            return
        c = self._params()
        if key is not None:
            c[key] = round(value, 2) if isinstance(value, float) else value
        base = glowmod.params(glowmod.BY_ID[style_id])
        changed = {k: v for k, v in c.items() if v != base[k]}
        edits = dict(self.cfg.glow_edits)
        if changed:
            edits[style_id] = changed
        else:
            edits.pop(style_id, None)
        self.cfg.glow_edits = edits
        if save:
            self.win.save()
            self._show_glow()
        if not self._live.isActive():
            self._live.start()

    def _glow_color(self, i: int):
        colors = list(self._params()["colors"])
        c = QColorDialog.getColor(QColor(colors[i] if i >= 0 else colors[-1]), self, "光暈顏色")
        if not c.isValid():
            return
        if i >= 0:
            colors[i] = c.name()
        else:
            colors.append(c.name())
        self._glow_edited("colors", colors)

    def _glow_fewer(self):
        self._glow_edited("colors", list(self._params()["colors"])[:-1])

    def _reset_glow(self):
        edits = dict(self.cfg.glow_edits)
        edits.pop(self.cfg.glow, None)
        self.cfg.glow_edits = edits
        self.win.save()
        self._show_glow()
        self._preview_glow()

    def _preview_glow(self):
        """The real glow shown for a moment (App._preview_glow); ▶ 預覽 disabled meanwhile."""
        if self.cfg.glow and not self.win._loading and not self.listening:
            self.win.glow_preview.emit(self.cfg.glow)
            self._preview_done.start()
            self.preview_button.setEnabled(False)
            self.preview_button.setText("播放中…")

    # --- the draft's mark ---
    def _show_mark(self):
        color = self.cfg.highlight_color.upper()
        preset = self.marks.get(color)
        for m in self.marks.values():
            m.setChecked(m is preset)
        self.mark_custom.setChecked(preset is None)
        self.mark_custom.color = "" if preset is not None else color
        self.mark_custom.update()
        self.preview.mark = QColor(color)
        self.preview.update()

    def _mark(self, color: str):
        self.cfg.highlight_color = color
        self.win.save()
        self._show_mark()

    def _pick_mark(self):
        c = QColorDialog.getColor(QColor(self.cfg.highlight_color), self, "草稿反白顏色", QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self.cfg.highlight_color = c.name(QColor.HexArgb).upper()
            self.win.save()
        self._show_mark()

    # --- sounds ---
    def _sound_set(self, cid):
        if cid is not None:
            for box in (self.start_box, self.stop_box):
                box.blockSignals(True)
                box.setCurrentIndex(box.findData(cid))
                box.blockSignals(False)
            self.cfg.start_sound = self.cfg.stop_sound = cid
            self.win.save()
            if not self.listening:
                self._play_sounds()
        self._show_sounds()

    def _sound(self, box, kind: str):
        setattr(self.cfg, f"{kind}_sound", box.currentData())
        self.win.save()
        if box.currentData() and not self.listening:
            cues.play(box.currentData(), kind)
            self._playing(cues.duration(box.currentData(), kind))
        self._show_sounds()

    def _show_sounds(self):
        self.custom_sounds.setVisible(self.sound_sets.value() is None and self.sound_sets.buttons[None].isChecked())
        playing = self._sound_done.isActive()
        self.listen_button.setEnabled(bool(self.cfg.start_sound or self.cfg.stop_sound) and not playing
                                      and not self.listening)
        self.listen_button.setText(BUSY if self.listening else "播放中…" if playing else "▶ 試聽")

    def _playing(self, seconds: float):
        self._sound_done.start(int(seconds * 1000) + 100)
        self._show_sounds()

    def _play_sounds(self):
        """The start sound, a pause, the end sound."""
        self._set_timer.stop()
        start, stop = self.cfg.start_sound, self.cfg.stop_sound
        cues.play(start, "start")
        total = cues.duration(start, "start") if start else 0
        if stop:
            wait = (total + _SET_PAUSE) if start else 0
            self._set_timer.setProperty("cue", stop)
            self._set_timer.start(int(wait * 1000))
            total = wait + cues.duration(stop, "stop")
        if total:
            self._playing(total)



