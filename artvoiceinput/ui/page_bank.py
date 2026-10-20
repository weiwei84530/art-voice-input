"""詞庫 (design 1, the user's pick): four lists under segmented tabs with their counts, a search box and the list's
order: 詞包 to switch on, 詞庫列表 (each word's 優先度 as a bar from 少出現 to 多出現; words are typed in here), 選字記憶
(這個ying3片是 → 這個影片是) and 英文替換. Every change is saved at once."""
import os

from pypinyin import lazy_pinyin
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QVBoxLayout,
                               QWidget)

from .. import hotwords as hw
from .. import packs
from ..memory import BOUNDARY
from . import theme
from .kit import Choice, Switch, T, Tip, button, card, dim, draw_icon, icon, label

TABS = [("packs", "詞包", "勾選的詞包，裡面的詞會優先辨識；「編輯詞」用記事本打開，存檔後下次說話就生效"),
        ("words", "詞庫列表", "每個詞出現的機會：選字選到會提高，被換掉會降低；0% 不影響辨識"),
        ("picks", "選字記憶", "選過的單字：聽到同樣的讀音、前後字也一樣時自動換"),
        ("aliases", "英文替換", "聽到左邊的拼法，一律寫成右邊")]
SORTS = {"words": ("hotword_sort", [("weight", "優先度（高→低）"), ("name", "名稱 A→Z"), ("name_desc", "名稱 Z→A"),
                                    ("date", "日期（新→舊）"), ("date_old", "日期（舊→新）")]),
         "picks": ("pick_sort", [("date", "日期（新→舊）"), ("date_old", "日期（舊→新）"), ("reading", "讀音 A→Z"),
                                 ("reading_desc", "讀音 Z→A")]),
         "aliases": ("alias_sort", [("date", "日期（新→舊）"), ("date_old", "日期（舊→新）"), ("name", "名稱 A→Z"),
                                    ("name_desc", "名稱 Z→A")])}
SOURCES = {hw.MANUAL: "自己加的", hw.PICKED: "選字"}
_SHOWN = 6   # a pack's first terms shown


def _shown(pct: int) -> str:
    d = pct - hw.NEUTRAL
    return f"{d:+d}%" if d else "0%"


class Row(QWidget):
    """A line of a list: the line above it, a tint under the pointer."""

    def __init__(self, header: bool = False, tint: bool = False):
        super().__init__()
        self.header, self.tint = header, tint
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(18, 8 if header else 10, 12, 8 if header else 10)
        self.lay.setSpacing(14)
        self.setMinimumHeight(34 if header else 50)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if self.header or self.tint:
            p.fillRect(self.rect(), T("tile2"))
        elif self.underMouse():
            p.fillRect(self.rect(), T("tile2"))
        if self.property("first") is not True:
            p.fillRect(0, 0, self.width(), 1, T("line"))


