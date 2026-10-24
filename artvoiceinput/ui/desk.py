"""The tutorial's pretend Windows 11 desktop (2026-10-24, the user's design): the Bloom wallpaper (A1+ of
https://claude.ai/artifact/FXMWnBF7Ek4uLwQ3y3JAiM: the flower 1.35x, its centre a little above the taskbar, its two
rings of petals swaying slowly), a taskbar with 記事本 and a chat app, their windows, the bubble, the floating button
(麥克風（原始）) and the 錄音紅 glow, light or dark with the settings window. Everything is drawn and clicked inside the
settings window; nothing here reaches the real app."""
import math
import time

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from .. import appicon
from ..floatbtn import EDGE, OrbButton
from ..glow import FADE_MS
from ..picker import Picker
from . import theme
from .kit import T, calm

BAR = 44                    # the taskbar's height
MARK = QColor(255, 228, 92, 0x78)   # the draft's yellow (config.highlight_color's default)
SWAY_S = 14.0               # one sway of the petals, seconds
# the wallpaper's colors (the artifact's tokens)
WALL = {
    False: dict(bg=("#f7faff", "#e3eefb", "#cfe0f6"), halo="#bcd8fb", core="#5b95ee", core_op=0.35,
                back=("#1f56d6", "#4b8ff2", "#b6dbff"), front=("#173fae", "#3577ea", "#9fcdff"),
                back_op=0.62, front_op=0.7, fold=0.28, center="#e9f3ff",
                bar="#f6f9fd", bar_op=0.88, bar_line="#c9d6e6", ink="#2b3440", text="#1f2833", gear="#6b7685"),
    True: dict(bg=("#0d1a33", "#0a1630", "#050b1a"), halo="#2a63d8", core="#3b7bff", core_op=0.45,
               back=("#2350d8", "#5d9bff", "#cfe6ff"), front=("#1a3fb8", "#4a8cf7", "#b4dcff"),
               back_op=0.72, front_op=0.8, fold=0.2, center="#cfe3ff",
               bar="#1b2130", bar_op=0.9, bar_line="#323c50", ink="#e1e7ef", text="#e8edf3", gear="#aab4c2"),
}
# the pretend apps' windows (Windows 11's own light and dark)
APP = {
    False: dict(frame="#f3f3f3", body="#ffffff", line="#d9d9d9", ink="#1b1b1b", muted="#6b6b6b",
                sel=QColor(0, 120, 215, 70), chat="#f4f6f8", them="#ffffff", me="#FFDDD8"),
    True: dict(frame="#202020", body="#272727", line="#3a3a3a", ink="#f2f2f2", muted="#a8a8a8",
               sel=QColor(76, 160, 255, 90), chat="#1e2227", them="#2c3138", me="#5A2A26"),
}
RED = ("#ff453a", "#ff6b5e", "#ff2d20")   # 錄音紅 (glow.STYLES "red")
FLASH_S = 1.1               # a corrected span's red fading out
TRAY_STEP, TRAY_RIGHT = 30, 98   # the tray's items: their spacing, the last one's centre from the right edge


def _dark() -> bool:
    return T("bg").lightnessF() < 0.3


def _petal(big: bool, fold: bool) -> QPainterPath:
    """One petal from the flower's middle along +x (the artifact's paths)."""
    if big:
        pts = ((55, -78, 190, -108, 262, -26), (176, -62, 84, -46, 0, 0) if fold else (206, 18, 92, 30, 0, 0))
    else:
        pts = ((42, -62, 146, -82, 200, -18), (134, -46, 64, -34, 0, 0) if fold else (158, 14, 70, 22, 0, 0))
    path = QPainterPath(QPointF(0, 0))
    for a, b, c, d, e, f in pts:
        path.cubicTo(a, b, c, d, e, f)
    return path


