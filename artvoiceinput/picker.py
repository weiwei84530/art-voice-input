"""The 選字 menu: a small window that does not take focus, so the target app keeps its caret and selection.

Design G3 (2026-10-20, the user's pick of the redesign's menus): the candidates as a plain list, the tabs (by how close
they sound: 同音 / 不同聲調 / 模糊音 for Chinese, 近音字 / 詞庫 / 大小寫 for English) in a row along the bottom with
their counts, the open one marked by an orange bar on top. The tabs stay at the bottom even when the menu opens above
the selection (they flipped to the top before). The pointer over a tab opens it. Candidates fill a grid top to bottom,
then left to right: 4 columns for a single character, 2 for words; the word that is there now (the first of the first
tab) is bold with an orange mark. Light or dark with the settings window (config.theme, ui/theme.py). Rows are answered
with the mouse only (decided 2026-09-29: short spoken answers like 對 / 第二個 were often misheard). There is no
timeout: the app closes the menu when the user's next click or key is somewhere else.
"""
import ctypes

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .ui import theme as themes

_GWL_EXSTYLE, _WS_EX_NOACTIVATE, _WS_EX_TOPMOST = -20, 0x08000000, 0x8
SINGLE = (4, 4)   # columns, rows per tab for one Chinese character
WORDS = (2, 5)    # for words and English
_SHADOW = 12      # room around the menu for its shadow
_PAD = 6          # inside the menu, around the candidates
_CELL_SINGLE = (46, 38)
_CELL_WORD = (104, 34)
_WORD_MAX = 220   # a long English candidate widens its column up to this
_BAR = 40         # the row of tabs


