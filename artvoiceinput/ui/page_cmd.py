"""語音指令 (design C4, the user's pick): one rule per line, "當我說 [phrases] 就 [does what]", grouped by what they do
with the group on the left (an orange bar). The phrases are chips: a click edits one in place, × removes it, ＋ adds
one; a built-in row without phrases is off. 自訂 rows also choose what they do; 新增一句 adds one. Under them, 說標點的名字
and 說「詞的字」, each with a switch. A phrase said for two things is marked and explained at the top."""
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLineEdit,
                               QSizePolicy, QVBoxLayout, QWidget)

from .. import rules
from ..keys import MOUSE_VKS, combo_text, is_modifier
from ..rules import Rule, Step
from . import theme
from .kit import Info, Keycap, Switch, T, button, card, dim, draw_icon, hbox, icon, label

GROUPS = [("輸入", "打字時用"), ("修改", "說錯時用"), ("剪貼簿", "搬文字用"), ("工具", "用滑鼠點著打"), ("結束", "講完時用"),
          ("自訂", "你自己加的")]
CUSTOM = len(GROUPS) - 1
# the built-in rows (rules.defaults): group, verb, what, how it is shown, a note
BUILT = {
    (rules.KEYS, "Shift+Enter"): (0, "按下", "Shift+Enter", "key", "在同一格裡換行"),
    (rules.KEYS, "Space"): (0, "按下", "Space", "key", "輸入一個空白"),
    (rules.WRAP, ("（", "）")): (0, "打出", "（ ｜ ）", "wrap", "游標停在中間；有選取時包住選取的字"),
    (rules.WRAP, ("「", "」")): (0, "打出", "「 ｜ 」", "wrap", "游標停在中間；有選取時包住選取的字"),
    (rules.KEYS, "Backspace"): (1, "按下", "Backspace", "key", "有選取時刪掉選取的字"),
    (rules.COMMAND, rules.UNDO): (1, "", "復原上一步", "cmd", "收回剛才打的字或改動，一次一步"),
    (rules.COMMAND, rules.SELECT_ALL): (2, "", "全選", "cmd", "終端機裡無法全選"),
    (rules.COMMAND, rules.COPY): (2, "", "複製", "cmd", "複製選取的文字"),
    (rules.COMMAND, rules.CUT): (2, "", "剪下", "cmd", "剪下選取的文字"),
    (rules.COMMAND, rules.PASTE): (2, "", "貼上", "cmd", "有選取時取代它"),
    (rules.COMMAND, rules.KEYBOARD): (3, "", "打開符號選單", "cmd", "在游標下方，點一個符號就打出來"),
    (rules.COMMAND, rules.OSK): (3, "", "打開螢幕小鍵盤", "cmd", "Windows 內建的鍵盤，用滑鼠點著打字"),
    (rules.KEYS, "Enter"): (4, "按下", "Enter", "key", "送出訊息"),
    (rules.COMMAND, rules.STOP): (4, "", "關閉麥克風", "cmd", "不按 Enter"),
}
KINDS = [(rules.KEYS, "按下按鍵"), (rules.TEXT, "打出文字"), (rules.WRAP, "左右包住")]
# 說標點的名字's keycaps: one per mark, its names together (2026-10-22, the user's design); edit.SYMBOLS but
# 驚歎號 (a way X-ASR writes 驚嘆號)
PUNCTS = [("，", "逗號\n逗點"), ("。", "句號\n句點"), ("、", "頓號"), ("？", "問號"), ("！", "驚嘆號"),
          ("；", "分號"), ("：", "冒號"), ("……", "刪節號\n省略號"), ("——", "破折號"),
          ("／", "斜線\n斜槓")]


def _key(kind, value):
    return kind, tuple(value) if isinstance(value, list) else value


def _opacity(w: QWidget, a: float):
    if a >= 1:
        w.setGraphicsEffect(None)
    else:
        fx = w.graphicsEffect() or QGraphicsOpacityEffect(w)
        fx.setOpacity(a)
        w.setGraphicsEffect(fx)


