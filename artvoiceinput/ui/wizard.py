"""The setup wizard (2026-10-21, the user's design C: one card on the wall, its content changing): shown over the
settings window at the first launch and after 清空並重新設定, before the home page. Three steps: the microphone heard
(the level meter; 略過 turns into 下一步 once what was said is decoded and shown as 你剛剛說), term
packs ticked (跳過 / 下一步), and a starting setup picked (標準 / 簡單 / 自動 / 簡約, `PRESETS`). Light or dark with the
window. Closed before the end, it comes back at the next launch (`Config.setup_done`)."""
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QComboBox, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import appicon, audio, packs
from . import theme
from .kit import Slides, T, button, crossfade, draw_icon, logo_renderer, prop
from .page_mic import TEST_HEARD, LevelMeter

CARD_W, CARD_H = 600, 560
BUTTON_W, START_W = 168, 240   # 略過 / 跳過 / 下一步 and 開始教學, 40 high (2026-10-22, the user's request)
SPEECH = 0.3           # a level this high is speech for 你剛剛說's cut
QUIET_AFTER = 0.7      # seconds under SPEECH that end what was said
MAX_SAY = 8.0          # speech longer than this is decoded anyway
KEEP = 12.0            # seconds of audio the probe keeps

# what each starting setup sets (the user's design, 2026-10-21; 簡約 and the names 2026-10-22); the 麥克風 page
# shows the same settings
PRESETS = {
    "std": dict(auto_listen=False, show_bubble=True, float_away=False, float_box=False, float_rec=True,
                auto_off_minutes=5, stop_on_enter=True, auto_off=True),
    "simple": dict(auto_listen=False, show_bubble=False, float_away=True, float_box=True, float_rec=True,
                   auto_off_minutes=1, stop_on_enter=False, auto_off=False),
    "auto": dict(auto_listen=True, show_bubble=False, float_away=False, float_box=False, float_rec=False,
                 auto_off_minutes=0, stop_on_enter=False, auto_off=True),
    # nothing on screen, no glow: 右 Alt or the tray icon, shown on the taskbar, turns the microphone on and off;
    # 送出 doesn't turn it off (stop_on_enter)
    "minimal": dict(auto_listen=False, show_bubble=False, float_away=False, float_box=False, float_rec=False,
                    auto_off_minutes=5, stop_on_enter=False, auto_off=False, hotkey="vk:a5", tray_pinned=True,
                    tray_click="mic", glow=""),
}
OPTIONS = [
    ("std", "標準", "點進輸入框，點一下小氣泡就講", "想方便，又想保留一點掌控"),
    ("simple", "簡單", "麥克風由你親手開關", "剛開始用語音輸入，或想每一步都自己決定"),
    ("auto", "自動", "點進輸入框就開始聽", "打字量大，想把雙手完全空出來"),
    ("minimal", "簡約", "按右 Alt 或點工作列圖示開關", "畫面上不想多出任何按鈕"),
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


class KeyFocus:
    """A focus ring only when the focus came by the keyboard: a step's button hidden handed the focus on as if Tab
    was pressed, and the next step's first tile showed its ring (the user's report, 2026-10-21)."""
    ring = False

    def focusInEvent(self, e):
        self.ring = e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.ring = False
        super().focusOutEvent(e)


class Badge(QWidget):
    """The app icon (`appicon`) over a soft dark red shadow."""
    S = 84

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.S + 24, self.S + 24)
        shadow = QGraphicsDropShadowEffect(self, blurRadius=22, offset=QPointF(0, 6))
        shadow.setColor(QColor(120, 10, 0, 70))
        self.setGraphicsEffect(shadow)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(12, 8)
        appicon.paint(p, self.S)


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


class TextLink(KeyFocus, QAbstractButton):
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
        f.setUnderline(self.underMouse() or self.ring)
        p.setFont(f)
        p.setPen(T("ink") if self.underMouse() else T("muted"))
        p.drawText(self.rect(), Qt.AlignCenter, self.text())


class BackButton(KeyFocus, QAbstractButton):
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
        if self.underMouse() or self.ring:
            p.setPen(Qt.NoPen)
            p.setBrush(T("tile2"))
            p.drawEllipse(QRectF(self.rect()))
        draw_icon(p, "back", QRectF(8, 8, 16, 16), T("ink") if self.underMouse() else T("muted"), 2.2)