class Bar(QWidget):
    """優先度 from −100% to +100% as a bar from the middle: orange up, gray down."""

    def __init__(self, pct: int):
        super().__init__()
        self.d = pct - hw.NEUTRAL
        self.setFixedHeight(16)
        self.setMinimumWidth(120)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - 8) / 2
        r = QRectF(0.5, y + 0.5, self.width() - 1, 7)
        p.setPen(QPen(T("line"), 1))
        p.setBrush(T("tile2"))
        p.drawRoundedRect(r, 4, 4)
        mid = self.width() / 2
        w = abs(self.d) / 100 * (self.width() / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(T("acc") if self.d > 0 else theme.qcolor("#8A9099"))
        if w:
            p.drawRoundedRect(QRectF(mid if self.d > 0 else mid - w, y, w, 8), 4, 4)
        c = T("muted")
        c.setAlphaF(0.5)
        p.fillRect(QRectF(mid - 0.75, y - 3, 1.5, 14), c)


def _x_button(slot, tip: str):
    b = button("", slot, ib=True)
    b.setIcon(icon("x", T("muted"), 14, 2.2))
    b.setToolTip(tip)
    return b


def _arrow():
    w = QWidget()
    w.setFixedSize(24, 16)

    def paint(_):
        p = QPainter(w)
        p.setRenderHint(QPainter.Antialiasing)
        draw_icon(p, "arrow", QRectF(4, 0, 16, 16), T("muted"), 2)
    w.paintEvent = paint
    return w


def _fixed(w, width: int):
    w.setFixedWidth(width)
    return w


class BankPage(QWidget):
    title = "詞庫"

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self.tab = self.cfg.hotword_section if self.cfg.hotword_section in dict((k, n) for k, n, _ in TABS) else "packs"
        self._stamp = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        self.tabs = Choice([(k, n) for k, n, _ in TABS], self.tab, kind="seg")
        self.tabs.picked.connect(self._pick_tab)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋")
        self.search.setFixedWidth(150)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._draw())
        self.sort = QComboBox()
        self.sort.setFixedWidth(150)
        self.sort.setCursor(Qt.PointingHandCursor)
        self.sort.currentIndexChanged.connect(self._sort_changed)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.tabs)
        top.addStretch(1)
        top.addWidget(self.search)
        top.addWidget(self.sort)
        v.addLayout(top)
        self.hint = dim("", wrap=True)
        v.addWidget(self.hint)
        self.box, self.list = card(margins=(0, 2, 0, 2), spacing=0)
        v.addWidget(self.box)
        v.addStretch(1)
        self.add_input = None

    # --- values ---
    def load(self):
        self._stamp = packs.stamp()
        self._draw()

    def reload_if_packs_changed(self):
        if packs.stamp() != self._stamp:
            self.load()

    def summary(self) -> str:
        return (f"詞包 {len(self.cfg.packs)} 個、詞庫列表 {len(self.win.hotwords.listed())} 個詞、"
                f"選字記憶 {len(self.win.memory.listed())} 筆")

    def restyle(self):
        self._draw()

    def _counts(self) -> dict:
        return {"packs": f"{len(self.cfg.packs)}/{len(packs.available())}", "words": str(len(self.win.hotwords.listed())),
                "picks": str(len(self.win.memory.listed())), "aliases": str(len(self.win.hotwords.aliases()))}

    # --- tabs, search, order ---
    def _pick_tab(self, key: str):
        self.tab = key
        if key != self.cfg.hotword_section:
            self.cfg.hotword_section = key
            self.cfg.save()
        self.search.clear()
        self._draw()

    def _sort_changed(self):
        if self.tab in SORTS and self.sort.currentData():
            setting = SORTS[self.tab][0]
            if getattr(self.cfg, setting) != self.sort.currentData():
                setattr(self.cfg, setting, self.sort.currentData())
                self.cfg.save()
                self._draw()

    def _show_sort(self):
        self.sort.blockSignals(True)
        self.sort.clear()
        if self.tab in SORTS:
            setting, items = SORTS[self.tab]
            for k, name in items:
                self.sort.addItem(name, k)
            self.sort.setCurrentIndex(max(0, self.sort.findData(getattr(self.cfg, setting))))
        self.sort.setVisible(self.tab in SORTS)
        self.sort.blockSignals(False)

    # --- drawing ---
    def _draw(self):
        counts = self._counts()
        for k, name, _ in TABS:
            self.tabs.setText(k, f"{name}  {counts[k]}")
        self.tabs.set(self.tab)
        self.hint.setText(dict((k, h) for k, _, h in TABS)[self.tab])
        self._show_sort()
        typed = self.add_input.text() if self.add_input is not None else ""
        self.add_input = None
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        q = self.search.text().strip().casefold()
        rows = getattr(self, f"_rows_{self.tab}")(q)
        if self.add_input is not None:
            self.add_input.setText(typed)
        if not rows:
            r = Row()
            r.setProperty("first", self.list.count() == 0)
            r.lay.addWidget(dim("沒有符合的項目" if q else self._empty_text(), wrap=True), 1)
            self.list.addWidget(r)
        first = True
        for i in range(self.list.count()):
            w = self.list.itemAt(i).widget()
            if isinstance(w, Row):
                w.setProperty("first", first)
                first = False

    def _empty_text(self) -> str:
        return {"words": "詞庫裡還沒有詞。選字時選了詞語（被換掉的詞也會列出），或在上面輸入詞語，就會加到這裡。",
                "picks": "還沒有記下的字。用選字換掉單一個中文字，就會記下它前後的字，之後在同樣的前後文自動換成那個字。",
                "aliases": "還沒有英文替換。選字或打字把英文換成另一種拼法（例如 Dipsick 換成 DeepSeek），之後辨識出舊拼法"
                           "就一律改成新的。"}.get(self.tab, "")

    def _rows_packs(self, q):
        out = 0
        for pack in packs.available():
            if q and q not in pack.name.casefold() and not any(q in w.casefold() for w in pack.words):
                continue
            r = Row()
            sw = Switch(pack.id in self.cfg.packs, pack.name)
            sw.toggled.connect(lambda on, i=pack.id: self._toggle_pack(i, on))
            r.lay.addWidget(sw)
            name = label(pack.name)
            name.setFont(theme.font(14, 500))
            r.lay.addWidget(_fixed(name, 130))
            n = label(f"{len(pack.words)} 個詞")
            n.setFont(theme.font(13.5, 600, num=True))
            r.lay.addWidget(_fixed(n, 74))
            terms = dim("、".join(pack.words[:_SHOWN]) + ("…" if len(pack.words) > _SHOWN else ""))
            terms.setMinimumWidth(10)
            terms.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            r.lay.addWidget(terms, 1)
            r.lay.addWidget(button("編輯詞", lambda _=False, i=pack.id: self._edit_pack(i)))
            self.list.addWidget(r)
            out += 1
        return out

    def _rows_words(self, q):
        add = Row(tint=True)
        self.add_input = QLineEdit()
        self.add_input.setPlaceholderText("輸入要加的詞，例如人名或產品名")
        self.add_input.returnPressed.connect(self._add_word)
        self.add_input.setStyleSheet(f"QLineEdit {{ background: {T('tile').name()}; }}")
        add.lay.addWidget(self.add_input, 1)
        add.lay.addWidget(button("加入", self._add_word, pri=True))
        self.list.addWidget(add)
        head = Row(header=True)
        head.lay.addWidget(_fixed(self._h("詞"), 150))
        scale = QWidget()
        sl = QHBoxLayout(scale)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self._h("← 少出現"))
        sl.addStretch(1)
        sl.addWidget(self._h("多出現 →"))
        head.lay.addWidget(scale, 1)
        h = self._h("優先度")
        h.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.lay.addWidget(_fixed(h, 56))
        head.lay.addWidget(_fixed(self._h("來源"), 120))
        head.lay.addSpacing(28)
        self.list.addWidget(head)
        items = self._sorted_words()
        n = 0
        for h in items:
            if q and q not in h.word.casefold():
                continue
            r = Row()
            w = label(h.word)
            w.setFont(theme.font(14, 500))
            r.lay.addWidget(_fixed(w, 150))
            r.lay.addWidget(Bar(h.pct), 1)
            pct = label(_shown(h.pct))
            pct.setFont(theme.font(14, 600, num=True))
            pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if h.pct < hw.NEUTRAL:
                pct.setStyleSheet(f"color: {T('muted').name()};")
            r.lay.addWidget(_fixed(pct, 56))
            src = dim(f"{SOURCES.get(h.source, '')} · {h.added[5:10].replace('-', '/')}" if h.added
                      else SOURCES.get(h.source, ""))
            src.setToolTip(h.added)
            r.lay.addWidget(_fixed(src, 120))
            r.lay.addWidget(_x_button(lambda _=False, word=h.word: self._remove_word(word), "移除，優先度回到預設"))
            self.list.addWidget(r)
            n += 1
        return n

    def _rows_picks(self, q):
        rows = self.win.memory.listed()
        order = self.cfg.pick_sort
        if order in ("reading", "reading_desc"):
            rows.sort(key=lambda e: (e["key"], e["value"]), reverse=order == "reading_desc")
        else:
            rows.sort(key=lambda e: (e["added"], e["serial"]), reverse=order != "date_old")
        head = Row(header=True)
        head.lay.addWidget(self._h("聽到"), 1)
        head.lay.addSpacing(24)
        head.lay.addWidget(self._h("自動寫成"), 1)
        head.lay.addWidget(_fixed(self._h("記住於"), 60))
        head.lay.addSpacing(28)
        self.list.addWidget(head)
        n = 0
        for e in rows:
            left = "".join(c for c in e["left"] if c != BOUNDARY)
            right = "".join(e["right"])
            if q and q not in (left + e["value"] + right + e["key"]).casefold():
                continue
            r = Row()
            heard = QLabel(f"{left}<span style='font-family:\"{theme.NUM_FONT}\"; font-weight:600; "
                           f"color:{T('acct').name()}; background:rgba(255,69,58,40);'>"
                           f"&nbsp;{e['key']}&nbsp;</span>{right}")
            heard.setFont(theme.font(14.5))
            r.lay.addWidget(heard, 1)
            r.lay.addWidget(_arrow())
            to = QLabel(f"{left}<b style='color:{T('acct').name()}'>{e['value']}</b>{right}")
            to.setFont(theme.font(14.5))
            r.lay.addWidget(to, 1)
            d = dim(e["added"][5:10].replace("-", "/"))
            d.setToolTip(e["added"])
            r.lay.addWidget(_fixed(d, 60))
            r.lay.addWidget(_x_button(lambda _=False, k=e["key"], s=e["serial"]: self._remove_pick(k, s), "忘掉這筆"))
            self.list.addWidget(r)
            n += 1
        return n

    def _rows_aliases(self, q):
        rows = [(a, w, self.win.hotwords.alias_date(w, a)) for a, w in self.win.hotwords.aliases()]
        order = self.cfg.alias_sort
        if order in ("name", "name_desc"):
            rows.sort(key=lambda r: (r[0].casefold(), r[1].casefold()), reverse=order == "name_desc")
        else:
            rows.sort(key=lambda r: r[2], reverse=order != "date_old")
        head = Row(header=True)
        head.lay.addWidget(self._h("聽到"), 1)
        head.lay.addSpacing(24)
        head.lay.addWidget(self._h("一律寫成"), 1)
        head.lay.addWidget(_fixed(self._h("日期"), 60))
        head.lay.addSpacing(28)
        self.list.addWidget(head)
        n = 0
        for alias, word, added in rows:
            if q and q not in (alias + word).casefold():
                continue
            r = Row()
            a = label(alias)
            a.setFont(theme.font(15, 500, num=True))
            a.setStyleSheet(f"color: {T('muted').name()};")
            r.lay.addWidget(a, 1)
            r.lay.addWidget(_arrow())
            b = label(word)
            b.setFont(theme.font(15, 700, num=True))
            r.lay.addWidget(b, 1)
            d = dim(added[5:10].replace("-", "/"))
            d.setToolTip(added)
            r.lay.addWidget(_fixed(d, 60))
            r.lay.addWidget(_x_button(lambda _=False, w=word, al=alias: self._remove_alias(w, al), "不再替換"))
            self.list.addWidget(r)
            n += 1
        return n

    @staticmethod
    def _h(text):
        h = label(text)
        h.setFont(theme.font(12, 700))
        h.setStyleSheet(f"color: {T('muted').name()};")
        return h

    def _sorted_words(self) -> list:
        """The list in the chosen order; ties by 優先度, then name. Names sort by their pinyin, so Chinese words sit
        among the English ones by sound."""
        def name(h):
            return "".join(lazy_pinyin(h.word)).casefold()
        items = sorted(self.win.hotwords.listed(), key=lambda h: (-h.pct, name(h)))
        order = self.cfg.hotword_sort
        if order in ("name", "name_desc"):
            items.sort(key=name, reverse=order == "name_desc")
        elif order in ("date", "date_old"):
            items.sort(key=lambda h: h.added, reverse=order == "date")
        return items

    # --- changes ---
    def _toggle_pack(self, pack_id: str, on: bool):
        ids = [i for i in self.cfg.packs if i != pack_id] + ([pack_id] if on else [])
        self.cfg.packs = ids
        self.cfg.save()
        self.win.hotwords.set_packs(packs.words_for(ids), packs.PCT)
        counts = self._counts()
        self.tabs.setText("packs", f"詞包  {counts['packs']}")
        self.win.refresh_tiles()

    def _edit_pack(self, pack_id: str):
        path = packs.path(pack_id)
        if not path.exists():
            packs.install()
        os.startfile(path)

    def _add_word(self):
        word = self.add_input.text().strip()
        if not word:
            return
        if not self.win.hotwords.add(word):
            Tip.flash(self.add_input.mapToGlobal(self.add_input.rect().bottomLeft()) + QPoint(0, 6),
                      "單一個中文字不能加入詞庫", self.add_input, 2500)
            return
        self.add_input.clear()
        self._draw()
        self.win.refresh_tiles()

    def _remove_word(self, word: str):
        self.win.hotwords.remove(word)
        self._draw()
        self.win.refresh_tiles()

    def _remove_pick(self, key: str, serial: int):
        self.win.memory.remove(key, serial)
        self._draw()
        self.win.refresh_tiles()

    def _remove_alias(self, word: str, alias: str):
        self.win.hotwords.remove_alias(word, alias)
        self._draw()