# --- phrases ---
class Chip(QAbstractButton):
    """A phrase: an orange pill; the pointer over it shows ×. A phrase said for two things is outlined and underlined."""
    edit = Signal()
    remove = Signal()

    def __init__(self, text: str, bad: bool = False):
        super().__init__()
        self.text_, self.bad = text, bad
        self.setCursor(Qt.IBeamCursor)
        self.setFont(theme.font(13.5, 700))
        self.setFixedHeight(28)
        self.setFixedWidth(self.fontMetrics().horizontalAdvance(text) + 12 + 26)
        self.setToolTip("點一下修改")
        self.setMouseTracking(True)

    def _on_x(self, pos) -> bool:
        return pos.x() > self.width() - 24

    def mouseMoveEvent(self, e):
        on_x = self._on_x(e.position())
        self.setCursor(Qt.PointingHandCursor if on_x else Qt.IBeamCursor)
        self.setToolTip("" if on_x else "點一下修改")   # nothing over the ×
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            (self.remove if self._on_x(e.position()) and self.underMouse() else self.edit).emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        p.setPen(QPen(T("acc"), 1.5) if (self.bad or self.underMouse()) else Qt.NoPen)
        bg = T("accbg")
        if self.bad:
            bg = QColor(255, 69, 58, 51)
        p.setBrush(bg)
        p.drawRoundedRect(r, 14, 14)
        p.setPen(T("acct"))
        p.setFont(self.font())
        tr = QRectF(12, 0, self.width() - 12 - 26, self.height())
        p.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft, self.text_)
        if self.bad:
            pen = QPen(T("acc"), 1.2)
            p.setPen(pen)
            w = self.fontMetrics().horizontalAdvance(self.text_)
            y = self.height() - 6.5
            path = QPainterPath(QPointF(12, y))
            x = 12.0
            while x < 12 + w:
                path.quadTo(QPointF(x + 1.5, y - 2 if int(x) % 6 < 3 else y + 2), QPointF(x + 3, y))
                x += 3
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        if self.underMouse():
            p.setOpacity(0.75)
            draw_icon(p, "x", QRectF(self.width() - 21, 9, 10, 10), T("acct"), 2.4)


class AddChip(QAbstractButton):
    """＋ (with 說法 when the row has none): a dashed pill that adds a phrase."""

    def __init__(self, words: bool):
        super().__init__()
        self.words = words
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("新增說法")
        self.setFont(theme.font(12.5))
        self.setFixedHeight(28)
        self.setFixedWidth(64 if words else 34)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hot = self.underMouse()
        pen = QPen(T("acc") if hot else T("line"), 1.5, Qt.DashLine)
        pen.setDashPattern([3, 2])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75), 14, 14)
        p.setPen(T("acct") if hot else T("muted"))
        p.setFont(self.font())
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, "＋ 說法" if self.words else "＋")


class ChipEdit(QLineEdit):
    """A phrase being typed: Enter or leaving keeps it, Esc puts back what was there."""
    done = Signal(str)

    def __init__(self, text: str):
        super().__init__(text)
        self.setPlaceholderText("輸入說法")
        self.setFixedSize(110, 28)
        self.setFont(theme.font(13.5, 700))
        self._orig = text
        self._finished = False
        self.returnPressed.connect(lambda: self._finish(self.text()))

    def restyle(self):
        self.setStyleSheet(f"QLineEdit {{ border-radius: 14px; border: 2px solid {T('acc').name()};"
                           f" background: {T('tile').name()}; color: {T('acct').name()}; padding: 0 10px;"
                           f" min-height: 24px; }}")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._finish(self._orig)
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        QTimer.singleShot(0, lambda: self._finish(self.text()))

    def _finish(self, text: str):
        if not self._finished:
            self._finished = True
            self.done.emit(text.strip())