class PackTile(KeyFocus, QAbstractButton):
    """A term pack to tick: its name and as many of its first terms as two lines hold (no count: the user's
    request, 2026-10-21)."""
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
        lines = [[], []]
        words = list(pack.words)
        for line in lines:   # whole terms only: none cut off (the mockup's were)
            while words and (not line or fm.horizontalAdvance("、".join(line + [words[0]]) + "、") <= self.W - 24):
                line.append(words.pop(0))
        self.sample = ["、".join(lines[0]) + ("、" if lines[1] else ""), "、".join(lines[1])]

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
        if self.ring:
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
        for i, line in enumerate(self.sample):
            p.drawText(QRectF(12, 32 + i * 18, self.W - 20, 18), Qt.AlignLeft | Qt.AlignVCenter, line)


class Illus:
    """The options' small pictures, drawn on a 120x76 grid: the floating button with the pointer on it, a text box
    with the bubble beside it clicked, a glowing text box hearing speech, the Alt key beside the tray icon."""

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
            # the bubble over the text box's end, as large as 工具's tray icon (2026-10-22, the user's request)
            p.setPen(QPen(T("line"), 1.5))
            p.setBrush(tile)
            p.drawRoundedRect(QRectF(8, 24, 82, 28), 5, 5)
            p.setPen(QPen(ink, 1.6))
            p.drawLine(QPointF(17, 31), QPointF(17, 45))
            p.setPen(QPen(tile, 2))
            p.setBrush(acc)
            p.drawEllipse(QPointF(88, 38), 14, 14)
            mic(88, 37.5, 1.35)
            pointer(95, 47, 0.9)
        elif key == "minimal":
            p.setPen(QPen(T("line"), 1.5))
            p.setBrush(tile)
            p.drawRoundedRect(QRectF(14, 22, 46, 32), 5, 5)
            p.setPen(ink)
            p.setFont(theme.font(13, 700))
            p.drawText(QRectF(14, 22, 46, 30), Qt.AlignCenter, "Alt")
            p.save()
            p.translate(78, 23)
            appicon.paint(p, 28)
            p.restore()
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


class Option(KeyFocus, QAbstractButton):
    """A starting setup: picture, name and what it is for."""
    H = 80            # 70 read flat (2026-10-22, the user's request)
    PIC = QRectF(9, 8, 100, 64)
    TEXT_X = 124

    def __init__(self, key, name, lead, who):
        super().__init__()
        self.key, self.name, self.lead, self.who = key, name, lead, who
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName(f"{name}：{lead}")
        self.setFixedHeight(self.H)

    def sizeHint(self):
        return QSize(520, self.H)

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
        if self.ring:
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
        p.drawText(QRectF(x, 15, 200, 24), Qt.AlignLeft | Qt.AlignVCenter, self.name)
        nx = x + QFontMetrics(f).horizontalAdvance(self.name) + 10
        p.setFont(theme.font(13, 500))
        p.drawText(QRectF(nx, 16, self.width() - nx - 12, 24), Qt.AlignLeft | Qt.AlignVCenter, self.lead)
        p.setPen(T("muted"))
        p.setFont(theme.font(12))
        p.drawText(QRectF(x, 42, self.width() - x - 12, 20), Qt.AlignLeft | Qt.AlignVCenter, self.who)