class Picker(QWidget):
    picked = Signal(str)      # the word clicked
    closed = Signal()         # hidden without a pick

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.theme = None           # ui.theme.Theme, shared with the settings window (use_theme)
        self.tabs: list[tuple[str, list[str]]] = []
        self.current = 0
        self.single = False
        self.message = ""           # shown instead of candidates: … while loading, 沒有候選字
        self._anchor = None         # (top-left, bottom y) of the selection the menu belongs to, logical pixels
        self._answered = False
        self._hover = None          # ("cell", i) or ("tab", i)
        self._cells: list[QRectF] = []
        self._tab_rects: list[QRectF] = []
        self._box = QRectF()

    # --- public API ---
    def use_theme(self, theme):
        self.theme = theme
        theme.changed.connect(self.update)

    @property
    def candidates(self) -> list[str]:
        """Every candidate, tab after tab."""
        return [w for _, words in self.tabs for w in words]

    def show_loading(self, word: str, rect):
        self._answered = False
        self._fill([], single=False, message="…")
        self._place(rect)

    def show_candidates(self, word: str, tabs: list[tuple[str, list[str]]]):
        """tabs: (name, words) with words, in order; the first is opened."""
        self._fill(tabs, single=len(word) == 1 and not word.isascii(), message="沒有候選字")
        if self.isVisible():
            QTimer.singleShot(0, self._clamp)

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
            self.update()

    # --- layout ---
    def _fill(self, tabs, single: bool, message: str):
        self.tabs = [(name, words[:(SINGLE if single else WORDS)[0] * (SINGLE if single else WORDS)[1]])
                     for name, words in tabs]
        self.current, self.single, self.message = 0, single, message
        self._hover = None
        self._layout()
        self.update()

    def _layout(self):
        cols, rows = SINGLE if self.single else WORDS
        cw, ch = _CELL_SINGLE if self.single else _CELL_WORD
        if not self.single and self.tabs:
            f = themes.font(15.5, 500)
            fm = QFontMetrics(f)
            longest = max((fm.horizontalAdvance(w) for _, ws in self.tabs for w in ws), default=0)
            cw = min(max(cw, longest + 28), _WORD_MAX)
        if self.tabs:
            width = cols * cw + 2 * _PAD
            fm_tabs = themes.font(12.5, 700)
            tab_need = sum(QFontMetrics(fm_tabs).horizontalAdvance(f"{n} {len(ws)}") + 22 for n, ws in self.tabs)
            width = max(width, tab_need + 2 * _PAD)
            height = rows * ch + 2 * _PAD + _BAR
        else:
            width, height = 140, 44
        self._box = QRectF(_SHADOW, _SHADOW - 4, width, height)
        self.setFixedSize(round(width + 2 * _SHADOW), round(height + 2 * _SHADOW))
        x0, y0 = self._box.x() + _PAD, self._box.y() + _PAD
        self._cells = [QRectF(x0 + (n // rows) * cw, y0 + (n % rows) * ch, cw, ch) for n in range(cols * rows)]
        self._tab_rects = []
        if self.tabs:
            bar_y = self._box.bottom() - _BAR + 5
            tw = (width - 12) / len(self.tabs)
            self._tab_rects = [QRectF(self._box.x() + 6 + i * tw + 1, bar_y, tw - 2, _BAR - 11)
                               for i in range(len(self.tabs))]

    # --- painting ---
    def _c(self, key: str) -> QColor:
        if self.theme is None:
            return themes.qcolor(themes.LIGHT[key])
        return self.theme.color(key)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = self._box
        dark = self.theme is not None and self.theme["dark"]
        for i in range(_SHADOW, 0, -2):   # a soft shadow, darker under the menu
            a = (34 if dark else 16) * (1 - i / _SHADOW) ** 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, round(a)))
            p.drawRoundedRect(box.adjusted(-i / 2, -i / 2 + 4, i / 2, i / 2 + 6), 8 + i / 2, 8 + i / 2)
        path = QPainterPath()
        path.addRoundedRect(box, 8, 8)
        p.fillPath(path, self._c("tile"))
        p.save()
        p.setClipPath(path)
        if not self.tabs:
            p.setPen(self._c("muted"))
            p.setFont(themes.font(13))
            p.drawText(box, Qt.AlignCenter, self.message)
        else:
            self._paint_cells(p)
            self._paint_tabs(p)
        p.restore()
        p.setPen(QPen(self._c("line"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

    def _paint_cells(self, p):
        words = self.tabs[self.current][1]
        if not words:
            p.setPen(self._c("muted"))
            p.setFont(themes.font(13))
            area = QRectF(self._box.x(), self._box.y(), self._box.width(), self._box.height() - _BAR)
            p.drawText(area, Qt.AlignCenter, "沒有候選字")
            return
        for i, word in enumerate(words):
            r = self._cells[i]
            hot = self._hover == ("cell", i)
            first = self.current == 0 and i == 0
            if hot:
                p.setPen(Qt.NoPen)
                p.setBrush(self._c("accbg"))
                p.drawRoundedRect(r, 5, 5)
            if first:
                p.setPen(Qt.NoPen)
                p.setBrush(self._c("acc"))
                if self.single:
                    p.drawRoundedRect(QRectF(r.x() + 12, r.bottom() - 6, r.width() - 24, 2), 1, 1)
                else:
                    p.drawRoundedRect(QRectF(r.x() + 3, r.y() + 10, 3, r.height() - 20), 1.5, 1.5)
            p.setPen(self._c("acct") if hot else self._c("ink"))
            p.setFont(themes.font(19 if self.single else 15.5, 700 if first else 500))
            if self.single:
                p.drawText(r, Qt.AlignCenter, word)
            else:
                fm = p.fontMetrics()
                p.drawText(r.adjusted(12, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter,
                           fm.elidedText(word, Qt.ElideRight, int(r.width() - 18)))

    def _paint_tabs(self, p):
        box = self._box
        bar = QRectF(box.x(), box.bottom() - _BAR, box.width(), _BAR)
        p.fillRect(bar, self._c("tile2"))
        p.fillRect(QRectF(bar.x(), bar.y(), bar.width(), 1), self._c("line"))
        for i, ((name, words), r) in enumerate(zip(self.tabs, self._tab_rects)):
            on = i == self.current
            if on:
                p.setPen(Qt.NoPen)
                p.setBrush(self._c("tile"))
                p.drawRoundedRect(r, 5, 5)
                p.setBrush(self._c("acc"))
                p.drawRoundedRect(QRectF(r.x() + 10, r.y(), r.width() - 20, 3), 1.5, 1.5)
            name_font = themes.font(12.5, 700 if on else 500)
            num_font = themes.font(11, 600, num=True)
            p.setFont(name_font)
            nw = p.fontMetrics().horizontalAdvance(name)
            p.setFont(num_font)
            count = str(len(words))
            cw = p.fontMetrics().horizontalAdvance(count)
            x = r.center().x() - (nw + 5 + cw) / 2
            p.setFont(name_font)
            p.setPen(self._c("ink") if on else self._c("muted"))
            p.drawText(QRectF(x, r.y(), nw + 2, r.height()), Qt.AlignLeft | Qt.AlignVCenter, name)
            p.setFont(num_font)
            p.setPen(self._c("acct") if on else self._c("muted"))
            p.drawText(QRectF(x + nw + 5, r.y() + 1, cw + 2, r.height()), Qt.AlignLeft | Qt.AlignVCenter, count)

    # --- the mouse ---
    def _hit(self, pos):
        for i, r in enumerate(self._tab_rects):
            if r.contains(pos):
                return "tab", i
        if self.tabs:
            for i in range(len(self.tabs[self.current][1])):
                if self._cells[i].contains(pos):
                    return "cell", i
        return None

    def mouseMoveEvent(self, e):
        hit = self._hit(e.position())
        if hit and hit[0] == "tab":
            self.open_tab(hit[1])
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.PointingHandCursor if hit and hit[0] == "cell" else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        hit = self._hit(e.position())
        if hit and hit[0] == "cell":
            self.pick(self.tabs[self.current][1][hit[1]])

    # --- placing ---
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
        self.move(pos - QPoint(_SHADOW, _SHADOW - 4))
        self._no_activate()
        self.show()
        self._no_activate()
        self._clamp()

    @staticmethod
    def _to_logical(p: QPoint) -> QPoint:
        # Qt keeps each screen's origin in device pixels and scales only within the screen
        for s in QGuiApplication.screens():
            g, r = s.geometry(), s.devicePixelRatio()
            if g.x() <= p.x() < g.x() + g.width() * r and g.y() <= p.y() < g.y() + g.height() * r:
                return QPoint(g.x() + int((p.x() - g.x()) / r), g.y() + int((p.y() - g.y()) / r))
        return p

    def _clamp(self):
        """Keep the menu on screen. Under a selection too close to the bottom it opens above it instead, like an
        IME candidate window (the tabs stay at the bottom)."""
        anchor = self._anchor
        screen = QGuiApplication.screenAt(anchor[0] if anchor else self.pos()) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        top_gap, bottom_gap = round(self._box.y()), round(self.height() - self._box.bottom())
        y = self.y()
        if anchor:
            y = anchor[1] + 6 - top_gap
            if y + self.height() - bottom_gap > a.bottom():
                y = anchor[0].y() - 6 - round(self._box.bottom())
        x = min(max(self.x(), a.left() - _SHADOW), a.right() - self.width() + _SHADOW)
        y = min(max(y, a.top() - top_gap), a.bottom() - self.height() + bottom_gap)
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