class ChipSet(QWidget):
    """A row's phrases: chips, one of them maybe being edited, and ＋."""
    changed = Signal(list)

    def __init__(self, phrases: list, bad: set, off_text: bool):
        super().__init__()
        self.phrases = list(phrases)
        self.bad = bad
        self.off_text = off_text
        self.editing = None
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(6)
        self._build()

    def _build(self):
        _hold(self)
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        for i, ph in enumerate(self.phrases):
            if i == self.editing:
                e = ChipEdit(ph)
                e.restyle()
                e.done.connect(lambda text, i=i: self._commit(i, text))
                self._lay.addWidget(e)
                QTimer.singleShot(0, lambda e=e: (e.setFocus(), e.selectAll()))
            else:
                c = Chip(ph, rules.normalize(ph) in self.bad)
                c.edit.connect(lambda i=i: self._edit(i))
                c.remove.connect(lambda i=i: self._remove(i))
                self._lay.addWidget(c)
        if not self.phrases and self.off_text:
            off = label("已停用")
            off.setFont(theme.font(12, 700))
            off.setStyleSheet(f"color: {T('muted').name()}; padding: 0 4px;")
            self._lay.addWidget(off)
        if self.editing is None:
            add = AddChip(not self.phrases)
            add.clicked.connect(self._add)
            self._lay.addWidget(add)

    def _edit(self, i):
        self.editing = i
        self._build()

    def _add(self):
        self.phrases.append("")
        self.editing = len(self.phrases) - 1
        self._build()

    def start_new(self):
        self._add()

    def _remove(self, i):
        del self.phrases[i]
        self.editing = None
        self._build()
        self.changed.emit(self.phrases)

    def _commit(self, i, text):
        if self.editing != i:
            return
        self.editing = None
        if text:
            self.phrases[i] = text
        else:
            del self.phrases[i]
        QTimer.singleShot(0, self._build)   # not from inside the editor's own signal
        QTimer.singleShot(0, lambda: self.changed.emit(self.phrases))


# --- what a rule does ---
class Act(QWidget):
    """What a built-in rule does: a key as a keycap, a pair of marks, a command in a box."""

    def __init__(self, kind: str, text: str):
        super().__init__()
        self.kind, self.text = kind, text
        f = theme.font(13.5, 600, num=True) if kind == "key" else theme.font(14, 700) if kind == "wrap" \
            else theme.font(13, 500)
        self.setFont(f)
        w = self.fontMetrics().horizontalAdvance(text)
        self.setFixedSize(w + (16 if kind == "key" else 18 if kind == "cmd" else 2), 24)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.kind == "key":
            p.setPen(QPen(T("line"), 1))
            p.setBrush(T("line"))
            p.drawRoundedRect(r, 5, 5)
            p.setPen(Qt.NoPen)
            p.setBrush(T("tile2"))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -2), 4, 4)
        elif self.kind == "cmd":
            p.setPen(QPen(T("line"), 1))
            p.setBrush(T("tile2"))
            p.drawRoundedRect(r, 5, 5)
        p.setPen(T("ink"))
        p.setFont(self.font())
        p.drawText(QRectF(self.rect()).adjusted(0, 0, 0, -1 if self.kind == "key" else 0), Qt.AlignCenter, self.text)


def _hold(w: QWidget):
    """Rebuilt out of sight: the whole window waits a moment, the scroll area too (the page alone was not enough:
    the table shrank for a moment and the view jumped)."""
    if not w.isVisible():   # nothing to hide (a theme change restyles this page unseen)
        return
    top = w.window()
    if top.updatesEnabled():
        top.setUpdatesEnabled(False)
        QTimer.singleShot(40, lambda: _release(top))


def _release(top: QWidget):
    # re-enabled, the window was not always painted again: a theme picked on 系統 showed only after going home
    # (2026-10-21)
    top.setUpdatesEnabled(True)
    top.update()


def _note(text: str):
    """What a rule does, after its controls: wraps onto a second line rather than pushing the row past the window
    (左右包住's note did, 2026-10-21)."""
    n = dim(text, wrap=True)
    n.setMinimumWidth(60)
    n.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return n


