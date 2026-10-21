"""辨識紀錄 (design 1, the user's pick): a timeline, newest first. A session (listening on, or what was done while
it was off) is a node with its time and length; each event under it shows its time, a colored dot and tag for its kind,
what changed on the screen (new text green, removed struck through red), a yellow ! when the 詞庫 may have shaped it
and a copy button for a finished sentence. What was heard and why are the row's tooltip. Filters by kind."""
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import logbook
from . import theme
from .kit import Choice, T, Tip, button, dim, icon, label

FILTERS = [("all", "全部"), ("text", "文字"), ("cmd", "指令"), ("fix", "選字與復原")]
KIND_COLORS = {"text": "#FF453A", "cmd": "#3D7BFF", "pick": "#A259FF", "undo": "#8A9099", "hint": "#D9822B"}
SETTLED = ("#C8323E", "#E8525C")   # 定稿, light and dark: the text red a little deeper (2026-10-21, the user's pick)
MAX_ROWS = 300   # rows drawn, newest first
LINE_X = 77      # the timeline's x


def kind_of(r: dict) -> str:
    """text, cmd, pick or undo (the filters and colors)."""
    if r["kind"] in ("undo", "hint"):
        return r["kind"]
    if r["kind"] == "op":
        return "pick" if r["tag"] in ("選字", "刪除") or r["heard"] in ("（選字）", "（刪除）") else "cmd"
    return "text"


def tag_of(r: dict) -> str:
    k = kind_of(r)
    if k == "cmd":
        return "指令" if r["tag"].startswith("指令") else (r["tag"] or "指令")
    if k == "pick":
        return r["tag"] or "選字"
    if k == "undo":
        return "復原"
    if k == "hint":
        return r["tag"]
    return "文字" if r["kind"] in ("", "lock") else (r["tag"].split("；")[0] if r["tag"] else "文字")


def _seconds(a: str, b: str) -> int:
    def s(t):
        h, m, sec = (int(x) for x in t.split(":"))
        return h * 3600 + m * 60 + sec
    try:
        return max(0, s(b) - s(a)) % 86400
    except ValueError:
        return 0


def _span(sec: int) -> str:
    return f"{sec // 60} 分 {sec % 60} 秒" if sec >= 60 else f"{sec} 秒"


class Node(QWidget):
    """A session's head: a ring on the line, its time and what it was."""

    def __init__(self, title: str, meta: str):
        super().__init__()
        self.title, self.meta = title, meta
        self.setFixedHeight(40)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(LINE_X, 0, 2, self.height()), T("line"))
        c = QPointF(LINE_X + 1, 26)
        p.setPen(Qt.NoPen)
        p.setBrush(T("ink"))
        p.drawEllipse(c, 6, 6)
        p.setBrush(T("bg"))
        p.drawEllipse(c, 3, 3)
        p.setPen(T("ink"))
        p.setFont(theme.font(14, 700))
        fm = p.fontMetrics()
        p.drawText(QPointF(LINE_X + 16, 26 + fm.ascent() / 2 - 2), self.title)
        x = LINE_X + 16 + fm.horizontalAdvance(self.title) + 10
        p.setPen(T("muted"))
        p.setFont(theme.font(12.5))
        p.drawText(QPointF(x, 26 + p.fontMetrics().ascent() / 2 - 2), self.meta)


