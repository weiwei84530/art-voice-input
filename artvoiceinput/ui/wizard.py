"""The setup wizard (2026-10-21, the user's design C: one card on the wall, its content changing): shown over the
settings window at the first launch and after 清空並重新設定, before the home page. Three steps: the microphone heard
(the level meter; 略過 turns into 下一步 once speech is loud enough, and what was said is decoded and shown), term
packs ticked (跳過 / 下一步), and a starting setup picked (簡單 / 標準 / 全自動, `PRESETS`). Light or dark with the
window. Closed before the end, it comes back at the next launch (`Config.setup_done`)."""
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QComboBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import audio, packs
from . import theme
from .kit import Slides, T, button, crossfade, draw_icon, logo_renderer, prop
from .page_mic import TEST_HEARD, LevelMeter

CARD_W, CARD_H = 600, 560
HEARD_TICKS = 3        # reads in a row over TEST_HEARD (50ms apart) that count as speech heard
SPEECH = 0.3           # a level this high is speech for 你剛剛說's cut
QUIET_AFTER = 0.7      # seconds under SPEECH that end what was said
KEEP = 12.0            # seconds of audio the probe keeps

# what each starting setup sets (the user's design, 2026-10-21); the 麥克風 page shows the same settings
PRESETS = {
    "simple": dict(auto_listen=False, show_bubble=False, show_float=True, float_text_only=False, float_keep=True,
                   auto_off_minutes=1, stop_on_enter=False, auto_off=False),
    "std": dict(auto_listen=False, show_bubble=True, show_float=True, float_text_only=True, float_keep=True,
                auto_off_minutes=5, stop_on_enter=True, auto_off=True),
    "auto": dict(auto_listen=True, show_bubble=False, show_float=False, auto_off_minutes=0, stop_on_enter=False,
                 auto_off=True),
}
OPTIONS = [
    ("simple", "簡單", "麥克風由你親手開關", "剛開始用語音輸入，或想每一步都自己決定",
     ["浮動按鈕一直顯示", "點輸入框不自動開", "1 分鐘沒講話就關"]),
    ("std", "標準", "點進輸入框，點一下小氣泡就講", "想方便，又想保留一點掌控",
     ["語音氣泡", "沒有輸入框時藏起浮動按鈕", "5 分鐘沒講話就關", "送出訊息後關", "離開輸入框後關"]),
    ("auto", "全自動", "點進輸入框就開始聽", "打字量大，想把雙手完全空出來",
     ["點進輸入框自動開麥克風", "不顯示浮動按鈕", "沒講話也不會關", "離開輸入框後關"]),
]


def _label(text: str, px: float, weight: int = 400, muted: bool = False, center: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setFont(theme.font(px, weight))
    if muted:
        lab.setProperty("muted", True)
    if center:
        lab.setAlignment(Qt.AlignCenter)
    return lab


def _tick(p: QPainter, r: QRectF, color: QColor, width: float):
    path = QPainterPath(QPointF(r.x() + r.width() * 0.28, r.y() + r.height() * 0.53))
    path.lineTo(r.x() + r.width() * 0.44, r.y() + r.height() * 0.69)
    path.lineTo(r.x() + r.width() * 0.73, r.y() + r.height() * 0.36)
    p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)


class Badge(QWidget):
    """The logo on an orange tile over its solid dark red shadow (the brand block's, from design H5)."""
    S = 84

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.S, self.S + 6)
        self._logo = logo_renderer()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#780A00"))
        p.drawRoundedRect(QRectF(0, 6, self.S, self.S), 22, 22)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(0, 0, self.S, self.S), 22, 22)
        self._logo.render(p, QRectF(15, 15, self.S - 30, self.S - 30))