class KeyField(QLineEdit):
    """Click, then press a key combination or a mouse button but the left (Ctrl+Shift+Z, 滑鼠右鍵): shown as text.
    Waiting for the keys (focused) it is tinted and says so; otherwise it looks like any field, empty or not."""
    captured = Signal(str)
    IDLE, WAIT = "點這裡設定按鍵", "請按下按鍵…"

    def __init__(self, text: str):
        super().__init__(text)
        self.setReadOnly(True)
        self.setPlaceholderText(self.IDLE)
        self.setProperty("slim", True)
        self.setProperty("keys", True)
        self.setFixedWidth(150)
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(theme.font(13.5, 600, num=True))

    def event(self, e):
        if e.type() == QEvent.KeyPress:   # here, not keyPressEvent: Tab would move the focus first
            vk = e.nativeVirtualKey()
            if not is_modifier(vk):
                self._take(e.modifiers(), vk)
            return True
        if e.type() == QEvent.MouseButtonPress and self.hasFocus():
            name = {Qt.RightButton: "滑鼠右鍵", Qt.MiddleButton: "滑鼠中鍵", Qt.BackButton: "滑鼠側鍵（下）",
                    Qt.ForwardButton: "滑鼠側鍵（上）"}.get(e.button())
            if name:
                self._take(e.modifiers(), MOUSE_VKS[name])
                return True
        if e.type() == QEvent.ContextMenu:   # the right button is a key here
            return True
        if e.type() == QEvent.FocusIn:
            self.setPlaceholderText(self.WAIT)
        elif e.type() == QEvent.FocusOut:
            self.setPlaceholderText(self.IDLE)
        return super().event(e)

    def _take(self, mods, vk: int):
        names = [n for n, flag in (("Ctrl", Qt.ControlModifier), ("Shift", Qt.ShiftModifier),
                                   ("Alt", Qt.AltModifier), ("Win", Qt.MetaModifier)) if mods & flag]
        text = combo_text(names, vk)
        if text:
            self.setText(text)
            self.captured.emit(text)


class RuleRow(QWidget):
    """One rule: 當我說 [phrases] 就 [what]. The top edge is the line between rows."""
    changed = Signal()
    removed = Signal()

    def __init__(self, row: dict, bad: set, stop_on_enter: bool):
        super().__init__()
        self.row = row
        self.rebuild = False   # its controls must change (another kind of action picked)
        self.setMinimumHeight(50)
        self.setMouseTracking(True)
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 10, 12, 10)
        h.setSpacing(10)
        h.addWidget(self._w("當我說"))
        self.chips = ChipSet(row["phrases"], bad, off_text=row["builtin"])
        self.chips.changed.connect(self._phrases)
        h.addWidget(self.chips)
        h.addWidget(self._w("就"))
        then = QWidget()
        th = QHBoxLayout(then)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(8)
        if row["builtin"]:
            _, verb, what, kind, note = BUILT[_key(row["type"], row["value"])]
            if row["type"] == rules.KEYS and row["value"] == "Enter":
                note = "送出訊息，麥克風會關閉" if stop_on_enter else "送出訊息，麥克風繼續開著"
            if verb:
                v = label(verb)
                v.setFont(theme.font(14, 500))
                th.addWidget(v)
            th.addWidget(Act(kind, what))
            if note:
                th.addWidget(_note(note), 1)
        else:
            self._custom(th)
        if not any(th.stretch(i) for i in range(th.count())):   # a note takes the room left itself
            th.addStretch(1)
        h.addWidget(then, 1)
        if not row["builtin"]:
            x = button("", self.removed.emit, ib=True)
            x.setToolTip("刪除這一句")
            x.setIcon(icon("x", T("muted"), 14, 2.2))
            h.addWidget(x)
        self.then = then
        _opacity(then, 0.4 if row["builtin"] and not row["phrases"] else 1.0)

    @staticmethod
    def _w(text):
        w = label(text)
        w.setStyleSheet(f"color: {T('muted').name()}; font-size: 13px;")
        return w

    def _custom(self, th):
        row = self.row
        kind = QComboBox()
        kind.setCursor(Qt.PointingHandCursor)
        kind.setProperty("slim", True)   # the style sheet's height fits the row (a fixed height was overridden)
        if row["type"] is None:
            kind.addItem("選擇要做的事", None)
        for k, name in KINDS:
            kind.addItem(name, k)
        kind.setCurrentIndex(max(0, kind.findData(row["type"])))
        if row["type"] is None:
            kind.setStyleSheet(f"QComboBox {{ border: 1px solid {T('acc').name()}; color: {T('acct').name()}; }}")
        kind.currentIndexChanged.connect(lambda: self._kind(kind.currentData()))
        th.addWidget(kind)
        if row["type"] == rules.KEYS:
            f = KeyField(row["value"] or "")
            f.captured.connect(lambda t: self._value(t))
            th.addWidget(f)
        elif row["type"] == rules.TEXT:
            f = QLineEdit(row["value"] or "")
            f.setPlaceholderText("要打出的文字")
            f.setProperty("slim", True)
            f.setFixedWidth(160)
            f.editingFinished.connect(lambda: self._value(f.text()))
            th.addWidget(f)
        elif row["type"] == rules.WRAP:
            pair = list(row["value"]) if isinstance(row["value"], (list, tuple)) and len(row["value"]) == 2 else ["", ""]
            row["value"] = pair
            for i, hint in ((0, "左邊"), (1, "右邊")):
                f = QLineEdit(pair[i])
                f.setPlaceholderText(hint)
                f.setProperty("slim", True)
                f.setFixedWidth(64)
                f.setAlignment(Qt.AlignCenter)
                f.editingFinished.connect(lambda i=i, f=f: self._pair(i, f.text()))
                th.addWidget(f)
                if i == 0:
                    bar = label("｜")
                    bar.setStyleSheet(f"color: {T('muted').name()};")
                    th.addWidget(bar)
            th.addWidget(_note("游標停在中間；有選取時包住選取的字"), 1)

    def _phrases(self, phrases):
        self.row["phrases"] = list(phrases)
        self.changed.emit()

    def _kind(self, kind):
        if kind == self.row["type"]:
            return
        self.row["type"] = kind
        self.row["value"] = ["", ""] if kind == rules.WRAP else ""
        self.rebuild = True
        self.changed.emit()

    def _value(self, v):
        if v != self.row["value"]:
            self.row["value"] = v
            self.changed.emit()

    def _pair(self, i, text):
        if self.row["value"][i] != text:
            self.row["value"][i] = text
            self.changed.emit()

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if self.underMouse():
            p.fillRect(self.rect(), T("tile2"))
        if self.property("first") is not True:
            p.fillRect(0, 0, self.width(), 1, T("line"))


