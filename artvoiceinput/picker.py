"""The 選字 menu: a small window that does not take focus, so the target app keeps its caret and selection.

Design G2 (2026-10-20, the user's pick of the redesign's menus, made compact): the candidates as a plain list, the
tabs (by how close they sound: 同音 / 不同聲調 / 模糊音 for Chinese, 近音字 / 詞庫 / 大小寫 for English) in a rail on
the right, each a name over its count, the open one marked by an orange bar on its left. The pointer over a tab opens
it. Candidates fill a grid top to bottom, then left to right: 3 columns of 5 for a single character (in about the
words' size), 2 of 5 for words. The word that is there now leads the first tab, bold with an orange mark, so the user
sees what is chosen (a click on it keeps it); tab counts leave it out. Light or dark with the settings window
(config.theme, ui/theme.py). Rows are answered with the mouse only (decided 2026-09-29: short spoken answers like
對 / 第二個 were often misheard). There is no timeout: the app closes the menu when the user's next click or key is
somewhere else.

The same menu is the symbol keyboard (2026-10-22, design A of https://claude.ai/artifact/FSX49ZChyWMdwvv5i8kPcG, the
user's pick): said 符號 or 鍵盤, it opens under the caret with SYMBOLS' tabs (全形, 半形, 小寫, 大寫), no word leading the first; a click types
the symbol, a pair (PAIRS) with the caret put back between, and closes it.
"""
import ctypes

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .ui import theme as themes

_GWL_EXSTYLE, _WS_EX_NOACTIVATE, _WS_EX_TOPMOST = -20, 0x08000000, 0x8
SINGLE = (3, 5)   # columns, rows per tab for one Chinese character (the user's choice: 15, rows like words')
WORDS = (2, 5)    # for words and English
_SHADOW = 12      # room around the menu for its shadow
_PAD = 5          # inside the menu, around the candidates
_CELL_SINGLE = (42, 28)
_CELL_WORD = (88, 28)
_FONT_SINGLE, _FONT_WORD = 15, 14
_WORD_MAX = 200   # a long English candidate widens its column up to this
_RAIL_PAD = 5     # inside the rail of tabs
_TAB_H = 38       # a tab: its name over its count
_TAB_GAP = 4
_RAIL_MIN = 62
SYMBOL_GRID = (5, 6)   # columns, rows of the symbol keyboard, in the single characters' cells, filled top to bottom
# 全形: two columns of marks, then two of pairs; letters a-z for what speech spells badly (2026-10-22)
SYMBOLS = [("全形", ["，", "。", "、", "；", "：", "？", "！", "……", "——", "～", "·", "※",
                     "「」", "『』", "（）", "【】", "《》", "〈〉", "〔〕", "“”", "‘’", "［］"]),
           ("半形", ["@", "#", "$", "%", "&", "*", "_", "-", "+", "=", "/", "\\", "|", "<", ">", "~", "^", "`", "'",
                     '"', ":", ";", "!", "?", "()", "[]", "{}"]),
           ("小寫", [chr(c) for c in range(ord("a"), ord("z") + 1)]),
           ("大寫", [chr(c) for c in range(ord("A"), ord("Z") + 1)])]