class OkDot(QWidget):
    """A green circle with a white tick, before 聽到了 (the user's request)."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(16, 16)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(T("ins"))
        p.drawEllipse(QRectF(0.5, 0.5, 15, 15))
        _tick(p, QRectF(0, 0, 16, 16), QColor("#FFFFFF"), 1.8)


class TextLink(QAbstractButton):
    """Gray text, underlined under the pointer: 跳過教學."""

    def __init__(self, text: str):
        super().__init__()
        self.setText(text)
        self.setFont(theme.font(13))
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        fm = QFontMetrics(self.font())
        self.setFixedSize(fm.horizontalAdvance(text) + 8, 24)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        f = self.font()
        f.setUnderline(self.underMouse() or self.hasFocus())
        p.setFont(f)
        p.setPen(T("ink") if self.underMouse() else T("muted"))
        p.drawText(self.rect(), Qt.AlignCenter, self.text())


class BackButton(QAbstractButton):
    """‹ at the card's top left: the step before."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("上一步")
        self.setFocusPolicy(Qt.TabFocus)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.underMouse() or self.hasFocus():
            p.setPen(Qt.NoPen)
            p.setBrush(T("tile2"))
            p.drawEllipse(QRectF(self.rect()))
        draw_icon(p, "back", QRectF(8, 8, 16, 16), T("ink") if self.underMouse() else T("muted"), 2.2)