class GroupLabel(QWidget):
    """A group's name on the left of its rows: an orange bar, the name, what it is for, how many."""

    def __init__(self, name: str, hint: str, count: str, first: bool):
        super().__init__()
        self.name, self.hint, self.count, self.first = name, hint, count, first
        self.setFixedWidth(148)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.first:
            p.fillRect(0, 0, self.width(), 1, T("line"))
        p.fillRect(self.width() - 1, 0, 1, self.height(), T("line"))
        p.setPen(Qt.NoPen)
        p.setBrush(T("acc"))
        p.drawRoundedRect(QRectF(-3, 12, 7, self.height() - 24), 3, 3)
        p.setPen(T("ink"))
        p.setFont(theme.font(16, 700))
        p.drawText(QRectF(20, 12, self.width() - 30, 24), Qt.AlignLeft | Qt.AlignVCenter, self.name)
        p.setPen(T("muted"))
        p.setFont(theme.font(12))
        p.drawText(QRectF(20, 37, self.width() - 30, 18), Qt.AlignLeft | Qt.AlignVCenter, self.hint)
        p.setPen(T("acct"))
        p.setFont(theme.font(12, 600, num=True))
        p.drawText(QRectF(20, 58, self.width() - 30, 18), Qt.AlignLeft | Qt.AlignVCenter, self.count)


