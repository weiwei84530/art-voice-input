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

from .selection import draft_rects  # noqa: F401  (app.py imports it from here)

log = logging.getLogger("artvoiceinput")

# the 外觀 tab's colors (#AARRGGBB): highlighter yellow first (the default), selection blue last
COLORS = [("#78FFE45C", "螢光黃"), ("#6E7CE08A", "淡綠"), ("#64FF8FC8", "粉紅"), ("#6EFFB35C", "淡橘"),
          ("#5A3390FF", "選取藍")]


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