class Entry(QWidget):
    """An event: time, a dot on the line, its tag, the change, ! and copy."""
    copy = Signal(str)
    link = Signal(str)   # a hint row clicked: where it leads ("packs")

    def __init__(self, r: dict, dark: bool):
        super().__init__()
        self.r = r
        self.kind = kind_of(r)
        self.setMouseTracking(True)
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 6, 10, 6)
        h.setSpacing(10)
        t = label(r["time"])
        t.setFont(theme.font(12.5, 500, num=True))
        t.setStyleSheet(f"color: {T('muted').name()};")
        t.setFixedSize(58, 22)
        h.addWidget(t, 0, Qt.AlignTop)
        h.addSpacing(18)   # the dot is painted on the line
        tag = QLabel(tag_of(r))
        tag.setFont(theme.font(11.5, 700))
        color = self.color = SETTLED[dark] if tag_of(r) == "定稿" else KIND_COLORS[self.kind]
        c = QColor(color)
        tag.setStyleSheet(f"color: {color}; background: rgba({c.red()},{c.green()},{c.blue()},34); border-radius: 4px;"
                          " padding: 2px 7px;")
        h.addWidget(tag, 0, Qt.AlignTop)
        change = r["change"]
        if dark:
            change = change.replace(logbook.INS, "background-color:#1E3B29; color:#62D683").replace(
                logbook.DEL, "background-color:#43252A; color:#FF8A80; text-decoration:line-through")
        body = QLabel(change)
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setFont(theme.font(14.5))
        body.setStyleSheet("line-height: 160%;")
        body.setTextInteractionFlags(Qt.NoTextInteraction)
        h.addWidget(body, 1)
        if r.get("bank"):
            # the 詞庫 tile's book: good news (the user's settings at work), not a warning
            bang = QLabel()
            bang.setFixedSize(22, 22)
            bang.setAlignment(Qt.AlignCenter)
            bang.setPixmap(icon("bank", T("acc"), 16, 1.9).pixmap(QSize(16, 16), 2.0))
            bang.setToolTip("\n".join(["詞庫可能影響了這句："] + r["bank"]))
            bang.setProperty("quick_tip", True)
            h.addWidget(bang, 0, Qt.AlignTop)
        if r["copy"]:
            b = button("", lambda: self.copy.emit(r["copy"]), ib=True)
            b.setIcon(icon("copy", T("muted"), 15, 1.9))
            # as high as the time and tag (22): at 28 it made its row taller, the row's text sat high in it
            b.setStyleSheet("min-height: 22px; max-height: 22px; min-width: 22px; max-width: 22px;")
            b.setToolTip("複製這句")
            b.setProperty("quick_tip", True)
            h.addWidget(b, 0, Qt.AlignTop)
        tip = [x for x in (f"聽到：{r['heard']}" if r["heard"] else "", r["tag"], r["tip"]) if x]
        self.setToolTip("\n".join(tip))
        self.setProperty("quick_tip", True)   # shown as soon as the pointer comes, not after kit.TipRouter's second
        if r.get("link"):
            self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if self.r.get("link") and e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.link.emit(self.r["link"])
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(T("tile"))
            p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        p.fillRect(QRectF(LINE_X, 0, 2, self.height()), T("line"))
        p.setPen(Qt.NoPen)
        p.setBrush(T("bg"))
        c = QPointF(LINE_X + 1, 17)
        p.drawEllipse(c, 7, 7)
        p.setBrush(QColor(self.color))
        p.drawEllipse(c, 4, 4)


class LogPage(QWidget):
    title = "辨識紀錄"

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.filter = "all"
        self.sessions = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.filters = Choice(FILTERS, "all")
        self.filters.picked.connect(self._pick)
        top = QHBoxLayout()
        top.addWidget(self.filters)
        top.addStretch(1)
        top.addWidget(dim("只保留這次執行期間，不會存檔"))
        top.addSpacing(10)
        top.addWidget(button("清除紀錄", self._clear))
        v.addLayout(top)
        self.body = QVBoxLayout()
        self.body.setSpacing(0)
        v.addLayout(self.body)
        v.addStretch(1)

    def load(self):
        pass

    def restyle(self):
        self._draw()

    def summary(self) -> str:
        for g in reversed(self.sessions):
            for r in reversed(g["rows"]):
                if r["copy"]:
                    return f"最近一句：{r['copy']}"
        return "每次辨識的結果與修改"

    def set_log(self, sessions):
        self.sessions = list(sessions)
        if self.isVisible():
            self._draw()
        else:
            self._dirty = True

    def shown(self):
        self._draw()

    def showEvent(self, e):
        if getattr(self, "_dirty", False):
            self._draw()
        super().showEvent(e)

    def _pick(self, key):
        self.filter = key
        self._draw()

    def _clear(self):
        self.win.clear_log.emit()

    def _keep(self, r) -> bool:
        k = kind_of(r)
        return self.filter == "all" or k == self.filter or (self.filter == "fix" and k in ("pick", "undo"))

    def _draw(self):
        self._dirty = False
        while self.body.count():
            w = self.body.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        dark = self.win.theme["dark"]
        left = MAX_ROWS
        for g in reversed(self.sessions):
            rows = [r for r in reversed(g["rows"]) if self._keep(r)]
            if not rows or left <= 0:
                continue
            head = "麥克風開著" if g["listening"] else "沒開麥克風時"
            meta = f"{_span(_seconds(g['start'], g['end']))} · {len(rows)} 筆" if g["listening"] else f"{len(rows)} 筆"
            self.body.addWidget(Node(f"{g['start'][:5]}　{head}", meta))
            for r in rows[:left]:
                e = Entry(r, dark)
                e.link.connect(lambda key: key == "packs" and self.win.show_packs())
                e.copy.connect(self._copy)
                self.body.addWidget(e)
            left -= len(rows)
        if self.body.count() == 0:
            empty = dim("開麥克風後，每段話聽到什麼、畫面上變成什麼會顯示在這裡" if self.filter == "all"
                        else "這次執行還沒有這類紀錄", wrap=True)
            empty.setContentsMargins(4, 12, 4, 12)
            self.body.addWidget(empty)

    def _copy(self, text: str):
        QApplication.clipboard().setText(text)
        Tip.flash(QCursor.pos() + QPoint(12, 18), "已複製", self, 1200)