class PackTile(QAbstractButton):
    """A term pack to tick: its name, the first terms that fit, how many terms."""
    W, H = 168, 78

    def __init__(self, pack):
        super().__init__()
        self.pack = pack
        self.setCheckable(True)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName(pack.name)
        fm = QFontMetrics(theme.font(12))
        shown = []
        for w in pack.words:   # whole terms only: none cut off (the mockup's were)
            if fm.horizontalAdvance("、".join(shown + [w])) > self.W - 26:
                break
            shown.append(w)
        self.sample = "、".join(shown)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        p.setPen(QPen(T("acc") if on else T("acc", 0.5) if self.underMouse() else T("line"), 1.5))
        p.setBrush(T("acc", 0.07) if on else T("tile2"))
        p.drawRoundedRect(r, 8, 8)
        if self.hasFocus():
            p.setPen(QPen(T("ink"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 0.5), 8, 8)
        # the tick circle, top right
        c = QRectF(self.W - 28, 12, 16, 16)
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(T("acc"))
            p.drawEllipse(c)
            _tick(p, c, QColor("#FFFFFF"), 1.8)
        else:
            p.setPen(QPen(T("muted", 0.7), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c.adjusted(0.75, 0.75, -0.75, -0.75))
        p.setPen(T("ink"))
        p.setFont(theme.font(14.5, 700))
        p.drawText(QRectF(12, 9, self.W - 44, 22), Qt.AlignLeft | Qt.AlignVCenter, self.pack.name)
        p.setPen(T("muted"))
        p.setFont(theme.font(12))
        p.drawText(QRectF(12, 32, self.W - 20, 18), Qt.AlignLeft | Qt.AlignVCenter, self.sample)
        p.setFont(theme.font(13, 600, num=True))
        p.drawText(QRectF(12, 51, self.W - 20, 18), Qt.AlignLeft | Qt.AlignVCenter, f"{len(self.pack.words)} 個詞")


class Illus:
    """The options' small pictures, drawn on a 120x76 grid: the floating button with the pointer on it, a text box
    with the bubble beside it clicked, a glowing text box hearing speech."""

    @staticmethod
    def paint(p: QPainter, key: str, r: QRectF):
        p.save()
        p.translate(r.x(), r.y())
        p.scale(r.width() / 120, r.height() / 76)
        p.setRenderHint(QPainter.Antialiasing)
        acc, ink, tile = QColor(theme.ACCENT), T("ink"), T("tile")
        white = QColor("#FFFFFF")

        def mic(cx, cy, s):
            p.setPen(Qt.NoPen)
            p.setBrush(white)
            p.drawRoundedRect(QRectF(cx - 2.6 * s, cy - 6 * s, 5.2 * s, 8.5 * s), 2.6 * s, 2.6 * s)
            p.setPen(QPen(white, 1.3 * s, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(cx - 4.6 * s, cy - 4.6 * s, 9.2 * s, 9.2 * s), 200 * 16, 140 * 16)
            p.drawLine(QPointF(cx, cy + 4.6 * s), QPointF(cx, cy + 6.6 * s))

        def pointer(x, y, s):
            path = QPainterPath(QPointF(x, y))
            for dx, dy in ((0, 17), (4.5, 12.8), (7.7, 19.8), (10.9, 18.3), (7.7, 11.5), (13.9, 11.5)):
                path.lineTo(x + dx * s, y + dy * s)
            path.closeSubpath()
            p.setPen(QPen(tile, 1.2))
            p.setBrush(ink)
            p.drawPath(path)

        if key == "simple":
            p.setPen(Qt.NoPen)
            p.setBrush(acc)
            p.drawEllipse(QPointF(60, 36), 20, 20)
            mic(60, 35, 1.9)
            pointer(73, 47, 1.0)
        elif key == "std":
            p.setPen(QPen(T("line"), 1.5))
            p.setBrush(tile)
            p.drawRoundedRect(QRectF(6, 24, 84, 28), 5, 5)
            p.setPen(QPen(ink, 1.6))
            p.drawLine(QPointF(15, 31), QPointF(15, 45))
            p.setPen(Qt.NoPen)
            p.setBrush(acc)
            p.drawEllipse(QPointF(102, 38), 11, 11)
            mic(102, 37.5, 1.05)
            pointer(106, 45, 0.82)
        else:
            glow = QColor(acc)
            glow.setAlphaF(0.28)
            p.setPen(QPen(glow, 4))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(10, 18, 100, 40), 9, 9)
            p.setPen(QPen(acc, 1.8))
            p.setBrush(tile)
            p.drawRoundedRect(QRectF(14, 22, 92, 32), 5, 5)
            p.setPen(QPen(acc, 2.6, Qt.SolidLine, Qt.RoundCap))
            for x, h in ((30, 10), (36, 18), (42, 8), (48, 14), (54, 4)):
                p.drawLine(QPointF(x, 38 - h / 2), QPointF(x, 38 + h / 2))
            p.setPen(QPen(ink, 1.6))
            p.drawLine(QPointF(62, 31), QPointF(62, 45))
        p.restore()


class Option(QAbstractButton):
    """A starting setup: picture, name and what it is for; picked, what it sets as chips under them."""
    PIC = QRectF(9, 9, 84, 56)
    TEXT_X = 107

    def __init__(self, key, name, lead, who, sets):
        super().__init__()
        self.key, self.name, self.lead, self.who, self.sets = key, name, lead, who, sets
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName(f"{name}：{lead}")
        self.toggled.connect(lambda _: self.updateGeometry())

    def _chips(self, width: float) -> list[QRectF]:
        """Where each chip goes, wrapped within the text column."""
        fm = QFontMetrics(theme.font(11.5))
        x, y, out = 0.0, 0.0, []
        for s in self.sets:
            w = fm.horizontalAdvance(s) + 16
            if x and x + w > width:
                x, y = 0.0, y + 24
            out.append(QRectF(x, y, w, 20))
            x += w + 5
        return out

    def sizeHint(self):
        h = 74
        if self.isChecked():
            chips = self._chips(max(self.width(), 520) - self.TEXT_X - 14)
            h = 70 + int(chips[-1].bottom()) + 12
        return QSize(520, h)

    def resizeEvent(self, e):
        self.updateGeometry()

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        p.setPen(QPen(T("acc") if on else T("acc", 0.5) if self.underMouse() else T("line"), 1.5))
        p.setBrush(T("acc", 0.05) if on else T("tile"))
        p.drawRoundedRect(r, 8, 8)
        if self.hasFocus():
            p.setPen(QPen(T("ink"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 0.5), 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(T("bg"))
        p.drawRoundedRect(self.PIC, 6, 6)
        Illus.paint(p, self.key, self.PIC.adjusted(2, 2.5, -2, -2.5))
        x = self.TEXT_X
        p.setPen(T("ink"))
        f = theme.font(16, 700)
        p.setFont(f)
        p.drawText(QRectF(x, 12, 200, 24), Qt.AlignLeft | Qt.AlignVCenter, self.name)
        nx = x + QFontMetrics(f).horizontalAdvance(self.name) + 10
        p.setFont(theme.font(13, 500))
        p.drawText(QRectF(nx, 13, self.width() - nx - 12, 24), Qt.AlignLeft | Qt.AlignVCenter, self.lead)
        p.setPen(T("muted"))
        p.setFont(theme.font(12))
        p.drawText(QRectF(x, 38, self.width() - x - 12, 20), Qt.AlignLeft | Qt.AlignVCenter, self.who)
        if on:
            p.setFont(theme.font(11.5))
            for s, c in zip(self.sets, self._chips(self.width() - x - 14)):
                c.translate(x, 66)
                p.setPen(Qt.NoPen)
                p.setBrush(T("accbg"))
                p.drawRoundedRect(c, 10, 10)
                p.setPen(T("acct"))
                p.drawText(c, Qt.AlignCenter, s)


class MicStep(QWidget):
    """1: the name, the microphone, its meter; 略過 until speech is heard, then 下一步."""
    heard_audio = Signal(object)   # what was said (16 kHz float32), to be decoded for 你剛剛說
    done = Signal()

    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(60, 52, 60, 30)
        v.setSpacing(0)
        v.addWidget(Badge(), 0, Qt.AlignHCenter)
        v.addSpacing(20)
        v.addWidget(_label("阿特語音輸入法", 34, 700, center=True))
        v.addSpacing(4)
        v.addWidget(_label("已經裝好了。先說句話，確認麥克風聽得到你。", 14, muted=True, center=True))
        v.addSpacing(28)
        self.mic = QComboBox()
        self.mic.setCursor(Qt.PointingHandCursor)
        self.mic.setAccessibleName("使用的麥克風")
        self.mic.currentIndexChanged.connect(self._mic)
        v.addWidget(self.mic)
        v.addSpacing(12)
        self.meter = LevelMeter()
        v.addWidget(self.meter)
        v.addSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.ok = OkDot()
        self.status = _label("", 13.5, 500, center=True)
        row.addStretch(1)
        row.addWidget(self.ok)
        row.addWidget(self.status)
        row.addStretch(1)
        v.addLayout(row)
        v.addSpacing(8)
        self.said = _label("", 14, center=True)
        self.said.setWordWrap(True)
        v.addWidget(self.said)
        v.addStretch(1)
        self.next = button("略過", self.done.emit)
        self.next.setFixedSize(160, 40)
        v.addWidget(self.next, 0, Qt.AlignHCenter)

        self.probe = audio.LevelProbe(keep=KEEP)
        self._timer = QTimer(self, interval=50, timeout=self._tick)
        self.reset()

    def reset(self):
        self._heard = False
        self._run = 0
        self._speech_at = None   # when the speech being said began (monotonic)
        self._loud_at = 0.0
        self._waiting = False    # what was said is being decoded
        self.mic.blockSignals(True)
        self.mic.clear()
        self.mic.addItem("系統預設", "")
        for name in audio.list_input_devices():
            self.mic.addItem(name, name)
        i = self.mic.findData(self.win.cfg.mic)
        self.mic.setCurrentIndex(max(i, 0))
        self.mic.blockSignals(False)
        self.said.clear()
        self.said.hide()
        self._show()

    def _show(self, error: str = ""):
        self.ok.setVisible(self._heard and not error)
        if error:
            self.status.setText(error)
            prop(self.status, muted=False, ok=False, warn=True)
        elif self._heard:
            self.status.setText("聽到了，音量足夠")
            prop(self.status, muted=False, ok=True, warn=False)
        else:
            self.status.setText("試著說「今天天氣很好」")
            prop(self.status, muted=True, ok=False, warn=False)
        self.next.setText("下一步" if self._heard else "略過")
        prop(self.next, pri=self._heard)

    def start(self):
        try:
            self.probe.start(self.win.cfg.mic)
        except Exception:
            self.probe.stop()
            self.meter.reset()
            self._show("這支麥克風打不開，換一支試試，或先略過")
            return
        self._show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.probe.stop()
        self.meter.reset()

    def _mic(self):
        self.win.cfg.mic = self.mic.currentData() or ""
        self.win.save()
        self._heard, self._run, self._speech_at = False, 0, None
        self.said.hide()
        self.stop()
        self.start()

    def _tick(self):
        level = self.probe.read()
        self.meter.set(level)
        now = time.monotonic()
        if not self._heard:
            self._run = self._run + 1 if level > TEST_HEARD else 0
            if self._run >= HEARD_TICKS:
                self._heard = True
                self._show()
        if level > SPEECH:
            if self._speech_at is None:
                self._speech_at = now
            self._loud_at = now
        elif self._speech_at is not None and now - self._loud_at > QUIET_AFTER:
            spoken = self._loud_at - self._speech_at
            start = self._speech_at
            self._speech_at = None
            if spoken >= 0.3 and not self._waiting:
                self._waiting = True
                self.heard_audio.emit(self.probe.recent(min(now - start + 0.4, KEEP)))

    def show_said(self, text):
        """The decode of what was said: None while the model isn't ready yet."""
        self._waiting = False
        if text is None:
            self.said.setText("辨識模型還在準備，好了之後這裡會顯示你說的話")
            prop(self.said, muted=True)
        elif text:
            self.said.setText(f"你剛剛說：「{text}」")
            prop(self.said, muted=False)
        else:
            return
        self.said.show()


class PackStep(QWidget):
    """2: term packs to tick; 跳過 with none ticked, 下一步 with some."""
    done = Signal()

    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(40, 44, 40, 30)
        v.setSpacing(0)
        v.addWidget(_label("你平常會講到哪些領域的詞？", 24, 700))
        v.addSpacing(6)
        v.addWidget(_label("勾選的詞包裡，產品名和英文術語會更容易被聽對。", 13.5, muted=True))
        v.addSpacing(20)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.tiles = []
        for i, pack in enumerate(packs.available()):
            t = PackTile(pack)
            t.toggled.connect(self._show)
            grid.addWidget(t, i // 3, i % 3)
            self.tiles.append(t)
        v.addLayout(grid)
        v.addSpacing(14)
        v.addWidget(_label("之後在「詞庫」可以隨時加減，也能自己加詞。", 12.5, muted=True))
        v.addStretch(1)
        self.next = button("跳過", self.done.emit)
        self.next.setFixedSize(160, 40)
        v.addWidget(self.next, 0, Qt.AlignHCenter)
        BackButton(self).move(16, 18)

    def reset(self):
        for t in self.tiles:
            t.setChecked(t.pack.id in self.win.cfg.packs)
        self._show()

    def picked(self) -> list[str]:
        return [t.pack.id for t in self.tiles if t.isChecked()]

    def _show(self):
        on = bool(self.picked())
        self.next.setText("下一步" if on else "跳過")
        prop(self.next, pri=on)


class StyleStep(QWidget):
    """3: the starting setup; 開始教學 (not made yet: does nothing) or 跳過教學 to the home page."""
    done = Signal()

    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(40, 44, 40, 20)
        v.setSpacing(0)
        v.addWidget(_label("你想怎麼開關麥克風？", 24, 700))
        v.addSpacing(6)
        v.addWidget(_label("選一個起點，之後都能在「麥克風」頁改。", 13.5, muted=True))
        v.addSpacing(16)
        self.options = {}
        for key, *rest in OPTIONS:
            o = Option(key, *rest)
            o.clicked.connect(lambda _=False, k=key: self.pick(k))
            v.addWidget(o)
            v.addSpacing(8)
            self.options[key] = o
        v.addStretch(1)
        tutorial = button("開始教學", None, pri=True)   # the tutorial comes later (the user's decision, 2026-10-21)
        tutorial.setFixedHeight(44)
        v.addWidget(tutorial)
        v.addSpacing(8)
        skip = TextLink("跳過教學，直接開始使用")
        skip.clicked.connect(self.done.emit)
        v.addWidget(skip, 0, Qt.AlignHCenter)
        BackButton(self).move(16, 18)

    def reset(self):
        self.pick("std")

    def pick(self, key: str):
        self.choice = key
        for k, o in self.options.items():
            o.setChecked(k == key)


class Card(QWidget):
    """The white (dark gray) card with the steps' progress along its top edge."""

    def __init__(self, parent):
        super().__init__(parent)
        self.step = 0
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(T("tile"))
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        p.setClipPath(_rounded(QRectF(self.rect()), 12))
        w = (self.width() - 6) / 3
        for i in range(3):
            p.setBrush(T("acc") if i <= self.step else T("line"))
            p.drawRect(QRectF(i * (w + 3), 0, w, 5))


def _rounded(r: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    return path


class Wizard(QWidget):
    """Over the whole settings window: the wall, the faint logo, the card with the three steps sliding."""
    finished = Signal()

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setGeometry(win.rect())
        self._logos = {}           # color -> the faint logo on the wall
        self.card = Card(self)
        self.card.setGeometry((self.width() - CARD_W) // 2, (self.height() - CARD_H) // 2, CARD_W, CARD_H)
        self.mic_step, self.pack_step, self.style_step = MicStep(win), PackStep(win), StyleStep(win)
        self.slides = Slides(self.mic_step, self.pack_step, self.style_step)
        self.slides.setParent(self.card)
        self.slides.setGeometry(0, 5, CARD_W, CARD_H - 5)
        self.mic_step.done.connect(lambda: self.go(1))
        self.pack_step.done.connect(lambda: self.go(2))
        for step in (self.pack_step, self.style_step):
            back = step.findChild(BackButton)
            back.clicked.connect(lambda _=False, s=step: self.go(self.slides.index - 1))
        self.style_step.done.connect(self._finish)

    def begin(self):
        """From the first step, with the current settings."""
        self.mic_step.reset()
        self.pack_step.reset()
        self.style_step.reset()
        self.slides.go(0)
        self.slides._set_pos(0.0)
        self.card.step = 0
        self.card.update()

    def go(self, index: int):
        index = max(0, min(index, 2))
        if index == 0:
            self.mic_step.start()
        else:
            self.mic_step.stop()
        self.card.step = index
        self.card.update()
        self.slides.go(index)

    def showEvent(self, e):
        super().showEvent(e)
        if self.slides.index == 0:
            self.mic_step.start()

    def hideEvent(self, e):
        """Hidden or the window closed: the microphone isn't kept open unseen."""
        self.mic_step.stop()
        super().hideEvent(e)

    def _finish(self):
        cfg = self.win.cfg
        for k, v in PRESETS[self.style_step.choice].items():
            setattr(cfg, k, v)
        cfg.packs = self.pack_step.picked()
        cfg.setup_done = True
        crossfade(self.win, 320)
        self.hide()
        self.finished.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), T("wall2"))
        p.setOpacity(0.35 if not T("wall2").lightnessF() < 0.3 else 0.6)
        color = T("wall1").name()
        if color not in self._logos:
            self._logos[color] = logo_renderer(color)
        self._logos[color].render(p, QRectF(-230, -150, 700, 700))
        p.setOpacity(1.0)
        # the card's soft shadow
        p.setPen(Qt.NoPen)
        g = self.card.geometry()
        for i, a in enumerate((0.035, 0.03, 0.025, 0.02, 0.015)):
            d = 4 + i * 4
            p.setBrush(QColor(0, 0, 0, round(255 * a * (2.2 if T("wall2").lightnessF() < 0.3 else 1))))
            p.drawRoundedRect(QRectF(g).adjusted(-d / 2, d / 2, d / 2, d * 1.2), 12 + d / 2, 12 + d / 2)