class MicStep(QWidget):
    """1: the name, the microphone, its meter; 略過 until what was said is decoded (你剛剛說), then 下一步."""
    heard_audio = Signal(object)   # what was said (16 kHz float32), to be decoded for 你剛剛說
    done = Signal()

    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(60, 52, 60, 30)
        v.setSpacing(0)
        v.addWidget(Badge(), 0, Qt.AlignHCenter)   # 8px of its shadow's room under the icon
        v.addSpacing(6)
        # smaller and closer to the icon than at first, spaced like the brand block's name (2026-10-21, the user's
        # request: 34px stood apart from the icon)
        name = _label("阿特語音輸入法", 26, 700, center=True)
        f = name.font()
        f.setLetterSpacing(f.SpacingType.PercentageSpacing, 104)
        name.setFont(f)
        v.addWidget(name)
        v.addSpacing(6)
        v.addWidget(_label("先說句話，確認麥克風聽得到你。", 14, muted=True, center=True))
        v.addSpacing(30)
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
        self.next = button("略過", self.done.emit, wiz=True)   # 40 high by the style sheet (setFixedHeight lost to it)
        self.next.setFixedWidth(BUTTON_W)
        v.addWidget(self.next, 0, Qt.AlignHCenter)

        self.probe = audio.LevelProbe(keep=KEEP)
        self._timer = QTimer(self, interval=50, timeout=self._tick)
        self.reset()

    def reset(self):
        self._heard = False      # 你剛剛說 came back: 聽到了 and 下一步
        self._speech_at = None   # when the speech being said began (monotonic)
        self._loud_at = 0.0
        self._loud = False       # this speech went over TEST_HEARD
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
        """The status line (the user's design, 2026-10-21): 試著說… → 正在聽… while speech comes in and is decoded →
        聽到了 with the green dot once 你剛剛說 shows."""
        self.ok.setVisible(self._heard and not error)
        if error:
            self.status.setText(error)
            prop(self.status, muted=False, ok=False, warn=True)
        elif self._heard:
            self.status.setText("聽到了，音量足夠")
            prop(self.status, muted=False, ok=True, warn=False)
        elif self._speech_at is not None or self._waiting:
            self.status.setText("正在聽…")
            prop(self.status, muted=True, ok=False, warn=False)
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
        self._speech_at = None

    def _mic(self):
        self.win.cfg.mic = self.mic.currentData() or ""
        self.win.save()
        self._heard, self._speech_at, self._waiting = False, None, False
        self.said.hide()
        self.stop()
        self.start()

    def _tick(self):
        level = self.probe.read()
        self.meter.set(level)
        now = time.monotonic()
        if level > SPEECH:
            if self._speech_at is None:
                self._speech_at = now
                self._loud = False
                self._show()
            self._loud_at = now
            self._loud = self._loud or level > TEST_HEARD
            if now - self._speech_at < MAX_SAY:
                return
        elif self._speech_at is None or now - self._loud_at <= QUIET_AFTER:
            return
        # the speech ended (or went on past MAX_SAY: a noisy room never goes quiet)
        start, self._speech_at = self._speech_at, None
        if self._loud_at - start >= 0.3 and not self._waiting:
            self._waiting = True
            self.heard_audio.emit(self.probe.recent(min(now - start + 0.4, KEEP)))
        self._show()

    def show_said(self, text):
        """The decode of what was said: None while the model isn't ready yet (then the level alone counts)."""
        self._waiting = False
        if text is None:
            self._heard = self._heard or self._loud
            self.said.setText("辨識模型還在準備，好了之後這裡會顯示你說的話")
            prop(self.said, muted=True)
            self.said.show()
        elif text:
            self._heard = True
            self.said.setText(f"你剛剛說：「{text}」")
            prop(self.said, muted=False)
            self.said.show()
        self._show()


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
        self.next = button("跳過", self.done.emit, wiz=True)
        self.next.setFixedWidth(BUTTON_W)
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
        v.setContentsMargins(40, 40, 40, 16)
        v.setSpacing(0)
        v.addWidget(_label("你想怎麼開關麥克風？", 24, 700))
        v.addSpacing(6)
        v.addWidget(_label("選一個起點，之後都能在「麥克風」頁改。", 13.5, muted=True))
        v.addSpacing(14)
        self.options = {}
        for key, *rest in OPTIONS:
            o = Option(key, *rest)
            o.clicked.connect(lambda _=False, k=key: self.pick(k))
            v.addWidget(o)
            v.addSpacing(6)
            self.options[key] = o
        v.addStretch(1)
        tutorial = button("開始教學", None, pri=True, wiz=True)   # the tutorial comes later (the user's decision)
        tutorial.setFixedWidth(START_W)
        v.addWidget(tutorial, 0, Qt.AlignHCenter)
        v.addSpacing(6)
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
        self.setFocusPolicy(Qt.ClickFocus)
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
        self.setFocus(Qt.OtherFocusReason)   # not on the next step's first tile, as if Tab was pressed
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