class Wallpaper:
    """Bloom drawn once per size and theme into three pictures (the ground, each ring of petals); the rings are
    turned a little each frame."""
    S = 1.35

    def __init__(self):
        self._key = None
        self.ground = self.back = self.front = None

    def centre(self, w: int, h: int) -> QPointF:
        return QPointF(w / 2, h - BAR - 106)

    def _make(self, w: int, h: int, dpr: float, dark: bool):
        c = WALL[dark]
        cx, cy = w / 2, h - BAR - 106

        def canvas(cw, ch):
            pm = QPixmap(round(cw * dpr), round(ch * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            return pm, p

        self.ground, p = canvas(w, h)
        g = QLinearGradient(0, 0, w, h)
        for at, col in zip((0, 0.55, 1), c["bg"]):
            g.setColorAt(at, QColor(col))
        p.fillRect(QRectF(0, 0, w, h), g)
        p.save()
        p.translate(cx, cy - 40)
        p.scale(330 * self.S, 290 * self.S)
        halo = QRadialGradient(QPointF(0, 0), 1)
        col = QColor(c["halo"])
        col.setAlphaF(0.9)
        halo.setColorAt(0, col)
        col.setAlphaF(0)
        halo.setColorAt(1, col)
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(0, 0), 1, 1)
        p.restore()
        p.setPen(Qt.NoPen)
        # the blurred blue under the petals
        r = (150 + 56) * self.S
        core = QRadialGradient(QPointF(cx, cy), r)
        col = QColor(c["core"])
        col.setAlphaF(c["core_op"])
        core.setColorAt(0, col)
        core.setColorAt(150 / 206, col)
        col.setAlphaF(0)
        core.setColorAt(1, col)
        p.setBrush(core)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()

        side = round(2 * 270 * self.S)
        for name, big, start, colors, op in (("back", True, 8, c["back"], c["back_op"]),
                                             ("front", False, 30, c["front"], c["front_op"])):
            pm, p = canvas(side, side)
            p.translate(side / 2, side / 2)
            p.scale(self.S, self.S)
            p.setPen(Qt.NoPen)
            length = 262 if big else 200
            body, fold = _petal(big, False), _petal(big, True)
            for i in range(8):
                p.save()
                p.rotate(start + i * 45)
                g = QLinearGradient(0, 0, length, 0)
                for at, col in zip((0, 0.55, 1), colors):
                    g.setColorAt(at, QColor(col))
                p.setOpacity(op)
                p.setBrush(g)
                p.drawPath(body)
                p.setOpacity(c["fold"])
                p.setBrush(QColor("#ffffff"))
                p.drawPath(fold)
                p.restore()
            if not big:
                p.setOpacity(0.85)
                p.setBrush(QColor(c["center"]))
                p.drawEllipse(QPointF(0, 0), 16, 16)
            p.end()
            setattr(self, name, pm)

    def paint(self, p: QPainter, w: int, h: int, dpr: float, phase: float):
        dark = _dark()
        key = (w, h, dpr, dark)
        if key != self._key:
            self._make(w, h, dpr, dark)
            self._key = key
        p.drawPixmap(0, 0, self.ground)
        centre = self.centre(w, h)
        k = (1 - math.cos(phase * math.tau)) / 2   # 0 .. 1 .. 0 like the artifact's keyframes
        for pm, deg, grow in ((self.back, 4.0, 0.03), (self.front, -5.0, 0.05)):
            p.save()
            p.translate(centre)
            p.rotate(deg * k)
            s = 1 + grow * k
            p.scale(s, s)
            side = pm.width() / pm.devicePixelRatio()
            p.drawPixmap(QPointF(-side / 2, -side / 2), pm)
            p.restore()


class FakeText(QWidget):
    """A pretend text box: text, a caret, a selection made with the mouse, and the draft marked yellow. Lines wrap
    at the box's width."""
    pressed = Signal(QPoint)    # a click put the caret here (the desk's coordinates)
    selected = Signal()         # a drag or double click ended with a selection

    def __init__(self, parent, single_line: bool = False, placeholder: str = ""):
        super().__init__(parent)
        self.single_line, self.placeholder = single_line, placeholder
        self.text = ""
        self.caret = self.anchor = 0
        self.draft = None           # (start, end) marked yellow
        self.flash = None           # (start, end, since): a corrected span, red fading out
        self.focused = False
        self._blink = True
        self._drag = False
        self._timer = QTimer(self, interval=530, timeout=self._tick)
        self._flash_timer = QTimer(self, interval=33, timeout=self._flash_tick)
        self.setCursor(Qt.IBeamCursor)
        self.setFont(theme.font(15))

    # --- editing ---
    @property
    def selection(self) -> tuple[int, int]:
        return min(self.caret, self.anchor), max(self.caret, self.anchor)

    @property
    def selected_text(self) -> str:
        a, b = self.selection
        return self.text[a:b]

    def set_text(self, text: str, caret: int | None = None):
        self.text = text
        self.caret = self.anchor = len(text) if caret is None else caret
        self.draft = None
        self.update()

    def replace(self, a: int, b: int, s: str, draft: bool = False):
        """text[a:b] becomes s, the caret after it (marked as the draft with draft)."""
        self.text = self.text[:a] + s + self.text[b:]
        self.caret = self.anchor = a + len(s)
        self.draft = (a, a + len(s)) if draft and s else None
        self._blink = True
        self.update()

    def insert(self, s: str, draft: bool = False):
        a, b = self.selection
        self.replace(a, b, s, draft)

    def commit(self):
        self.draft = None
        self.update()

    def flash_span(self, a: int, b: int):
        """text[a:b] was just corrected: red behind it, fading out in FLASH_S (none with 節流模式)."""
        if calm():
            return
        self.flash = (a, b, time.monotonic())
        self._flash_timer.start()
        self.update()

    def _flash_tick(self):
        if self.flash is None or time.monotonic() - self.flash[2] > FLASH_S:
            self.flash = None
            self._flash_timer.stop()
        self.update()

    def set_focus(self, on: bool):
        self.focused = on
        self._blink = True
        if on:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def char_rect(self, a: int, b: int) -> QRect:
        """The rectangle of text[a:b] on its first line, in the desk's coordinates."""
        boxes = [r for i, r in self._layout() if a <= i < b]
        if not boxes:
            r = self._caret_rect(a)
            return QRect(self.mapTo(self.desk(), r.topLeft().toPoint()), QSize(2, round(r.height())))
        top = boxes[0].y()
        row = [r for r in boxes if r.y() == top]
        left, right = row[0].x(), row[-1].right()
        return QRect(self.mapTo(self.desk(), QPoint(round(left), round(top))),
                     QSize(round(right - left), round(row[0].height())))

    def used_rect(self) -> QRect:
        """The rows holding text (at least one), in the desk's coordinates: what the user reads."""
        bottom = self._caret_rect(len(self.text)).bottom()
        boxes = self._layout()
        if boxes:
            bottom = max(bottom, max(r.bottom() for _, r in boxes))
        top = round(self._pad()[1])
        return QRect(self.mapTo(self.desk(), QPoint(0, top)), QSize(self.width(), round(bottom) - top + 4))

    def desk(self) -> QWidget:
        return self.parentWidget().parentWidget()   # the app window's desk

    # --- layout ---
    def _pad(self) -> tuple[float, float]:
        return (12, (self.height() - self._line_h()) / 2) if self.single_line else (14, 10)

    def _line_h(self) -> float:
        return 26.0

    def _layout(self) -> list[tuple[int, QRectF]]:
        """Each character's box, wrapped at the width."""
        fm = QFontMetricsF(self.font())
        px, py = self._pad()
        lh = self._line_h()
        x, y = px, py
        out = []
        for i, ch in enumerate(self.text):
            if ch == "\n":
                out.append((i, QRectF(x, y, 0, lh)))
                x, y = px, y + lh
                continue
            w = fm.horizontalAdvance(ch)
            if x + w > self.width() - px and x > px and not self.single_line:
                x, y = px, y + lh
            out.append((i, QRectF(x, y, w, lh)))
            x += w
        return out

    def _caret_rect(self, i: int) -> QRectF:
        boxes = self._layout()
        px, py = self._pad()
        if i < len(boxes):
            r = boxes[i][1]
            return QRectF(r.x(), r.y(), 1.5, self._line_h())
        if not boxes:
            return QRectF(px, py, 1.5, self._line_h())
        last = boxes[-1][1]
        if self.text.endswith("\n"):
            return QRectF(px, last.y() + self._line_h(), 1.5, self._line_h())
        return QRectF(last.right(), last.y(), 1.5, self._line_h())

    def _index_at(self, pos: QPointF) -> int:
        best, best_d = len(self.text), None
        for i, r in self._layout() + [(len(self.text), self._caret_rect(len(self.text)))]:
            if not (r.y() <= pos.y() < r.y() + self._line_h()):
                continue
            edge = r.x() if pos.x() < r.center().x() or r.width() == 0 else r.right()
            d = abs(pos.x() - edge)
            if best_d is None or d < best_d:
                best, best_d = (i if edge == r.x() else i + 1), d
        if best_d is None:   # below the text: its end
            return len(self.text)
        return min(best, len(self.text))

    # --- mouse ---
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        i = self._index_at(e.position())
        self.caret = self.anchor = i
        self._drag = False
        self.update()
        self.pressed.emit(self.mapTo(self.desk(), e.position().toPoint()))

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            i = self._index_at(e.position())
            if i != self.caret:
                self.caret = i
                self._drag = True
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag and self.caret != self.anchor:
            self.selected.emit()

    def mouseDoubleClickEvent(self, e):
        i = min(self._index_at(e.position()), len(self.text) - 1)
        boxes = dict(self._layout())
        if 0 <= i < len(self.text) and i in boxes and boxes[i].x() > e.position().x():
            i -= 1   # the character left of the point
        if 0 <= i < len(self.text) and self.text[i] not in "\n":
            self.anchor, self.caret = i, i + 1
            self.update()
            self.selected.emit()

    def _tick(self):
        self._blink = not self._blink
        self.update()

    # --- painting ---
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = APP[_dark()]
        p.setFont(self.font())
        boxes = self._layout()
        a, b = self.selection
        flash = None
        if self.flash:
            k = 1 - (time.monotonic() - self.flash[2]) / FLASH_S
            flash = QColor(255, 69, 58, round(115 * max(0.0, k)))
        for i, r in boxes:
            if self.draft and self.draft[0] <= i < self.draft[1] and self.text[i] != "\n":
                p.fillRect(r.adjusted(0, 3, 0, -3), MARK)
            if flash and self.flash[0] <= i < self.flash[1] and self.text[i] != "\n":
                p.fillRect(r.adjusted(0, 3, 0, -3), flash)
            if a <= i < b and self.text[i] != "\n":
                p.fillRect(r.adjusted(0, 3, 0, -3), c["sel"])
        p.setPen(QColor(c["ink"]))
        for i, r in boxes:
            if self.text[i] != "\n":
                p.drawText(r, Qt.AlignCenter, self.text[i])
        if not self.text and self.placeholder:
            px, py = self._pad()
            p.setPen(QColor(c["muted"]))
            p.drawText(QRectF(px, py, self.width() - 2 * px, self._line_h()), Qt.AlignLeft | Qt.AlignVCenter,
                       self.placeholder)
        if self.focused and a == b and self._blink:
            p.fillRect(self._caret_rect(self.caret).adjusted(0, 4, 0, -4), QColor(c["ink"]))


class AppWindow(QWidget):
    """A pretend app's window: a soft shadow, its frame, a title bar with the app's icon and the three buttons."""
    TITLE = 34
    SHADOW = 14

    def __init__(self, parent, title: str, kind: str):
        super().__init__(parent)
        self.title, self.kind = title, kind

    def mousePressEvent(self, e):
        self.parentWidget().stray.emit()

    def inner(self) -> QRect:
        s = self.SHADOW
        return QRect(s, s + self.TITLE, self.width() - 2 * s, self.height() - 2 * s - self.TITLE)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = APP[_dark()]
        s = self.SHADOW
        frame = QRectF(self.rect()).adjusted(s, s, -s, -s)
        for i in range(s, 0, -2):
            a = (40 if _dark() else 18) * (1 - i / s) ** 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, round(a)))
            p.drawRoundedRect(frame.adjusted(-i / 2, -i / 2 + 3, i / 2, i / 2 + 5), 8 + i / 2, 8 + i / 2)
        p.setPen(QPen(QColor(c["line"]), 1))
        p.setBrush(QColor(c["frame"]))
        p.drawRoundedRect(frame.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        # the icon and title
        paint_app_icon(p, self.kind, QRectF(frame.x() + 12, frame.y() + 9, 16, 16))
        p.setPen(QColor(c["ink"]))
        p.setFont(theme.font(12))
        p.drawText(QRectF(frame.x() + 36, frame.y(), 300, self.TITLE), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        # minimise, maximise, close
        pen = QPen(QColor(c["ink"]), 1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        y = frame.y() + self.TITLE / 2
        right = frame.right()
        p.drawLine(QPointF(right - 125, y), QPointF(right - 115, y))
        p.drawRect(QRectF(right - 80, y - 5, 10, 10))
        p.drawLine(QPointF(right - 33, y - 5), QPointF(right - 23, y + 5))
        p.drawLine(QPointF(right - 33, y + 5), QPointF(right - 23, y - 5))


def paint_app_icon(p: QPainter, kind: str, r: QRectF):
    """記事本 (a page with lines) or the chat app (a speech balloon), Fluent-like, in r."""
    p.save()
    p.setPen(Qt.NoPen)
    if kind == "notepad":
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor("#5fb8ff"))
        g.setColorAt(1, QColor("#1f7ae0"))
        p.setBrush(g)
        p.drawRoundedRect(r.adjusted(r.width() * 0.12, 0, -r.width() * 0.12, 0), r.width() * 0.14, r.width() * 0.14)
        p.setPen(QPen(QColor(255, 255, 255, 230), max(1.0, r.width() * 0.08), Qt.SolidLine, Qt.RoundCap))
        for k in (0.34, 0.52, 0.7):
            p.drawLine(QPointF(r.x() + r.width() * 0.3, r.y() + r.height() * k),
                       QPointF(r.right() - r.width() * 0.3, r.y() + r.height() * k))
    elif kind == "chat":
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor("#4cd97b"))
        g.setColorAt(1, QColor("#16a34a"))
        p.setBrush(g)
        body = QRectF(r.x(), r.y() + r.height() * 0.08, r.width(), r.height() * 0.72)
        p.drawRoundedRect(body, r.width() * 0.3, r.width() * 0.3)
        tail = QPainterPath(QPointF(r.x() + r.width() * 0.22, body.bottom() - 2))
        tail.lineTo(r.x() + r.width() * 0.18, r.bottom())
        tail.lineTo(r.x() + r.width() * 0.48, body.bottom() - 2)
        p.drawPath(tail)
        p.setBrush(QColor(255, 255, 255, 235))
        for k in (0.3, 0.5, 0.7):
            p.drawEllipse(QPointF(r.x() + r.width() * k, body.center().y()), r.width() * 0.07, r.width() * 0.07)
    p.restore()


class Notepad(AppWindow):
    def __init__(self, parent):
        super().__init__(parent, "未命名 - 記事本", "notepad")
        self.edit = FakeText(self)

    def resizeEvent(self, e):
        r = self.inner()
        self.edit.setGeometry(r.x() + 1, r.y() + 30, r.width() - 2, r.height() - 30 - 26)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        c = APP[_dark()]
        r = self.inner()
        p.fillRect(QRect(r.x() + 1, r.y() + 30, r.width() - 2, r.height() - 30 - 26), QColor(c["body"]))
        p.setPen(QColor(c["ink"]))
        p.setFont(theme.font(12))
        for i, name in enumerate(("檔案", "編輯", "檢視")):
            p.drawText(QRectF(r.x() + 12 + i * 46, r.y(), 40, 30), Qt.AlignLeft | Qt.AlignVCenter, name)
        p.setPen(QColor(c["muted"]))
        p.setFont(theme.font(11))
        line = self.edit.text[:self.edit.caret].count("\n") + 1
        col = self.edit.caret - (self.edit.text.rfind("\n", 0, self.edit.caret) + 1) + 1
        status = f"第 {line} 行，第 {col} 欄      100%      Windows (CRLF)      UTF-8"
        p.drawText(QRectF(r.x() + 12, r.bottom() - 25, r.width() - 24, 24), Qt.AlignLeft | Qt.AlignVCenter, status)


class Chat(AppWindow):
    """A chat with 小美: messages, the input box, the send arrow."""

    def __init__(self, parent):
        super().__init__(parent, "聊天", "chat")
        self.messages: list[tuple[bool, str]] = [(False, "你到哪了？我已經在門口了")]
        self.edit = FakeText(self, single_line=True, placeholder="輸入訊息")

    def resizeEvent(self, e):
        r = self.inner()
        self.edit.setGeometry(r.x() + 12, r.bottom() - 52, r.width() - 64, 40)

    def say(self, mine: bool, text: str):
        self.messages.append((mine, text))
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = APP[_dark()]
        r = self.inner()
        p.fillRect(QRect(r.x() + 1, r.y(), r.width() - 2, r.height() - 1), QColor(c["chat"]))
        # who: an avatar and the name
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#f5a3b5"))
        p.drawEllipse(QRectF(r.x() + 14, r.y() + 10, 28, 28))
        p.setPen(QColor("#ffffff"))
        p.setFont(theme.font(13, 700))
        p.drawText(QRectF(r.x() + 14, r.y() + 10, 28, 28), Qt.AlignCenter, "美")
        p.setPen(QColor(c["ink"]))
        p.setFont(theme.font(14, 700))
        p.drawText(QRectF(r.x() + 50, r.y() + 10, 200, 28), Qt.AlignLeft | Qt.AlignVCenter, "小美")
        p.fillRect(QRect(r.x() + 1, r.y() + 48, r.width() - 2, 1), QColor(c["line"]))
        # messages, newest at the bottom
        p.setFont(theme.font(13.5))
        fm = p.fontMetrics()
        y = r.bottom() - 66
        for mine, text in reversed(self.messages):
            w = min(fm.horizontalAdvance(text) + 24, r.width() - 70)
            box = fm.boundingRect(QRect(0, 0, w - 24, 400), Qt.TextWordWrap, text)
            h = box.height() + 16
            y -= h
            if y < r.y() + 56:
                break
            x = r.right() - 14 - w if mine else r.x() + 14
            bubble = QRectF(x, y, w, h)
            p.setPen(Qt.NoPen if mine else QPen(QColor(c["line"]), 1))
            p.setBrush(QColor(c["me"] if mine else c["them"]))
            p.drawRoundedRect(bubble, 14, 14)
            p.setPen(QColor(c["ink"]))
            p.drawText(bubble.adjusted(12, 8, -12, -8), Qt.TextWordWrap, text)
            y -= 10
        # the input box and the send arrow
        box = QRectF(self.edit.geometry()).adjusted(-0.5, -0.5, 0.5, 0.5)
        p.setPen(QPen(QColor(theme.ACCENT) if self.edit.focused else QColor(c["line"]), 1.2))
        p.setBrush(QColor(c["body"]))
        p.drawRoundedRect(box, 20, 20)
        send = QRectF(box.right() + 8, box.y() + 2, 36, 36)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#22c55e"))
        p.drawEllipse(send)
        arrow = QPainterPath(QPointF(send.x() + 11, send.y() + 11))
        arrow.lineTo(send.right() - 9, send.center().y())
        arrow.lineTo(send.x() + 11, send.bottom() - 11)
        arrow.lineTo(send.x() + 14, send.center().y())
        arrow.closeSubpath()
        p.setBrush(QColor("#ffffff"))
        p.drawPath(arrow)


class Glow(QWidget):
    """錄音紅 along the desk's edges while listening, breathing like 柔光; mouse clicks go through."""
    DEPTH = 26

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.level = 0.0
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=1000 // 24, timeout=self.update)
        self._fade = QVariantAnimation(self, duration=FADE_MS)
        self._fade.valueChanged.connect(self._set)
        self._fade.finished.connect(self._faded)

    def _set(self, v):
        self.level = float(v)
        self.update()

    def _faded(self):
        if self.level <= 0:
            self.hide()
            self._timer.stop()

    def turn(self, on: bool):
        self._fade.stop()
        if on:
            self.show()
            self.raise_()
            if not calm():
                self._timer.start()
        self._fade.setStartValue(self.level)
        self._fade.setEndValue(1.0 if on else 0.0)
        self._fade.start()

    def paintEvent(self, _):
        p = QPainter(self)
        t = time.monotonic() - self._t0
        breath = 0.8 if calm() else 0.68 + 0.22 * math.sin(t * math.tau / 2.6)
        a = self.level * breath
        w, h, d = self.width(), self.height(), self.DEPTH
        for i, (x0, y0, x1, y1, rect) in enumerate(((0, 0, 0, d, QRectF(0, 0, w, d)),
                                                    (0, h, 0, h - d, QRectF(0, h - d, w, d)),
                                                    (0, 0, d, 0, QRectF(0, 0, d, h)),
                                                    (w, 0, w - d, 0, QRectF(w - d, 0, d, h)))):
            g = QLinearGradient(x0, y0, x1, y1)
            col = QColor(RED[i % 3])
            col.setAlphaF(min(1.0, 0.75 * a))
            g.setColorAt(0, col)
            col.setAlphaF(min(1.0, 0.25 * a))
            g.setColorAt(0.45, col)
            col.setAlphaF(0)
            g.setColorAt(1, col)
            p.fillRect(rect, g)


class Ring(QWidget):
    """A pulsing dashed outline round what the user is asked to click; clicks go through."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.target = QRect()
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=33, timeout=self.update)
        self.hide()

    def point_at(self, r: QRect | None, round_: bool = False):
        self.round = round_
        if r is None or r.isNull():
            self.hide()
            self._timer.stop()
            return
        self.target = QRect(r)
        self.setGeometry(r.adjusted(-12, -12, 12, 12))
        self.show()
        self.raise_()
        if not calm():
            self._timer.start()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = (time.monotonic() - self._t0) % 1.4 / 1.4
        grow = 0 if calm() else 4 * math.sin(t * math.pi)
        r = QRectF(self.rect()).adjusted(8 - grow, 8 - grow, -8 + grow, -8 + grow)
        col = QColor(theme.ACCENT)
        col.setAlphaF(0.9 - 0.4 * (0 if calm() else t))
        pen = QPen(col, 2, Qt.DashLine)
        pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if self.round:
            p.drawEllipse(r)
        else:
            p.drawRoundedRect(r, 9, 9)


class DeskPicker(Picker):
    """The real 選字 menu's look and behaviour, as a widget on the desk."""

    def __init__(self, parent, theme_):
        super().__init__()
        self.setParent(parent, Qt.Widget)
        self.use_theme(theme_)

    def open_under(self, rect: QRect, word: str, tabs):
        self._answered = False
        self.lead = True
        self.show_candidates(word, tabs)
        x = rect.x() - 12
        y = rect.bottom() + 6 - (12 - 4)
        if y + self.height() > self.parent().height() - BAR:
            y = rect.y() - 6 - round(self._box.bottom())
        self.move(max(0, min(x, self.parent().width() - self.width())), y)
        self.show()
        self.raise_()

    def _clamp(self):
        pass

    def mousePressEvent(self, e):
        e.accept()   # kept here: passed on, the desk closed the menu before the release picked (2026-10-24)

    def _no_activate(self):
        pass


class Desk(QWidget):
    """The desktop: wallpaper, taskbar, the two apps (shown when opened), the bubble, the floating button, the glow.
    `clicked_app` names a taskbar app clicked (or "tray", Art VoiceInput's icon), `stray` a click on nothing to click (the wallpaper, a window's frame,
    the rest of the taskbar); the tutorial does the rest."""
    clicked_app = Signal(str)
    stray = Signal()

    def __init__(self, parent, theme_):
        super().__init__(parent)
        self.wall = Wallpaper()
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=1000 // 24, timeout=self._frame)
        self.listening = False
        self.tray_icon = True      # Art VoiceInput's icon on the taskbar (pinned: 簡約), else under ︿
        self.running = set()       # the apps open, marked on the taskbar
        self.notepad = Notepad(self)
        self.chat = Chat(self)
        self.notepad.hide()
        self.chat.hide()
        self.glow = Glow(self)
        self.glow.hide()
        self.bubble = OrbButton(28, parent=self)
        self.bubble.hide()
        self.float = OrbButton(44, parent=self)
        self.float.hide()
        self.picker = DeskPicker(self, theme_)
        self.picker.hide()
        self.ring = Ring(self)
        self._fx = []

    # --- geometry ---
    def resizeEvent(self, e):
        w, h = self.width(), self.height()
        self.notepad.setGeometry(96, 40, 560, 330)
        self.chat.setGeometry(w - 420, 20, 350, 470)
        self.glow.setGeometry(0, 0, w, h)
        f = self.float
        f.move(w - EDGE - f.bsize - f.margin, (h - BAR) // 2 - f.height() // 2)   # where floatbtn puts it

    def taskbar_rect(self, kind: str) -> QRect:
        """The taskbar button of an app (notepad, chat)."""
        x = {"start": -88, "search": -44, "files": 0, "notepad": 44, "chat": 88}[kind]
        return QRect(self.width() // 2 - 20 + x, self.height() - BAR + 2, 40, 40)

    def tray_rect(self) -> QRect:
        """Art VoiceInput's tray icon (item 1 of the tray)."""
        return QRect(self.width() - TRAY_RIGHT - TRAY_STEP * 3 - 10, self.height() - BAR + 12, 20, 20)

    # --- animation ---
    def showEvent(self, e):
        if not calm():
            self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()

    def _frame(self):
        if calm():
            self._timer.stop()
        self.update(QRect(0, 0, self.width(), self.height() - BAR))
        if self.listening and self.tray_icon:   # the tray icon's ring turns (the taskbar isn't repainted otherwise)
            self.update(self.tray_rect())

    def open_app(self, w: AppWindow, kind: str):
        """In from a little lower, fading in (at once with 節流模式)."""
        self.running.add(kind)
        w.show()
        w.raise_()
        self.glow.raise_()
        self.ring.raise_()
        self.update()
        if calm():
            return
        end = w.pos()
        fx = QGraphicsOpacityEffect(w, opacity=0.0)
        w.setGraphicsEffect(fx)
        fade = QPropertyAnimation(fx, b"opacity", w, duration=220, startValue=0.0, endValue=1.0)
        slide = QPropertyAnimation(w, b"pos", w, duration=260, startValue=end + QPoint(0, 24), endValue=end,
                                   easingCurve=QEasingCurve.OutCubic)
        fade.finished.connect(lambda: w.setGraphicsEffect(None))
        fade.start()
        slide.start()
        self._fx = [fade, slide]

    # --- painting ---
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        phase = 0.0 if calm() else ((time.monotonic() - self._t0) % SWAY_S) / SWAY_S
        self.wall.paint(p, self.width(), self.height(), self.devicePixelRatioF(), phase)
        self._paint_taskbar(p)

    def _paint_taskbar(self, p: QPainter):
        c = WALL[_dark()]
        w, h = self.width(), self.height()
        top = h - BAR
        bar = QColor(c["bar"])
        bar.setAlphaF(c["bar_op"])
        p.fillRect(QRectF(0, top, w, BAR), bar)
        p.fillRect(QRectF(0, top, w, 1), QColor(c["bar_line"]))
        ink = QColor(c["ink"])
        # start: four squares
        r = self.taskbar_rect("start")
        g = QLinearGradient(r.x() + 12, r.y() + 12, r.x() + 28, r.y() + 28)
        g.setColorAt(0, QColor("#3fa2f7"))
        g.setColorAt(1, QColor("#0a64d8"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        for dx in (0, 8.7):
            for dy in (0, 8.7):
                p.drawRoundedRect(QRectF(r.x() + 12 + dx, r.y() + 12 + dy, 7.5, 7.5), 1, 1)
        # search
        r = self.taskbar_rect("search")
        p.setPen(QPen(ink, 1.8, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(r.center().x() - 1.5, r.center().y() - 1.5), 5.5, 5.5)
        p.drawLine(QPointF(r.center().x() + 2.5, r.center().y() + 2.5), QPointF(r.center().x() + 7, r.center().y() + 7))
        # files
        r = QRectF(self.taskbar_rect("files"))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e8a91c"))
        p.drawRoundedRect(QRectF(r.center().x() - 10, r.center().y() - 7, 20, 15), 2, 2)
        p.setBrush(QColor("#ffcd4a"))
        p.drawRoundedRect(QRectF(r.center().x() - 11, r.center().y() - 2, 22, 10), 2, 2)
        # the two apps, with a dash under those open
        for kind in ("notepad", "chat"):
            r = QRectF(self.taskbar_rect(kind))
            if kind in self.running:
                hover = QColor(ink)
                hover.setAlphaF(0.08)
                p.setPen(Qt.NoPen)
                p.setBrush(hover)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 5, 5)
                p.setBrush(QColor(theme.ACCENT) if kind == self.front() else QColor(c["gear"]))
                dash = 16 if kind == self.front() else 6
                p.drawRoundedRect(QRectF(r.center().x() - dash / 2, r.bottom() - 4, dash, 3), 1.5, 1.5)
            paint_app_icon(p, kind, QRectF(r.center().x() - 11, r.center().y() - 12, 22, 22))
        # the tray as Windows 11 lays it out (the user's screenshot, 2026-10-24): ︿, Art VoiceInput's icon (while
        # listening its microphone gives way to a ring turning, as in tray.py), 英, Wi-Fi, volume, TRAY_STEP apart
        y = top + BAR / 2
        cx = lambda i: w - TRAY_RIGHT - TRAY_STEP * (4 - i)   # noqa: E731  the centre of item i
        p.setPen(QPen(ink, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        x = cx(0) if self.tray_icon else cx(1)
        p.drawPolyline([QPointF(x - 4, y + 2), QPointF(x, y - 2), QPointF(x + 4, y + 2)])
        r = QRectF(self.tray_rect())
        p.save()
        if not self.tray_icon:
            p.setClipRect(QRectF())   # hidden under ︿, as Windows keeps an icon not pinned
        p.translate(r.topLeft() + QPointF(1, 1))
        if self.listening:
            appicon.tile(p, 18)
            ring = QRectF(4, 4, 10, 10)
            pen = QPen(QColor(255, 255, 255, 90), 2.0)
            p.setPen(pen)
            p.drawEllipse(ring)
            pen.setColor(QColor("#ffffff"))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            turn = ((time.monotonic() - self._t0) % 1.2) / 1.2
            p.drawArc(ring, round((90 - 360 * turn) * 16), -110 * 16)
        else:
            appicon.paint(p, 18)
        p.restore()
        p.setPen(ink)   # the input method
        p.setFont(theme.font(12))
        p.drawText(QRectF(cx(2) - 10, y - 10, 20, 20), Qt.AlignCenter, "英")
        x = cx(3)   # Wi-Fi: two arcs over a dot
        p.setPen(QPen(ink, 1.5, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(x - 7.5, y - 4.5, 15, 15), 47 * 16, 86 * 16)
        p.drawArc(QRectF(x - 4.2, y - 1.2, 8.4, 8.4), 47 * 16, 86 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(ink)
        p.drawEllipse(QPointF(x, y + 4), 1.4, 1.4)
        x = cx(4) - 5   # volume: the speaker and one wave
        speaker = QPainterPath(QPointF(x, y - 2.5))
        for dx, dy in ((3, -2.5), (7, -6), (7, 7), (3, 3.5), (0, 3.5)):
            speaker.lineTo(x + dx, y + dy)
        speaker.closeSubpath()
        p.drawPath(speaker)
        p.setPen(QPen(ink, 1.4, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(x + 5, y - 3, 7, 7), -60 * 16, 120 * 16)
        p.setPen(QColor(c["text"]))
        p.setFont(theme.font(10.5))
        now = time.localtime()
        hour = now.tm_hour % 12 or 12
        clock = f"{'上午' if now.tm_hour < 12 else '下午'} {hour}:{now.tm_min:02d}"
        p.drawText(QRectF(w - 88, top + 5, 100, 18), Qt.AlignCenter, clock)
        p.drawText(QRectF(w - 88, top + 21, 100, 18), Qt.AlignCenter,
                   f"{now.tm_year}/{now.tm_mon}/{now.tm_mday}")

    def front(self) -> str:
        """The app whose window is on top."""
        shown = [k for k, win in (("notepad", self.notepad), ("chat", self.chat)) if win.isVisible()]
        if len(shown) == 2:
            return "chat" if self.children().index(self.chat) > self.children().index(self.notepad) else "notepad"
        return shown[0] if shown else ""

    def mousePressEvent(self, e):
        self.picker.dismiss()
        pos = e.position().toPoint()
        if self.childAt(pos) is not None:
            return   # passed on by one of ours that took no press (the bubble, the floating button)
        for kind in ("notepad", "chat"):
            if self.taskbar_rect(kind).contains(pos):
                self.clicked_app.emit(kind)
                return
        if self.tray_icon and self.tray_rect().adjusted(-4, -8, 4, 8).contains(pos):
            self.clicked_app.emit("tray")
            return
        self.stray.emit()