class AddBig(QAbstractButton):
    """新增一句: a dashed box with an orange ＋."""

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("新增一句")
        self.setFixedHeight(54)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        hot = self.underMouse()
        pen = QPen(T("acc") if hot else T("line"), 1.5, Qt.DashLine)
        pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.setBrush(T("accbg") if hot else Qt.NoBrush)
        p.drawRoundedRect(r, 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(T("acc"))
        c = QPointF(14 + 15, r.center().y())
        p.drawEllipse(c, 15, 15)
        draw_icon(p, "plus", QRectF(c.x() - 8, c.y() - 8, 16, 16), QColor("#FFFFFF"), 2.4)
        p.setPen(T("ink"))
        p.setFont(theme.font(14, 700))
        p.drawText(QRectF(56, 8, r.width() - 60, 20), Qt.AlignLeft | Qt.AlignVCenter, "新增一句")
        p.setPen(T("muted"))
        p.setFont(theme.font(12))
        p.drawText(QRectF(56, 27, r.width() - 60, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "例如說「箭頭」打出 →，或說「下一格」按 Tab")


class Banner(QWidget):
    """The problem at the top: a red ! and the text."""

    def __init__(self):
        super().__init__()
        self.text = ""
        self.setFixedHeight(38)

    def set(self, text: str):
        self.text = text
        self.setVisible(bool(text))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 69, 58, 26))
        p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        p.setBrush(T("acc"))
        p.drawEllipse(QPointF(12 + 9, self.height() / 2), 9, 9)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(theme.font(12, 700))
        p.drawText(QRectF(12, 0, 18, self.height()), Qt.AlignCenter, "!")
        p.setPen(T("acct"))
        p.setFont(theme.font(13, 500))
        p.drawText(QRectF(38, 0, self.width() - 44, self.height()), Qt.AlignLeft | Qt.AlignVCenter, self.text)


class Example(QWidget):
    """節日的節 → 節: the phrase as a pill (的 faint), an arrow, the character as a keycap."""

    def __init__(self, word: str, ch: str):
        super().__init__()
        self.word, self.ch = word, ch
        self.setFixedHeight(34)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = theme.font(13.5, 700)
        p.setFont(f)
        fm = p.fontMetrics()
        parts = [(self.word, 1.0), ("的", 0.55), (self.ch, 1.0)]
        w = sum(fm.horizontalAdvance(t) for t, _ in parts) + 2 + 22
        y = (self.height() - 28) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(T("accbg"))
        p.drawRoundedRect(QRectF(0, y, w, 28), 14, 14)
        x = 11
        for t, a in parts:
            p.setOpacity(a)
            p.setPen(T("acct"))
            p.drawText(QRectF(x, y, 100, 28), Qt.AlignLeft | Qt.AlignVCenter, t)
            x += fm.horizontalAdvance(t) + (1 if t == "的" or a < 1 else 0)
        p.setOpacity(1)
        ax = w + 10
        p.setPen(QPen(T("acc"), 2))
        p.drawLine(QPointF(ax, self.height() / 2), QPointF(ax + 18, self.height() / 2))
        p.setPen(Qt.NoPen)
        p.setBrush(T("acc"))
        tip = [QPointF(ax + 22, self.height() / 2), QPointF(ax + 17, self.height() / 2 - 5),
               QPointF(ax + 17, self.height() / 2 + 5)]
        p.drawPolygon(tip)
        kx = ax + 32
        r = QRectF(kx, 1, 32, 32)
        p.setPen(QPen(T("line"), 1))
        p.setBrush(T("line"))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(T("tile2"))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -3), 5, 5)
        p.setPen(T("ink"))
        p.setFont(theme.font(18, 500))
        p.drawText(r.adjusted(0, 0, 0, -2), Qt.AlignCenter, self.ch)