PAIRS = {w for _, ws in SYMBOLS for w in ws if len(w) == 2 and w not in ("……", "——")}


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
        self.grid = SINGLE
        self.lead = True            # the first tab's first word is the one there now (選字; not the symbol keyboard)
        self.message = ""           # shown instead of candidates: … while loading, 沒有候選字
        self._anchor = None         # (top-left, bottom y) of the selection the menu belongs to, logical pixels
        self._answered = False
        self._hover = None          # ("cell", i) or ("tab", i)
        self._cells: list[QRectF] = []
        self._tab_rects: list[QRectF] = []
        self._box = QRectF()
        self._list = QRectF()       # the candidates' side and the rail of tabs
        self._rail = QRectF()

    # --- public API ---
    def use_theme(self, theme):
        self.theme = theme
        theme.changed.connect(self.update)

    @property
    def candidates(self) -> list[str]:
        """Every candidate, tab after tab (not the word that is there now)."""
        return [w for i, (_, words) in enumerate(self.tabs) for w in (words[1:] if i == 0 and self.lead else words)]

    def show_loading(self, word: str, rect):
        self._answered = False
        self.lead = True
        self._fill([], single=False, message="…")
        self._place(rect)

    def show_symbols(self, rect):
        """The symbol keyboard under rect (the caret, physical pixels), or by the mouse."""
        self._answered = False
        self.lead = False
        self._fill(SYMBOLS, single=True, message="", grid=SYMBOL_GRID)
        self._place(rect)

    def show_candidates(self, word: str, tabs: list[tuple[str, list[str]]]):
        """tabs: (name, words) with words, in order; the first is opened."""
        if tabs:
            tabs = [(tabs[0][0], [word] + tabs[0][1])] + list(tabs[1:])
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
    def _fill(self, tabs, single: bool, message: str, grid=None):
        self.grid = grid or (SINGLE if single else WORDS)
        self.tabs = [(name, words[:self.grid[0] * self.grid[1]]) for name, words in tabs]
        self.current, self.single, self.message = 0, single, message
        self._hover = None
        self._layout()
        self.update()

    def _layout(self):
        cols, rows = self.grid
        cw, ch = _CELL_SINGLE if self.single else _CELL_WORD
        if not self.single and self.tabs:
            fm = QFontMetrics(themes.font(_FONT_WORD, 500))
            longest = max((fm.horizontalAdvance(w) for _, ws in self.tabs for w in ws), default=0)
            cw = min(max(cw, longest + 24), _WORD_MAX)
        if self.tabs:
            # only as many columns as the fullest tab needs, so the menu stays the same size across tabs
            cols = max(1, min(cols, max(-(-len(ws) // rows) for _, ws in self.tabs)))
            list_w, list_h = cols * cw + 2 * _PAD, rows * ch + 2 * _PAD
            fm = QFontMetrics(themes.font(12, 700))
            rail_w = max(_RAIL_MIN, max(fm.horizontalAdvance(n) for n, _ in self.tabs) + 22 + 2 * _RAIL_PAD)
            rail_h = len(self.tabs) * (_TAB_H + _TAB_GAP) - _TAB_GAP + 2 * _RAIL_PAD
            width, height = list_w + rail_w, max(list_h, rail_h)
        else:
            list_w = rail_w = 0
            width, height = 120, 38
        self._box = QRectF(_SHADOW, _SHADOW - 4, width, height)
        self.setFixedSize(round(width + 2 * _SHADOW), round(height + 2 * _SHADOW))
        x0, y0 = self._box.x() + _PAD, self._box.y() + _PAD
        self._cells = [QRectF(x0 + (n // rows) * cw, y0 + (n % rows) * ch, cw, ch) for n in range(cols * rows)]
        self._list = QRectF(self._box.x(), self._box.y(), list_w, height)
        self._rail = QRectF(self._box.x() + list_w, self._box.y(), rail_w, height)
        self._tab_rects = [QRectF(self._rail.x() + _RAIL_PAD, self._rail.y() + _RAIL_PAD + i * (_TAB_H + _TAB_GAP),
                                  rail_w - 2 * _RAIL_PAD, _TAB_H) for i in range(len(self.tabs))]

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
            p.drawText(self._list, Qt.AlignCenter, "沒有候選字")
            return
        for i, word in enumerate(words):
            r = self._cells[i]
            hot = self._hover == ("cell", i)
            first = self.lead and self.current == 0 and i == 0
            if hot:
                p.setPen(Qt.NoPen)
                p.setBrush(self._c("accbg"))
                p.drawRoundedRect(r, 5, 5)
            if first:
                p.setPen(Qt.NoPen)
                p.setBrush(self._c("acc"))
                if self.single:
                    p.drawRoundedRect(QRectF(r.x() + 11, r.bottom() - 5, r.width() - 22, 2), 1, 1)
                else:
                    p.drawRoundedRect(QRectF(r.x() + 3, r.y() + 8, 3, r.height() - 16), 1.5, 1.5)
            p.setPen(self._c("acct") if hot else self._c("ink"))
            p.setFont(themes.font(_FONT_SINGLE if self.single else _FONT_WORD, 700 if first else 500))
            if self.single:
                p.drawText(r, Qt.AlignCenter, word)
            else:
                fm = p.fontMetrics()
                p.drawText(r.adjusted(11, 0, -5, 0), Qt.AlignLeft | Qt.AlignVCenter,
                           fm.elidedText(word, Qt.ElideRight, int(r.width() - 16)))

    def _paint_tabs(self, p):
        rail = self._rail
        p.fillRect(rail, self._c("tile2"))
        p.fillRect(QRectF(rail.x(), rail.y(), 1, rail.height()), self._c("line"))
        for i, ((name, words), r) in enumerate(zip(self.tabs, self._tab_rects)):
            on = i == self.current
            if on:
                p.setPen(Qt.NoPen)
                p.setBrush(self._c("tile"))
                p.drawRoundedRect(r, 5, 5)
                p.setBrush(self._c("acc"))
                p.drawRoundedRect(QRectF(r.x(), r.y() + 8, 3, r.height() - 16), 1.5, 1.5)
            p.setFont(themes.font(12, 700 if on else 500))
            p.setPen(self._c("ink") if on else self._c("muted"))
            p.drawText(QRectF(r.x() + 10, r.y() + 4, r.width() - 12, 16), Qt.AlignLeft | Qt.AlignVCenter, name)
            p.setFont(themes.font(10.5, 600, num=True))
            p.setPen(self._c("acct") if on else self._c("muted"))
            p.drawText(QRectF(r.x() + 10, r.y() + 20, r.width() - 12, 14), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{len(words) - (i == 0 and self.lead)} 個")

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
        IME candidate window."""
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
