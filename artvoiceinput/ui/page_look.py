"""外觀與聲音: a preview (a window with the draft marked, the floating button, the glow along the edges), then the
button look and size, the edge glow (styles, motion, and under 自訂 its parameters, colors and edges), the draft's mark
color, 節流模式 and the sounds."""
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QColorDialog, QComboBox, QGridLayout, QSlider, QVBoxLayout, QWidget)

from .. import cues
from .. import glow as glowmod
from ..config import BUTTON_SCALE_RANGE
from ..floatbtn import _SIZE as _MIC_SIZE, OrbButton, _paint_mic
from ..highlight import COLORS as MARK_COLORS
from ..orbs import LOOKS, draw as draw_orb, palette
from . import theme
from .kit import Choice, Info, Switch, T, button, card, hbox, label, sep

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

    def _fit(self):
        side = round(self.base * BUTTON_SCALE_RANGE[1] / 100 * self.room)
        self.margin = (side - self.bsize) // 2
        self.setFixedSize(side, side)

    def _gone(self):
        pass

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
        self.setFixedHeight(160)
        self.colors = palette(None)
        self.glow_on = True
        self.mark = QColor(MARK_COLORS[0][0])
        self.orb = OrbSample(self)
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=40, timeout=self.update)

    def showEvent(self, e):
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()

    def resizeEvent(self, e):
        self.orb.move(self.width() - 70 - self.orb.width() // 2, (self.height() - self.orb.height()) // 2)

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
        w = QRectF(36, 28, min(420, r.width() - 200), 100)
        for i, a in enumerate((10, 6, 3)):
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(w.adjusted(-i, 4 + i, i, 8 + i), 7, 7)
        p.setBrush(T("tile"))
        p.setPen(QPen(T("line"), 1))
        p.drawRoundedRect(w, 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(T("tile2"))
        p.drawRoundedRect(QRectF(w.x() + 0.5, w.y() + 0.5, w.width() - 1, 18), 6, 6)
        p.setFont(theme.font(14.5))
        fm = p.fontMetrics()
        a, b = "明天下午三點開會，", "記得帶上週的報告"
        x, y = w.x() + 14, w.y() + 30
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
        shift = ((time.monotonic() - self._t0) / 4.0) % 1.0
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


class LookPage(QWidget):
    title = "外觀與聲音"

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.preview = Preview()
        v.addWidget(self.preview)
        self.preview.orb.keep = lambda: self.cfg.float_keep

        top = QGridLayout()
        top.setSpacing(12)
        top.setColumnStretch(0, 1)
        top.setColumnStretch(1, 1)
        # 按鈕樣式
        c_look, c = card()
        c.addLayout(hbox(label("按鈕樣式", h3=True), Info("浮動按鈕和語音氣泡的樣子：原本的麥克風，或跟光暈同色的能量球"
                                                       "（沒開光暈時用彩虹的顏色）。上面預覽裡的按鈕可以點一下看動畫"),
                         None, spacing=6))
        grid = QGridLayout()
        grid.setSpacing(4)
        self.looks = {}
        for i, (key, name) in enumerate(LOOKS.items()):
            t = LookTile(key, name)
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
        top.addWidget(c_look, 0, 0)
        # 螢幕邊緣光暈
        c_glow, c = card()
        self.preview_button = button("▶ 預覽", self._preview_glow)
        self._preview_done = QTimer(self, singleShot=True, interval=PREVIEW_MS, timeout=self._show_glow)
        c.addLayout(hbox(label("螢幕邊緣光暈", h3=True), Info("麥克風開著時，螢幕邊緣亮起一圈光，講話時會變亮。"
                                                         "選了、調了或按「預覽」會先亮一下讓你看"), None,
                         self.preview_button, spacing=6))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.glows = {}
        for i, (key, name) in enumerate([("", "關閉")] + [(s.id, s.name) for s in glowmod.STYLES]):
            t = GlowTile(key, name)
            t.clicked.connect(lambda _=False, k=key: self._glow(k))
            self.glows[key] = t
            grid.addWidget(t, i // 4, i % 4)
        c.addLayout(grid)
        self.motions = Choice(list(glowmod.MOTIONS.items()))
        self.motions.picked.connect(self._motion)
        c.addWidget(self.motions)
        # 自訂: the style's parameters, colors and edges (the old 外觀 tab's editor, folded)
        self.custom_toggle = button("", self._toggle_custom)
        self.custom_toggle.setStyleSheet("QPushButton { background: transparent; border: none; padding: 2px 0; "
                                         "text-align: left; }")
        self.reset_button = button("恢復預設", self._reset_glow, link=True)
        c.addLayout(hbox(self.custom_toggle, None, self.reset_button))
        self.custom = QWidget()
        cv = QVBoxLayout(self.custom)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)
        self.color_row = hbox(spacing=4)
        cv.addLayout(hbox(label("顏色", b14=True), self.color_row, None, spacing=10))
        self.sliders = {}
        for key, name, lo, hi in SLIDERS:
            s = QSlider(Qt.Horizontal, minimum=lo, maximum=hi)
            s.setCursor(Qt.PointingHandCursor)
            s.valueChanged.connect(lambda val, k=key, w=s: self._glow_edited(k, val / 100, save=not w.isSliderDown()))
            s.sliderReleased.connect(lambda: self._glow_edited(None, None))
            self.sliders[key] = s
            n = label(name)
            n.setFixedWidth(64)
            cv.addLayout(hbox(n, s, spacing=10))
        self.edges = Choice([(k, v[0]) for k, v in glowmod.EDGES.items()])
        self.edges.picked.connect(self._edges)
        cv.addLayout(hbox(label("亮哪幾邊", b14=True), None, spacing=10))
        cv.addWidget(self.edges)
        self.custom.hide()
        c.addWidget(self.custom)
        c.addStretch(1)
        top.addWidget(c_glow, 0, 1)
        v.addLayout(top)

        bottom = QGridLayout()
        bottom.setSpacing(12)
        bottom.setColumnStretch(0, 1)
        bottom.setColumnStretch(1, 2)
        # 草稿反白顏色 + 節流模式
        c_mark, c = card()
        c.addLayout(hbox(label("草稿反白顏色", h3=True), Info("麥克風開著時，講完還可能被修正的字會疊上這個顏色，定稿後消失"),
                         None, spacing=6))
        self.marks = {}
        row = hbox(spacing=6)
        for color, name in MARK_COLORS:
            s = Swatch(color)
            s.setToolTip(name)
            s.clicked.connect(lambda _=False, col=color: self._mark(col))
            self.marks[color.upper()] = s
            row.addWidget(s)
        self.mark_custom = Swatch("#00000000")
        self.mark_custom.setToolTip("自訂顏色")
        self.mark_custom.clicked.connect(self._pick_mark)
        row.addWidget(self.mark_custom)
        row.addStretch(1)
        c.addLayout(row)
        c.addWidget(sep())
        self.lite = Switch(name="節流模式")
        self.lite.toggled.connect(self._lite)
        c.addLayout(hbox(label("節流模式", b14=True), Info(
            "勾選後動畫改用較省 CPU 的畫法：能量球每秒 15 張、光暈較粗略；螢幕邊緣光暈的波浪、流星、漣漪每秒 24 張。不開時"
            "能量球每秒 30 張、細節完整；會移動的光暈每秒 48 張，比較順，但 CPU 用量約多七成"), None, self.lite, spacing=6))
        c.addStretch(1)
        bottom.addWidget(c_mark, 0, 0)
        # 提示音
        c_sound, c = card()
        self.listen_button = button("▶ 試聽", self._play_sounds)
        self._sound_done = QTimer(self, singleShot=True, timeout=self._show_sounds)
        self._set_timer = QTimer(self, singleShot=True, timeout=lambda: cues.play(self._set_timer.property("cue"), "stop"))
        c.addLayout(hbox(label("提示音", h3=True), Info("開始音在麥克風打開時、結束音在關掉時播放。同一組的開始音與結束音"
                                                     "一起選；選「自定義」可分別挑選"), None, self.listen_button, spacing=6))
        sets = [(cid, name) for cid, name, *_ in cues.SOUNDS] + [("", "無"), (None, "自定義")]
        self.sound_sets = Choice(sets)
        self.sound_sets.picked.connect(self._sound_set)
        c.addWidget(self.sound_sets)
        self.start_box, self.stop_box = QComboBox(), QComboBox()
        for box, kind in ((self.start_box, "start"), (self.stop_box, "stop")):
            for cid, name, *_ in cues.SOUNDS:
                box.addItem(name, cid)
            box.addItem("無", "")
            box.currentIndexChanged.connect(lambda _=0, b=box, k=kind: self._sound(b, k))
        self.custom_sounds = QWidget()
        self.custom_sounds.setLayout(hbox(label("開始"), self.start_box, 12, label("結束"), self.stop_box, None,
                                          spacing=6))
        c.addWidget(self.custom_sounds)
        c.addStretch(1)
        bottom.addWidget(c_sound, 0, 1)
        v.addLayout(bottom)
        v.addStretch(1)
        self._live = QTimer(self, singleShot=True, interval=80, timeout=self._preview_glow)
        self._custom_open = False

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
        self.lite.set_quiet(cfg.orb_lite)
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

    def _lite(self, on: bool):
        self.cfg.orb_lite = on
        self.win.save()
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
        self.preview_button.setEnabled(on and not playing)
        self.preview_button.setText("播放中…" if playing else "▶ 預覽")
        self.custom_toggle.setVisible(on)
        self.custom_toggle.setText(("▾ 收起自訂" if self._custom_open else "▸ 自訂顏色、速度與邊緣"))
        self.custom.setVisible(on and self._custom_open)
        self.reset_button.setVisible(on and glowmod.edited(cfg.glow, cfg.glow_edits))
        c = self._params()
        for key, s in self.sliders.items():
            s.blockSignals(True)
            s.setValue(round(float(c[key]) * 100))
            s.blockSignals(False)
        while self.color_row.count():
            w = self.color_row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for i, color in enumerate(c["colors"]):
            s = Swatch(color, "", 26)
            s.setToolTip("點一下換顏色")
            s.clicked.connect(lambda _=False, i=i: self._glow_color(i))
            self.color_row.addWidget(s)
        if len(c["colors"]) < glowmod.MAX_COLORS:
            self.color_row.addWidget(button("＋", lambda: self._glow_color(-1), ib=True))
        if len(c["colors"]) > 2:
            self.color_row.addWidget(button("－", self._glow_fewer, ib=True))
        self.preview.colors = _colors_of(cfg.glow, cfg.glow_edits)
        self.preview.glow_on = on
        self.preview.update()
        self._show_orb()

    def _toggle_custom(self):
        self._custom_open = not self._custom_open
        self._show_glow()

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
        if self.cfg.glow and not self.win._loading:
            self.win.glow_preview.emit(self.cfg.glow)
            self._preview_done.start()
            self.preview_button.setEnabled(False)
            self.preview_button.setText("播放中…")

    # --- the draft's mark ---
    def _show_mark(self):
        color = self.cfg.highlight_color.upper()
        preset = self.marks.get(color)
        for s in self.marks.values():
            s.setChecked(s is preset)
        self.mark_custom.setChecked(preset is None)
        self.mark_custom.color = "#00000000" if preset is not None else color
        self.mark_custom.text_ = "＋" if preset is not None else "字"
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
            self._play_sounds()
        self._show_sounds()

    def _sound(self, box, kind: str):
        setattr(self.cfg, f"{kind}_sound", box.currentData())
        self.win.save()
        if box.currentData():
            cues.play(box.currentData(), kind)
            self._playing(cues.duration(box.currentData(), kind))
        self._show_sounds()

    def _show_sounds(self):
        self.custom_sounds.setVisible(self.sound_sets.value() is None and self.sound_sets.buttons[None].isChecked())
        playing = self._sound_done.isActive()
        self.listen_button.setEnabled(bool(self.cfg.start_sound or self.cfg.stop_sound) and not playing)
        self.listen_button.setText("播放中…" if playing else "▶ 試聽")

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