class CmdPage(QWidget):
    title = "語音指令"
    subtitle = "一句一條規則。點說法可以直接改"

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self.rows: list[dict] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.banner = Banner()
        self.banner.hide()
        v.addWidget(self.banner)
        self.banner_gap = QWidget()
        self.banner_gap.setFixedHeight(12)
        self.banner_gap.hide()
        v.addWidget(self.banner_gap)
        self.book, _ = card(margins=(0, 0, 0, 0), spacing=0)
        self.book_layout = self.book.layout()
        v.addWidget(self.book)
        v.addSpacing(20)
        v.addWidget(label("其他說法", sh=True))
        v.addSpacing(10)
        mods = QGridLayout()
        mods.setSpacing(12)
        mods.setColumnStretch(0, 7)   # room for the keycaps on one row (2026-10-22, the user's request)
        mods.setColumnStretch(1, 3)
        self.punct_card, c = card(spacing=8)
        self.punct = Switch(name="說標點的名字")
        self.punct.toggled.connect(self._punct)
        c.addLayout(hbox(label("說標點的名字", h3=True), Info(
            "整句只有這個名字才算，例如「逗號很重要」照常輸入"), None, self.punct, spacing=6))
        c.addWidget(dim("單獨說出名字就打出符號；有選取時取代選取"))
        self.keys = QWidget()
        g = QGridLayout(self.keys)
        g.setContentsMargins(0, 4, 0, 0)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(6)
        # one row of keycaps, each with its names under it (the keycap alone holds the mark)
        for i, (glyph, name) in enumerate(PUNCTS):
            g.addWidget(Keycap(glyph, size=(0, 42), glyph_px=20), 0, i)
            names = dim(name)
            names.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            g.addWidget(names, 1, i)
        c.addWidget(self.keys)
        mods.addWidget(self.punct_card, 0, 0)
        self.desc_card, c = card(spacing=8)
        self.desc = Switch(name="說詞的字打單字")
        self.desc.toggled.connect(self._desc)
        c.addLayout(hbox(label("說「詞的字」打單字", h3=True), Info(
            "整句剛好是「詞＋的＋字」，而且「的」前面整段就是一個字典裡的詞才算（「這個字是教育的育」不算）；輸入的是詞裡"
            "讀音相同的那個字"), None, self.desc, spacing=6))
        c.addWidget(dim("用一個詞指定是哪個同音字"))
        self.examples = QWidget()
        ev = QVBoxLayout(self.examples)
        ev.setContentsMargins(0, 4, 0, 0)
        ev.setSpacing(8)
        ev.addWidget(Example("節日", "節"))
        ev.addWidget(Example("顯示", "示"))
        c.addWidget(self.examples)
        c.addStretch(1)
        mods.addWidget(self.desc_card, 0, 1)
        v.addLayout(mods)
        v.addStretch(1)

    # --- values ---
    def load(self):
        """Rows from cfg.rules: one per action, phrases with the same action share it (復原、撤銷)."""
        self.rows = []
        for r in self.cfg.rules:
            if not (r.enabled and rules.spoken_ok(r)):
                continue
            st = r.steps[0]
            k = _key(st.type, st.value)
            row = next((o for o in self.rows if _key(o["type"], o["value"]) == k), None)
            if row is None:
                self.rows.append({"phrases": rules.phrases(r.phrase), "type": st.type,
                                  "value": list(st.value) if isinstance(st.value, (list, tuple)) else st.value,
                                  "builtin": k in BUILT})
            else:
                row["phrases"] += rules.phrases(r.phrase)
        for k in BUILT:   # a built-in turned off (no phrase) stays listed
            if not any(_key(o["type"], o["value"]) == k for o in self.rows):
                self.rows.append({"phrases": [], "type": k[0], "value": list(k[1]) if isinstance(k[1], tuple)
                                  else k[1], "builtin": True})
        order = list(BUILT)
        self.rows.sort(key=lambda o: order.index(_key(o["type"], o["value"])) if o["builtin"] else len(order))
        self.punct.set_quiet(self.cfg.punctuation_names)
        self.desc.set_quiet(self.cfg.describe_char)
        self._draw()

    def summary(self) -> str:
        return "說「換行」「送出」「復原」就執行，也能自訂"

    def restyle(self):
        self._draw()

    # --- drawing ---
    def _dups(self) -> set:
        count = {}
        for row in self.rows:
            for ph in row["phrases"]:
                n = rules.normalize(ph)
                if n:
                    count[n] = count.get(n, 0) + 1
        # a punctuation name is no clash: a row with that phrase runs instead (2026-10-22, the user's choice)
        return {n for n, c in count.items() if c > 1}

    def _draw(self, new_row: dict | None = None):
        _hold(self)   # the half-built table flashed
        lay = self.book_layout
        while lay.count():
            item = lay.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
            elif item.layout() is not None:
                _clear(item.layout())
        grid = QGridLayout()
        grid.setSpacing(0)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        bad = self._bad = self._dups()
        line, first = 0, True
        new_chips = None
        for gi, (name, hint) in enumerate(GROUPS):
            rows = [r for r in self.rows if (BUILT[_key(r["type"], r["value"])][0] if r["builtin"] else CUSTOM) == gi]
            if not rows and gi != 4:
                continue
            count = f"{len(rows)} 句" if rows else ""   # 自訂 empty: no count (還沒有 crowded its cell, 2026-10-22)
            span = len(rows) + (1 if gi == CUSTOM else 0)
            grid.addWidget(GroupLabel(name, hint, count, first), line, 0, span, 1)
            for i, row in enumerate(rows):
                w = RuleRow(row, bad, self.cfg.stop_on_enter)
                w.setProperty("first", first and i == 0)
                self._hook(w)
                grid.addWidget(w, line + i, 1)
                if row is new_row:
                    new_chips = w.chips
            if gi == CUSTOM:
                wrap = QWidget()
                wl = QVBoxLayout(wrap)
                wl.setContentsMargins(18, 10, 18, 14)
                add = AddBig()
                add.clicked.connect(self._add)
                wl.addWidget(add)
                wrap.paintEvent = lambda e, w=wrap: QPainter(w).fillRect(0, 0, w.width(), 1, T("line"))
                grid.addWidget(wrap, line + len(rows), 1)
            line += span
            first = False
        lay.addLayout(grid)
        self._grid = grid
        dups = sorted(bad & {rules.normalize(p) for r in self.rows for p in r["phrases"]})
        text = f"「{dups[0]}」同時是兩個指令的說法，說出來只會執行其中一個，請改掉一個。" if dups else ""
        self.banner.set(text)
        self.banner_gap.setVisible(bool(text))
        _opacity(self.keys, 1.0 if self.cfg.punctuation_names else 0.35)
        _opacity(self.examples, 1.0 if self.cfg.describe_char else 0.35)
        if new_chips is not None:
            QTimer.singleShot(0, new_chips.start_new)

    # --- changes ---
    def _save(self):
        out = []
        for row in self.rows:
            if row["type"] is None:
                continue
            for phrase in row["phrases"] or [""]:
                value = list(row["value"]) if isinstance(row["value"], list) else row["value"]
                out.append(Rule(rules.SPEECH, phrase=phrase, steps=[Step(row["type"], value)]))
        self.cfg.rules = out
        self.win.save()

    def _hook(self, w):
        w.changed.connect(lambda w=w: self._changed(w))
        w.removed.connect(lambda r=w.row: self._remove(r))

    def _changed(self, w):
        """A row changed: saved; the table is drawn again only when a phrase clash appears or goes, a row whose kind
        of action changed is replaced alone, anything else already shows (redrawing flashed, 2026-10-21)."""
        self._save()
        if self._dups() != self._bad:
            QTimer.singleShot(0, self._draw)
        elif w.rebuild:
            QTimer.singleShot(0, lambda: self._replace(w))

    def _replace(self, w):
        if self._grid.indexOf(w) < 0:
            return
        new = RuleRow(w.row, self._bad, self.cfg.stop_on_enter)
        new.setProperty("first", w.property("first"))
        self._hook(new)
        new.setParent(w.parentWidget())
        new.setGeometry(w.geometry())
        self._grid.replaceWidget(w, new)
        new.show()
        w.hide()
        w.deleteLater()

    def _remove(self, row):
        self.rows.remove(row)
        self._save()
        QTimer.singleShot(0, self._draw)

    def _add(self):
        row = {"phrases": [], "type": None, "value": "", "builtin": False}
        self.rows.append(row)
        self._draw(new_row=row)

    def _punct(self, on: bool):
        self.cfg.punctuation_names = on
        self.win.save()
        if self._dups() != getattr(self, "_bad", None):   # a punctuation name now clashes with a phrase, or no longer does
            self._draw()
        else:
            _opacity(self.keys, 1.0 if on else 0.35)

    def _desc(self, on: bool):
        self.cfg.describe_char = on
        self.win.save()
        _opacity(self.examples, 1.0 if on else 0.35)


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())

