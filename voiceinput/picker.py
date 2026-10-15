"""The 選字 menu: a small dark window that does not take focus, so the target app keeps its caret and selection.

Redesigned 2026-10-16 (the user's design): no input box (words are added on the 詞庫 tab instead), the candidates
in tabs, by how close they sound: 同音 / 不同聲調 / 模糊音 for Chinese, 近音字 / 詞庫 / 大小寫 for English. The pointer
over a tab opens it. The tabs sit on the side away from the selection (under the menu when it opens below the
selection, on top when it opens above it), so the pointer coming from the selection reaches the candidates first.
Candidates fill a grid top to bottom, then left to right: 4 columns for a single character, 2 for words. Rows are
answered with the mouse only (decided 2026-09-29: short spoken answers like 對 / 第二個 were often misheard). There
is no timeout: the app closes the menu when the user's next click or key is somewhere else.
"""
import ctypes

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

_STYLE = """
QWidget#picker { background: #202024; border: 1px solid #3a3a40; border-radius: 8px; }
QPushButton { color: #f2f2f2; background: transparent; border: none; border-radius: 5px;
              padding: 4px 10px; text-align: left; font-size: 15px; }
QPushButton:hover { background: #3a3a44; }
QLabel#tab { color: #9a9aa4; padding: 3px 8px; font-size: 12px; border-radius: 5px; }
QLabel#tab[current="true"] { color: #f2f2f2; background: #34343c; }
QLabel#empty { color: #8a8a94; padding: 6px 10px; font-size: 13px; }
"""
_GWL_EXSTYLE, _WS_EX_NOACTIVATE, _WS_EX_TOPMOST = -20, 0x08000000, 0x8
SINGLE = (4, 4)   # columns, rows per tab for one Chinese character
WORDS = (2, 5)    # for words and English


class _Tab(QLabel):
    def __init__(self, text, on_hover):
        super().__init__(text, objectName="tab")
        self._on_hover = on_hover

    def enterEvent(self, e):
        self._on_hover()
        super().enterEvent(e)


