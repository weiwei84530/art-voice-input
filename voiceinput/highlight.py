"""The draft marked (2026-10-16, the user's request; always on since the same evening, its color on the 外觀 tab):
while listening, the text typed but not committed yet gets a translucent box drawn over it, so what may still change
is told apart from what is settled. Highlighter yellow by default: in selection blue the user took a draft for a
selection and spoke again to replace it, and the speech went after it. Nothing in the document is selected: click-through windows on
top are drawn at the UI Automation rectangles of the text before the caret (dev/highlight_spike.py measured them
exact in Chrome's textarea and contenteditable boxes, 0.2-6ms per read, and in Windows Terminal). In a terminal the
rows of Claude Code's input box are walked back from the cursor (the borders and the padding at a row's end are not
part of the text); elsewhere the characters before the caret. When the text there is not the draft (the caret moved,
an app that does not report it) nothing is drawn.
"""
import logging

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from . import selection

log = logging.getLogger("voiceinput")

# the 外觀 tab's colors (#AARRGGBB): highlighter yellow first (the default), selection blue last
COLORS = [("#78FFE45C", "螢光黃"), ("#6E7CE08A", "淡綠"), ("#64FF8FC8", "粉紅"), ("#6EFFB35C", "淡橘"),
          ("#5A3390FF", "選取藍")]
_ROWS_BACK = 12         # input box rows walked back from a terminal's cursor


def _logical(x: int, y: int):
    """(top-left in logical pixels, device pixel ratio) of a physical screen point."""
    for s in QGuiApplication.screens():
        g, r = s.geometry(), s.devicePixelRatio()
        if g.x() <= x < g.x() + g.width() * r and g.y() <= y < g.y() + g.height() * r:
            return QPoint(g.x() + int((x - g.x()) / r), g.y() + int((y - g.y()) / r)), r
    return QPoint(x, y), 1.0


class _Mark(QWidget):
    def __init__(self, color: QColor):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.color = color

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), self.color)
        p.end()


class DraftMarks:
    """Main thread: the boxes on screen."""

    def __init__(self, color: str):
        self._marks: list[_Mark] = []
        self._shown = ()
        self._color = QColor(COLORS[0][0])
        self.set_color(color)

    def set_color(self, color: str):
        c = QColor(color)
        self._color = c if c.isValid() else QColor(COLORS[0][0])
        for m in self._marks:
            m.color = self._color
            m.update()

    def show(self, rects):
        rects = tuple(tuple(int(v) for v in r) for r in rects)
        if rects == self._shown:
            return
        self._shown = rects
        while len(self._marks) < len(rects):
            self._marks.append(_Mark(self._color))
        for m, (x, y, w, h) in zip(self._marks, rects):
            p, ratio = _logical(x, y)
            m.setGeometry(QRect(p.x(), p.y(), max(1, round(w / ratio)), max(1, round(h / ratio))))
            m.show()
        for m in self._marks[len(rects):]:
            m.hide()

    def visible(self) -> bool:
        return bool(self._shown)

    def hide(self):
        if self._shown:
            self._shown = ()
            for m in self._marks:
                m.hide()


def _flat(text: str) -> str:
    return "".join(text.split())


def draft_rects(text: str) -> list | None:
    """Any thread: screen rectangles of text right before the caret of the focused control, or None when the text
    there is not text (or cannot be read)."""
    try:
        uia, U = selection._uia()
        el = uia.GetFocusedElement()
        pattern = el.GetCurrentPattern(U.UIA_TextPatternId)
        if not pattern:
            return None
        pattern = pattern.QueryInterface(U.IUIAutomationTextPattern)
        if selection._proc_name(el.CurrentProcessId) in selection._TERMINALS or el.CurrentClassName == "TermControl":
            return _term_rects(pattern, U, text)
        ranges = pattern.GetSelection()
        if ranges.Length != 1:
            return None
        r = ranges.GetElement(0).Clone()
        if r.GetText(-1):
            return None                       # text is selected: no draft at a caret
        r.MoveEndpointByUnit(U.TextPatternRangeEndpoint_Start, U.TextUnit_Character, -len(text.replace("\r", "")))
        if _flat(r.GetText(-1)) != _flat(text):
            return None
        flat = list(r.GetBoundingRectangles() or [])
        return [tuple(flat[i:i + 4]) for i in range(0, len(flat), 4) if flat[i + 2] > 0]
    except Exception:
        log.debug("highlight: reading the draft's place failed", exc_info=True)
        return None


def _term_rects(pattern, U, text: str) -> list | None:
    """Windows Terminal: the input box rows from the cursor back, each from the box's text start to its right
    border, until they hold the draft (spaces ignored: a row's end is padding)."""
    cursor = selection._term_cursor(pattern)
    if cursor is None:
        return None
    line, col = cursor
    row = line.GetText(-1).rstrip("\r\n")
    start = selection.term_watcher._input_start(row, line, col, cursor)
    if start is None:
        return None
    need = _flat(text)
    got, rects, end = "", [], col
    for _ in range(_ROWS_BACK):
        right = min((i for i in (row.find("│", start), row.find("┃", start)) if i >= 0), default=len(row))
        part = row[start:min(end, right)].rstrip()
        b = start + len(part)
        if part.strip():
            # the row's part of the draft: from where the rest of it starts to the end of the text on the row
            take = need[:len(need) - len(got)]
            a = b
            count = 0
            while a > start and count < len(take):
                a -= 1
                if not row[a].isspace():
                    count += 1
            got = _flat(row[a:b]) + got
            first, last = selection._char_rect(line, a), selection._char_rect(line, b - 1)
            right = last[0] + last[2]
            if b < len(row):
                # Windows Terminal reports a wide character 3 cells wide (it takes 2): the next cell's left edge is
                # where it ends (the user saw half a character too much in Claude Code, 2026-10-16)
                nxt = selection._char_rect(line, b)
                if nxt[1] == first[1] and nxt[0] > last[0]:
                    right = nxt[0]
            rects.append((first[0], first[1], right - first[0], first[3]))
        if len(got) >= len(need):
            break
        line = line.Clone()
        if line.Move(U.TextUnit_Line, -1) != -1:
            return None
        row = line.GetText(-1).rstrip("\r\n")
        end = len(row)
    return rects if got == need else None