class Picker(QWidget):
    picked = Signal(str)      # the word clicked
    closed = Signal()         # hidden without a pick

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.tabs: list[tuple[str, list[str]]] = []
        self.current = 0
        self._anchor = None         # (top-left, bottom y) of the selection the menu belongs to, logical pixels
        self._above = False         # opened above the selection (tabs on top)
        self._answered = False
        self._tab_labels: list[_Tab] = []

        self.frame = QWidget(self, objectName="picker")
        self.frame.setAttribute(Qt.WA_StyledBackground)
        self.frame.setStyleSheet(_STYLE)
        self.tab_row = QWidget()
        self.tab_layout = QHBoxLayout(self.tab_row)
        self.tab_layout.setContentsMargins(0, 0, 0, 0)
        self.tab_layout.setSpacing(2)
        self.pages = QStackedWidget()
        self.inner = QVBoxLayout(self.frame)
        self.inner.setContentsMargins(6, 6, 6, 6)
        self.inner.setSpacing(4)
        self.inner.addWidget(self.pages)
        self.inner.addWidget(self.tab_row)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.frame)

    # --- public API ---
    @property
    def candidates(self) -> list[str]:
        """Every candidate, tab after tab."""
        return [w for _, words in self.tabs for w in words]

    def show_loading(self, word: str, rect):
        self._answered = False
        self._fill([], single=False, loading=True)
        self._place(rect)

    def show_candidates(self, word: str, tabs: list[tuple[str, list[str]]]):
        """tabs: (name, words) with words, in order; the first is opened."""
        self._fill(tabs, single=len(word) == 1 and not word.isascii())
        if self.isVisible():
            QTimer.singleShot(0, self._refit)

    def owns(self, hwnd: int) -> bool:
        return bool(hwnd) and ctypes.windll.user32.GetAncestor(hwnd, 2) == int(self.winId())   # GA_ROOT

    def dismiss(self):
        if self.isVisible():
            self.hide()

    def pick(self, word: str):
        self._answered = True
        self.hide()
        self.picked.emit(word)

    def open_tab(self, i: int):
        if 0 <= i < len(self.tabs) and i != self.current:
            self.current = i
            self.pages.setCurrentIndex(i)
            self._style_tabs()

    # --- internals ---
    def _style_tabs(self):
        for i, t in enumerate(self._tab_labels):
            t.setProperty("current", i == self.current)
            t.style().unpolish(t)
            t.style().polish(t)

    def _clear(self):
        while self.pages.count():
            w = self.pages.widget(0)
            self.pages.removeWidget(w)
            w.hide()               # removed now, not at deleteLater: the old rows kept the window large
            w.setParent(None)
            w.deleteLater()
        while self.tab_layout.count():
            w = self.tab_layout.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._tab_labels = []

    def _fill(self, tabs, single: bool, loading: bool = False):
        self._clear()
        self.tabs, self.current = tabs, 0
        if not tabs:
            page = QLabel("…" if loading else "沒有候選字", objectName="empty")
            self.pages.addWidget(page)
            self.tab_row.hide()
            self._shrink()
            return
        cols, rows = SINGLE if single else WORDS
        for i, (name, words) in enumerate(tabs):
            page = QWidget()
            grid = QGridLayout(page)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(0)
            for n, word in enumerate(words[:cols * rows]):
                grid.addWidget(QPushButton(word, clicked=lambda _=False, w=word: self.pick(w)), n % rows, n // rows)
            grid.setRowStretch(rows, 1)
            self.pages.addWidget(page)
            tab = _Tab(name, lambda i=i: self.open_tab(i))
            self.tab_layout.addWidget(tab)
            self._tab_labels.append(tab)
        self.tab_layout.addStretch(1)
        self.tab_row.show()
        self.pages.setCurrentIndex(0)
        self._style_tabs()
        self._shrink()

    def _refit(self):
        """Rows added to a visible window are shown, and sized, on the next event loop pass."""
        if self.isVisible():
            self._shrink()
            self._clamp()

    def _shrink(self):
        self.frame.layout().activate()
        self.layout().activate()
        self.resize(self.sizeHint())

    def _place(self, rect):
        """rect: selection bounds in physical screen pixels (x, y, w, h) from UI Automation, or None (then next
        to the mouse)."""
        self._anchor = None
        if rect:
            x, y, w, h = rect
            top = self._to_logical(QPoint(int(x), int(y)))
            self._anchor = (top, self._to_logical(QPoint(int(x), int(y + h))).y())
            pos = QPoint(top.x(), self._anchor[1] + 6)
        else:
            pos = QCursor.pos() + QPoint(0, 6)
        self.move(pos)
        self._no_activate()
        self.show()
        self._no_activate()
        self._clamp()
        QTimer.singleShot(0, self._refit)   # rows added while an earlier menu was still open are sized later

    @staticmethod
    def _to_logical(p: QPoint) -> QPoint:
        # Qt keeps each screen's origin in device pixels and scales only within the screen
        for s in QGuiApplication.screens():
            g, r = s.geometry(), s.devicePixelRatio()
            if g.x() <= p.x() < g.x() + g.width() * r and g.y() <= p.y() < g.y() + g.height() * r:
                return QPoint(g.x() + int((p.x() - g.x()) / r), g.y() + int((p.y() - g.y()) / r))
        return p

    def _set_above(self, above: bool):
        """The tabs go on the side away from the selection."""
        if above == self._above:
            return
        self._above = above
        self.inner.removeWidget(self.tab_row)
        self.inner.insertWidget(0 if above else 1, self.tab_row)

    def _clamp(self):
        """Keep the menu on screen. Under a selection too close to the bottom it opens above it instead, like an
        IME candidate window."""
        anchor = self._anchor
        screen = QGuiApplication.screenAt(anchor[0] if anchor else self.pos()) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        y = self.y()
        above = False
        if anchor:
            y = anchor[1] + 6
            if y + self.height() > a.bottom():
                y = anchor[0].y() - 6 - self.height()
                above = True
        self._set_above(above)
        x = min(max(self.x(), a.left()), a.right() - self.width())
        y = min(max(y, a.top()), a.bottom() - self.height())
        self.move(x, y)

    def _no_activate(self):
        hwnd = int(self.winId())
        user32 = ctypes.windll.user32
        user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
                              | _WS_EX_NOACTIVATE | _WS_EX_TOPMOST)

    def hideEvent(self, e):
        if not self._answered:
            self._answered = True
            self.closed.emit()
        super().hideEvent(e)
