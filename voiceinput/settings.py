"""Settings window in five tabs: 一般 (general), 外觀 (the glow, the draft's mark and the sounds; 2026-10-16),
辨識紀錄 (live transcript log), 自訂操作 (spoken operations, rules.py) and 詞庫 (hotwords.py, the UI name for hotwords since 2026-10-13), in four sections one open at a time:
term packs to tick (packs.py), every listed word with its 優先度 (−100% .. +100%, 0 does nothing; stored as 0 ..
200%; read only); 選字記憶 (the smart picks, memory.py); English replacements (hotword aliases). Each list is dated,
sortable, and its entries removable. Every change is applied and saved immediately."""
import html
import os
import time
from dataclasses import fields
from pathlib import Path

from pypinyin import lazy_pinyin
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QImage, QPainter, QPen, QPixmap, QTextDocument
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QTabWidget, QTextBrowser,
                               QToolButton,
                               QToolTip, QVBoxLayout, QWidget)

from . import audio, config, cues, hotwords, packs, recordings, rules, wordbank
from . import glow as glowmod
from .config import BUTTON_SCALE_RANGE, Config
from .floatbtn import OrbButton
from .highlight import COLORS as MARK_COLORS
from .orbs import LOOKS, palette
from .memory import BOUNDARY
from .keys import combo_text, hotkey_label, is_modifier
from .rules import Rule, Step

SPOKEN_ACTIONS = [(rules.KEYS, "按鍵"), (rules.TEXT, "輸入文字"), (rules.WRAP, "左右輸入文字"), (rules.UNDO, "復原"),
                  (rules.STOP, "結束錄音"),
                  (rules.SELECT_ALL, "全選"), (rules.COPY, "複製"), (rules.CUT, "剪下"), (rules.PASTE, "貼上")]
_COMMAND_NOTES = {rules.UNDO: "收回 VoiceInput 剛做的修改", rules.STOP: "關閉麥克風（不按 Enter）",
                  rules.SELECT_ALL: "全選（終端機裡無法全選）", rules.COPY: "複製選取的文字",
                  rules.CUT: "剪下選取的文字", rules.PASTE: "貼上（有選取時取代它）"}
# the 自訂操作 tab lists spoken operations by what they do (2026-10-16, the user's choice), in this order, under
# these headings; a row's place in its group by _ORDER, then as it was
_GROUPS = ["輸入", "修改", "剪貼簿", "結束", "自訂"]
_ORDER = {(rules.KEYS, "Shift+Enter"): (0, 0), (rules.KEYS, "Space"): (0, 1), (rules.KEYS, "Tab"): (0, 2),
          (rules.TEXT, None): (0, 3), (rules.WRAP, None): (0, 4),
          (rules.KEYS, "Backspace"): (1, 0), (rules.KEYS, "Delete"): (1, 1), (rules.COMMAND, rules.UNDO): (1, 2),
          (rules.COMMAND, rules.SELECT_ALL): (2, 0), (rules.COMMAND, rules.COPY): (2, 1),
          (rules.COMMAND, rules.CUT): (2, 2), (rules.COMMAND, rules.PASTE): (2, 3),
          (rules.KEYS, "Enter"): (3, 0), (rules.COMMAND, rules.STOP): (3, 1)}
# the default operations' steps: their rows are always listed, with the action fixed (2026-10-16, the user's
# choice: only the phrase is edited, left empty to turn one off; anything else is a row of 自訂)
_BUILT_IN = []
for _r in rules.defaults():
    if (_r.steps[0].type, _r.steps[0].value) not in _BUILT_IN:
        _BUILT_IN.append((_r.steps[0].type, _r.steps[0].value))


_BUILT_IN_COMMANDS = {v for k, v in _BUILT_IN if k == rules.COMMAND}


def _built_in(row) -> bool:
    return (row[1], row[2]) in _BUILT_IN


def _does(kind: str, value) -> str:
    """What a default operation does, in words (2026-10-16, the user's request: instead of its greyed-out action)."""
    if kind == rules.KEYS:
        return {"Shift+Enter": "換行（按 Shift+Enter）", "Space": "輸入一個空白", "Tab": "按 Tab",
                "Backspace": "刪除游標前的一個字（有選取時刪除選取的文字）",
                "Delete": "刪除游標後的一個字（有選取時刪除選取的文字）",
                "Enter": "按 Enter 送出，麥克風繼續開著"}.get(value, f"按 {value}")
    if kind == rules.TEXT:
        return f"輸入「{value}」"
    if kind == rules.WRAP and isinstance(value, (list, tuple)) and len(value) == 2:
        # one line for both cases (the user's request, 2026-10-16)
        return f"加上 {value[0]}{value[1]}，游標在中間；有選取時包住選取文字"
    return {rules.UNDO: "收回 VoiceInput 剛做的修改（一次一步）", rules.STOP: "關閉麥克風（不按 Enter）",
            rules.SELECT_ALL: "全選（終端機裡無法全選）", rules.COPY: "複製選取的文字",
            rules.CUT: "剪下選取的文字", rules.PASTE: "貼上剪貼簿的內容（有選取時取代它）"}.get(value, "")


def _place(row) -> tuple[int, int]:
    """(group, order in it) of a spoken row [phrases, step type, value]: a default one in its group, the user's own
    under 自訂 at the bottom, next to ＋ 新增口說操作."""
    _, kind, value = row
    if not _built_in(row):
        return 4, 0
    return _ORDER.get((kind, value if kind in (rules.KEYS, rules.COMMAND) else None), (4, 0))


def _swatch(color: str) -> QIcon:
    """A color button's icon: the mark color over white, as it looks on a page."""
    pm = QPixmap(20, 20)
    pm.fill(QColor("white"))
    p = QPainter(pm)
    p.fillRect(pm.rect(), QColor(color))
    p.setPen(QColor(0, 0, 0, 60))
    p.drawRect(pm.rect().adjusted(0, 0, -1, -1))
    p.end()
    icon = QIcon(pm)
    icon.addPixmap(pm, QIcon.Disabled)   # a preset's colors stay visible where they cannot be changed
    return icon

HOTWORD_SORTS = [("weight", "優先度（高→低）"), ("name", "名稱 A→Z"), ("name_desc", "名稱 Z→A"),
                 ("date", "日期（新→舊）"), ("date_old", "日期（舊→新）")]
PICK_SORTS = [("date", "日期（新→舊）"), ("date_old", "日期（舊→新）"), ("reading", "讀音 A→Z"),
              ("reading_desc", "讀音 Z→A")]
ALIAS_SORTS = [("date", "日期（新→舊）"), ("date_old", "日期（舊→新）"), ("name", "名稱 A→Z"), ("name_desc", "名稱 Z→A")]
def _shown(pct: int) -> str:
    """The 優先度 as the user sees it (2026-10-13, the user's choice): 0 does nothing, lowered words are negative."""
    d = pct - hotwords.NEUTRAL
    return f"{d:+d}%" if d else "0%"


def _show_pct(label, pct: int):
    label.setText(_shown(pct))
    label.setStyleSheet("color: #d03030" if pct < hotwords.NEUTRAL else "")


_SET_PAUSE = 0.8   # seconds between the start and end sound when a set is previewed
PREVIEW_MS = 3300  # a glow previewed shows this long, its fade-out included (App._preview_glow)
_CARD_STYLE = "QFrame#card { border: 1px solid palette(mid); border-radius: 6px; }"
_KIND_COLORS = {"輸入": "#1F5FAF", "操作": "#B35A00", "取代": "#0E7A6E", "選字": "#6B3FA0", "刪除": "#B42318", "復原": "#5B6573"}


def _scroll_instead(widget, e):
    """Give a wheel event to the scroll area around widget: on the list of operations the wheel scrolls and never
    changes a value (the user kept changing them by accident); only a click opens a drop-down."""
    area = widget.parentWidget()
    while area is not None and not isinstance(area, QScrollArea):
        area = area.parentWidget()
    if area is not None:
        QApplication.sendEvent(area.viewport(), e)


_COPY_ICON = "copy-icon"


class _LogView(QTextBrowser):
    """The 辨識紀錄 view: the copy icon its rows show is drawn here (rich text cannot load it from a file)."""

    def loadResource(self, kind, name):
        if kind == QTextDocument.ImageResource and name.toString() == _COPY_ICON:
            return _copy_icon()
        return super().loadResource(kind, name)


def _copy_icon() -> QImage:
    """Two overlapping rounded squares, gray, drawn at twice the size for sharp edges."""
    img = QImage(28, 28, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    img.setDevicePixelRatio(2)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#6B7280"), 1.3))
    p.drawRoundedRect(4.5, 1.5, 8, 8, 1.6, 1.6)
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(1.5, 4.5, 8, 8, 1.6, 1.6)
    p.end()
    return img


class _NoWheelCombo(QComboBox):
    def wheelEvent(self, e):
        _scroll_instead(self, e)


def _combo(items, value, tip="") -> QComboBox:
    c = _NoWheelCombo()
    for key, label in items:
        c.addItem(label, key)
    c.setCurrentIndex(max(0, c.findData(value)))
    if tip:
        c.setToolTip(tip)
    return c


def _card_list(empty_text: str, top=None):
    """A section of the 詞庫 tab: optional controls on top, a gray note shown while empty, then cards in a scroll
    area. Returns (layout the cards go in, the note, the section's widget)."""
    cards = QVBoxLayout()
    cards.setSpacing(4)
    inner = QWidget()
    v = QVBoxLayout(inner)
    v.setContentsMargins(0, 0, 0, 0)
    v.addLayout(cards)
    v.addStretch(1)
    scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
    scroll.setWidget(inner)
    scroll.viewport().setAutoFillBackground(False)   # the page's background, not a gray box under few cards
    inner.setAutoFillBackground(False)
    empty = QLabel(empty_text)
    empty.setStyleSheet("color: gray")
    empty.setWordWrap(True)
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 0, 0)
    if top is not None:
        layout.addLayout(top)
    layout.addWidget(empty)
    layout.addWidget(scroll, 1)
    return cards, empty, body


def _clear(layout):
    while layout.count():
        w = layout.takeAt(0).widget()
        w.setParent(None)
        w.deleteLater()


def _card() -> tuple[QFrame, QHBoxLayout]:
    card = QFrame(objectName="card")
    card.setStyleSheet(_CARD_STYLE)
    row = QHBoxLayout(card)
    row.setContentsMargins(8, 4, 4, 4)
    return card, row


_PACK_SHOWN = 5   # terms shown after a pack's name


def _date_label(added: str) -> QLabel:
    """The date of an entry; the time, kept for sorting (2026-10-14), only in the tooltip."""
    label = QLabel(added[:10])
    label.setStyleSheet("color: gray")
    return label


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: bold")
    return label


def _problem_label() -> QLabel:
    label = QLabel()
    label.setStyleSheet("color: #d9534f")
    label.setWordWrap(True)
    label.hide()
    return label


def _remove_button(tip: str, slot) -> QPushButton:
    b = QPushButton("✕", clicked=slot)   # no tooltip: only ⓘ explains (2026-10-16), ✕ needs none
    b.setFixedWidth(28)
    return b


def _info_icon() -> QImage:
    """A small gray circle with an i, drawn at twice the size for sharp edges."""
    img = QImage(32, 32, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    img.setDevicePixelRatio(2)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    gray = QColor("#8A9099")
    p.setPen(QPen(gray, 1.2))
    p.drawEllipse(1.5, 1.5, 13, 13)
    p.setPen(Qt.NoPen)
    p.setBrush(gray)
    p.drawEllipse(7.1, 4.2, 1.8, 1.8)
    p.drawRoundedRect(7.2, 6.9, 1.6, 5.2, 0.8, 0.8)
    p.end()
    return img


class _Info(QLabel):
    """ⓘ after a setting's name: its explanation shows only while the pointer is on it (2026-10-16, the user's
    request: tooltips over the controls popped up whenever the pointer rested there)."""

    def __init__(self, tip: str):
        super().__init__()
        self.tip = tip
        self.setPixmap(QPixmap.fromImage(_info_icon()))
        self.setFixedSize(18, 18)
        self.setAlignment(Qt.AlignCenter)

    def enterEvent(self, e):
        QToolTip.showText(self.mapToGlobal(QPoint(self.width(), self.height())), self.tip, self)

    def leaveEvent(self, e):
        QToolTip.hideText()


def _titled(text: str, tip: str) -> QWidget:
    """A form row's name with its ⓘ."""
    return _with_info(QLabel(text), tip, stretch=False)


def _with_info(widget, tip: str, stretch: bool = True) -> QWidget:
    """widget, then its ⓘ (a check box's text has no name column)."""
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    h.addWidget(widget)
    h.addWidget(_Info(tip))
    if stretch:
        h.addStretch()
    return box


class _OrbSample(OrbButton):
    """The 外觀 tab's example of the button look, animated, at the floating button's or the bubble's size, with its
    motions: the pointer over it shrinks it, a click plays listening starting and, a moment later, ending."""

    def __init__(self, size: int):
        super().__init__(size, room=1.7)   # less room than the real one: a click's growth is cut a little
        self.setToolTip("點一下看開關麥克風時的動畫")
        self._back = QTimer(self, singleShot=True, interval=900, timeout=self.come_back)

    def _fit(self):
        """Room for the largest 按鈕大小, so the row does not move when the size changes."""
        side = round(self.base * BUTTON_SCALE_RANGE[1] / 100 * self.room)
        self.margin = (side - self.bsize) // 2
        self.setFixedSize(side, side)

    def _gone(self):
        pass   # stays (transparent) until it comes back

    def clicked_demo(self):
        self.burst()
        self._back.start()


class KeyCapture(QLineEdit):
    """Click, then press a key combination: shows and stores it as text (Ctrl+Shift+Z)."""
    captured = Signal(str)

    def __init__(self, text: str):
        super().__init__(text, placeholderText="點這裡後按下組合鍵")
        self.setReadOnly(True)

    def event(self, e):
        if e.type() == QEvent.KeyPress:   # here, not keyPressEvent: Tab would move the focus first
            self._key(e)
            return True
        return super().event(e)

    def _key(self, e):
        vk = e.nativeVirtualKey()
        if is_modifier(vk):
            return
        mods = e.modifiers()
        names = [n for n, flag in (("Ctrl", Qt.ControlModifier), ("Shift", Qt.ShiftModifier),
                                   ("Alt", Qt.AltModifier), ("Win", Qt.MetaModifier)) if mods & flag]
        text = combo_text(names, vk)
        if text:
            self.setText(text)
            self.captured.emit(text)


class SettingsDialog(QDialog):
    applied = Signal()
    glow_preview = Signal(str)   # a glow style picked: shown for a moment
    capture_hotkey = Signal(bool)   # 麥克風快捷鍵: take the next press (True), or stop waiting for it

    def __init__(self, cfg, hotwords, memory):
        super().__init__()
        self.cfg = cfg
        self.hotwords = hotwords
        self.memory = memory
        self._loading = False
        self.setWindowTitle("VoiceInput 設定")
        self.resize(620, 560)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_page(), "一般")
        self.tabs.addTab(self._look_page(), "外觀")
        self.tabs.addTab(self._log_page(), "辨識紀錄")
        self.rules_tab = self.tabs.addTab(self._rules_page(), "自訂操作")
        self.tabs.currentChanged.connect(lambda i: self._warn_rules() if i == self.rules_tab else None)
        self.tabs.addTab(self._hotwords_page(), "詞庫")

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(buttons)

    # --- 一般 ---
    def _general_page(self) -> QWidget:
        self.mic = QComboBox()
        self.mic.addItem("系統預設", "")
        for name in audio.list_input_devices():
            self.mic.addItem(name, name)
        self.punct = QCheckBox("只說標點符號的名字時，輸入該符號")
        self.period_comma = QCheckBox("選取句號後講話，句號改成逗號並接上講的內容")
        self.period_comma.setToolTip("今天很好。明天見 → 選取「。」講「我們去公園」→ 今天很好，我們去公園。明天見")
        self.autostart = QCheckBox("開機時自動啟動")
        self.stop_on_enter = QCheckBox("送出訊息後自動關閉麥克風")
        self.mute = QCheckBox("錄音時暫時靜音電腦音效")
        self.describe = QCheckBox("說「詞＋的＋字」時只輸入那個字，例如「節日的節」")
        # 麥克風快捷鍵 (2026-10-17, the user's design): click, then press any key or mouse button but the left one,
        # with modifiers if wanted (hotkey.Hotkeys.capture); ✕ clears it
        self.hotkey = QPushButton(clicked=self._capture_clicked)
        self.hotkey.setMinimumWidth(180)
        self._capturing = False
        self.hotkey_clear = QToolButton(text="✕", autoRaise=True, clicked=self._clear_hotkey)
        self.hotkey_clear.setToolTip("不使用快捷鍵")
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self.hotkey)
        hotkey_row.addWidget(self.hotkey_clear)
        hotkey_row.addStretch()
        # 點進輸入框時 (2026-10-17, the user's design: the bubble and listening on by the focus are one choice; both
        # are shown or turned on by a left click that puts the focus in a text box)
        self.near_box = QComboBox()
        self.near_box.addItem("不使用", "")
        self.near_box.addItem("在點擊處旁顯示語音氣泡", "bubble")
        self.near_box.addItem("自動開麥克風，離開時關閉", "listen")
        # 浮動按鈕 (moved from 外觀 the same day), its two options under it, greyed out while it is off
        self.show_float = QCheckBox("顯示浮動按鈕")
        self.float_text_only = QCheckBox("只在可以打字的地方顯示")
        self.float_keep = QCheckBox("按下後不隱藏")
        float_box = QWidget()
        float_v = QVBoxLayout(float_box)
        float_v.setContentsMargins(0, 0, 0, 0)
        float_v.setSpacing(2)
        float_v.addWidget(_with_info(self.show_float, "停在螢幕上的按鈕，點一下開麥克風，拖到哪就留在哪；"
                                                      "樣子和大小在外觀頁設定"))
        float_opts = QHBoxLayout()
        float_opts.setContentsMargins(22, 0, 0, 0)
        float_opts.addWidget(_with_info(self.float_text_only, "勾選時，浮動按鈕只在游標停在可以打字的地方時出現；"
                                                              "不勾就到處都顯示", stretch=False))
        float_opts.addSpacing(16)
        float_opts.addWidget(_with_info(self.float_keep, "不勾時，開麥克風時按鈕放大淡出，關掉後縮回來；"
                                                         "勾了按鈕會留著，按下時彈一下，麥克風開著時再點一下就關掉",
                                        stretch=False))
        float_opts.addStretch()
        float_v.addLayout(float_opts)
        self.auto_off = QComboBox()
        self.auto_off.addItem("不自動關閉", 0)
        for m in (1, 3, 5, 10, 30):
            self.auto_off.addItem(f"{m} 分鐘沒講話", m)
        # development only, to be removed before release (the user's plan): recordings.py; shown only when launched
        # with --debug (config.DEBUG, 2026-10-17)
        self.keep_audio = QCheckBox("保存錄音（測試用）")
        folder = QPushButton("開啟錄音資料夾", clicked=self._open_recordings)
        audio_row = QHBoxLayout()
        audio_row.addWidget(_with_info(self.keep_audio, "每句話存成 wav，並記下辨識結果與之後的選字、刪除，"
                                                        "用來以真實聲音檢查辨識；不會自動刪除", stretch=False))
        audio_row.addWidget(folder)
        audio_row.addStretch()
        # development test (2026-10-17, the user's request; dev/cmdlab): a short command acted on after 0.15s of
        # silence instead of 0.3s
        self.early = QCheckBox("短停頓就執行指令（測試）")
        self.status = QLabel()
        self.status.setStyleSheet("color: gray")
        self.status.setWordWrap(True)

        form = QFormLayout()
        form.addRow("麥克風", self.mic)
        form.addRow(_titled("麥克風快捷鍵", "按一下右邊的按鈕，再按下想用的鍵盤按鍵（可以加 Ctrl、Shift、Alt、Win）"
                                      "或滑鼠按鍵（左鍵以外）；按 Esc 或點滑鼠左鍵取消。之後按一下這個鍵就開麥克風，"
                                      "再按一下關。這個鍵原本的功能會被取代"), hotkey_row)
        form.addRow(_titled("點進輸入框時", "用滑鼠左鍵點進可以打字的地方時：\n"
                                      "・語音氣泡：點擊處旁出現小按鈕，點一下開麥克風；打字、捲動滾輪或點到不能打字的地方"
                                      "就收起來\n"
                                      "・自動開麥克風：直接開麥克風，點到不能打字的地方（網頁空白處、按鈕、桌面）就關掉；"
                                      "用其他方式關掉後，再點一次輸入框就會重新打開"), self.near_box)
        form.addRow("", float_box)
        # nothing left to turn listening on (the tray notice of the key rows' days, now said here)
        self.no_way = _problem_label()
        self.no_way.setText("目前沒有任何方式能開麥克風：請設定「麥克風快捷鍵」、「點進輸入框時」或勾選「顯示浮動按鈕」")
        self.no_way.setWordWrap(True)
        form.addRow("", self.no_way)
        form.addRow(_titled("自動關閉麥克風", "麥克風開著卻一直沒聽到人聲時自動關掉，避免忘了關；關掉時播結束音"),
                    self.auto_off)
        form.addRow("", _with_info(self.stop_on_enter, "按 Enter（或 Ctrl+Enter）送出，或說「送出」之後，麥克風就自動關掉，"
                                                       "適合講完一則訊息就結束的用法。Shift+Enter 換行不算"))
        form.addRow("", _with_info(self.mute, "麥克風開著時把喇叭靜音，關閉麥克風後恢復；原本就靜音的話不會動"))
        form.addRow("", _with_info(self.punct, "逗號、句號、句點、問號、驚嘆號、感嘆號、頓號、分號、冒號、點點點、刪節號、"
                                               "省略號；整句只有這個名字才算，例如「逗號很重要」照常輸入"))
        # form.addRow("", self.period_comma)   # not carried over to continuous listening yet
        form.addRow("", _with_info(self.describe, "整句剛好是「詞＋的＋字」，而且「的」前面整段就是一個字典裡的詞才算"
                                                  "（例如「教育的育」；「這個字是教育的育」不算）；輸入的是詞裡讀音相同的那個字。"
                                                  "不想要這個功能就取消勾選"))
        form.addRow("", self.autostart)
        dev = form.rowCount()
        form.addRow("開發測試", audio_row)
        form.addRow("", _with_info(self.early, "單獨說出的指令停頓 0.15 秒就執行（平常要等 0.3 秒），所有指令都適用；"
                                               "認不出來就照常等 0.3 秒。代價是句子中間剛好停一下時可能被當成指令。"
                                               "下次開麥克風時生效"))
        for i in range(dev, form.rowCount()):
            form.setRowVisible(i, config.DEBUG)
        # 設定與詞庫 (2026-10-17, the user's design)
        reset = QPushButton("還原預設", clicked=self._reset_all)
        export = QPushButton("匯出詞庫…", clicked=self._export_words)
        import_ = QPushButton("匯入詞庫…", clicked=self._import_words)
        clear = QPushButton("清空詞庫", clicked=self._clear_words)
        file_row = QHBoxLayout()
        file_row.addWidget(_with_info(reset, "把這個設定視窗裡的所有設定（一般、外觀、自訂操作）還原成預設，"
                                             "不包含詞庫（詞包、詞庫列表、選字記憶、英文強制替換）", stretch=False))
        file_row.addSpacing(16)
        file_row.addWidget(export)
        file_row.addWidget(import_)
        file_row.addWidget(_with_info(clear, "匯出、匯入、清空的都是詞庫頁的全部內容：勾選的詞包和你改過的詞包內容、"
                                             "詞庫列表、選字記憶、英文強制替換。匯入會合併到現有的詞庫，兩邊都有的以匯入檔為準；"
                                             "想整個換掉就先清空再匯入", stretch=False))
        file_row.addStretch()
        form.addRow("設定與詞庫", file_row)
        page = QWidget()
        v = QVBoxLayout(page)
        v.addLayout(form)
        v.addStretch(1)
        v.addWidget(self.status)

        self.mic.currentIndexChanged.connect(self._apply)
        self.near_box.currentIndexChanged.connect(self._apply)
        self.auto_off.currentIndexChanged.connect(self._apply)
        for box in (self.punct, self.period_comma, self.describe, self.autostart, self.mute, self.keep_audio,
                    self.stop_on_enter, self.early, self.show_float, self.float_text_only, self.float_keep):
            box.toggled.connect(self._apply)
        return page

    def _capture_clicked(self):
        """麥克風快捷鍵: the next press becomes the hotkey (App._capture_hotkey); clicked again, cancelled."""
        self._capturing = not self._capturing
        self._show_hotkey()
        self.capture_hotkey.emit(self._capturing)

    def hotkey_captured(self, spec):
        """The press captured (a hotkey spec), or None: cancelled (Esc, a left click)."""
        if not self._capturing:
            return
        self._capturing = False
        if spec:
            self.cfg.hotkey = spec
            self._save()
            self._show_no_way()
        self._show_hotkey()

    def _clear_hotkey(self):
        if self._capturing:
            self._capturing = False
            self.capture_hotkey.emit(False)
        self.cfg.hotkey = ""
        self._save()
        self._show_hotkey()
        self._show_no_way()

    def _show_hotkey(self):
        self.hotkey.setText("請按下按鍵…（Esc 取消）" if self._capturing else hotkey_label(self.cfg.hotkey))
        self.hotkey_clear.setEnabled(bool(self.cfg.hotkey) or self._capturing)

    def hideEvent(self, e):
        if self._capturing:   # closed while waiting for a key
            self._capturing = False
            self.capture_hotkey.emit(False)
            self._show_hotkey()
        super().hideEvent(e)

    def _reset_all(self):
        """還原預設: every setting of this window as it comes, but the 詞庫 tab's (its packs ticked, orders, open
        section)."""
        if QMessageBox.question(self, "還原預設", "把這個設定視窗裡的所有設定（一般、外觀、自訂操作）還原成預設？\n"
                                               "詞庫不受影響。") != QMessageBox.Yes:
            return
        fresh = Config()
        keep = {"packs", "hotword_sort", "pick_sort", "alias_sort", "hotword_section"}
        for f in fields(Config):
            if f.name not in keep:
                setattr(self.cfg, f.name, getattr(fresh, f.name))
        self._save()
        self.load_values()

    def _export_words(self):
        name = f"VoiceInput 詞庫 {time.strftime('%Y-%m-%d')}.json"
        path, _ = QFileDialog.getSaveFileName(self, "匯出詞庫", str(Path.home() / "Documents" / name), "詞庫 (*.json)")
        if not path:
            return
        try:
            wordbank.export(Path(path), self.cfg, self.hotwords, self.memory)
        except OSError as e:
            QMessageBox.warning(self, "匯出詞庫", f"無法寫入檔案：{e}")
            return
        self.set_status(f"已匯出詞庫到 {path}")

    def _import_words(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入詞庫", str(Path.home() / "Documents"), "詞庫 (*.json)")
        if not path:
            return
        try:
            data = wordbank.load(Path(path))
            n = wordbank.merge(data, self.cfg, self.hotwords, self.memory)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "匯入詞庫", f"無法匯入：{e}")
            return
        self._words_changed()
        QMessageBox.information(self, "匯入詞庫", f"已合併：詞庫列表 {n['words']} 個詞、選字記憶 {n['picks']} 筆、"
                                              f"詞包新增 {n['pack_terms']} 個詞")

    def _clear_words(self):
        if QMessageBox.question(self, "清空詞庫", "清空詞庫列表、選字記憶、英文強制替換，詞包恢復成原始內容並取消勾選？\n"
                                              "這個動作無法復原，需要的話先匯出詞庫。") != QMessageBox.Yes:
            return
        wordbank.clear(self.cfg, self.hotwords, self.memory)
        self._words_changed()
        self.set_status("已清空詞庫")

    def _words_changed(self):
        self.cfg.save()
        self.hotwords.set_packs(packs.words_for(self.cfg.packs), packs.PCT)
        self.refresh_hotwords()
        self.applied.emit()

    # --- 外觀 (2026-10-16, the user's request: what is seen and heard) ---
    def _look_page(self) -> QWidget:
        self.start_sound, self.stop_sound = QComboBox(), QComboBox()
        for box in (self.start_sound, self.stop_sound):
            for cue_id, name, *_sources in cues.SOUNDS:
                box.addItem(name, cue_id)
            box.addItem("無", "")
        # a set picks both sounds at once; 自定義 shows a drop-down for each (the user's design, 2026-10-13)
        self.sound_set = QComboBox()
        for cue_id, name, *_sources in cues.SOUNDS:
            self.sound_set.addItem(name, cue_id)
        self.sound_set.addItem("無", "")
        self.sound_set.addItem("自定義", None)
        self._set_timer = QTimer(self, singleShot=True,
                                 timeout=lambda: cues.play(self._set_timer.property("cue"), "stop"))
        self.sound_listen = QPushButton("▶ 試聽", clicked=self._play_sounds)
        self._sound_done = QTimer(self, singleShot=True, timeout=self._show_sounds)   # 試聽 enabled again
        self.custom_sounds = QWidget()
        custom = QHBoxLayout(self.custom_sounds)
        custom.setContentsMargins(8, 0, 0, 0)
        for label, box in (("開始", self.start_sound), ("結束", self.stop_sound)):
            custom.addWidget(QLabel(label))
            custom.addWidget(box)
            custom.addSpacing(8)
        sound_row = QHBoxLayout()
        sound_row.addWidget(self.sound_set)
        sound_row.addWidget(self.sound_listen)
        sound_row.addWidget(self.custom_sounds)
        sound_row.addStretch()

        self.glow = QComboBox()
        self.glow.addItem("關閉", "")
        for st in glowmod.STYLES:
            self.glow.addItem(st.name, st.id)
        self.glow.setMinimumContentsLength(8)   # room for （已編輯）
        self.glow.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.glow_edges = QComboBox()
        for k, (label, *_edges) in glowmod.EDGES.items():
            self.glow_edges.addItem(label, k)
        self.glow_motion = QComboBox()
        for k, label in glowmod.MOTIONS.items():
            self.glow_motion.addItem(label, k)
        # ▶ 預覽 is disabled while the glow shows for a moment (picked, changed or previewed), like 試聽 while it
        # plays (the user's design, 2026-10-16)
        self.glow_preview_button = QPushButton("▶ 預覽", clicked=self._preview)
        self._preview_done = QTimer(self, singleShot=True, interval=PREVIEW_MS, timeout=self._show_glow)
        self.glow_reset = QPushButton("恢復預設", clicked=self._reset_glow)
        glow_row = QHBoxLayout()
        glow_row.addWidget(self.glow)
        glow_row.addWidget(self.glow_motion)
        glow_row.addWidget(self.glow_edges)
        glow_row.addWidget(self.glow_preview_button)
        glow_row.addWidget(self.glow_reset)
        glow_row.addStretch()

        # always shown and editable (the user's design, 2026-10-16; a separate 自訂 style before): the parameters
        # of the style picked, 2-6 colors and four sliders, saved when a slider is let go; a style changed shows
        # （已編輯） in the drop-down and 恢復預設 puts it back
        self.glow_params_box = QWidget()
        g = QGridLayout(self.glow_params_box)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        self.glow_colors = QHBoxLayout()
        self.glow_colors.setSpacing(4)
        g.addWidget(QLabel("顏色"), 0, 0)
        g.addLayout(self.glow_colors, 0, 1)
        self.glow_sliders = {}
        for row, (key, label, lo, hi, scale) in enumerate((("turn", "旋轉速度", 0, 40, 100), ("pulse", "呼吸", 0, 100, 100),
                                                          ("depth", "寬度", 40, 200, 100),
                                                          ("bright", "亮度", 30, 160, 100)), 1):
            slider = QSlider(Qt.Horizontal, minimum=lo, maximum=hi)
            slider.setProperty("scale", scale)
            # live while dragged (the user's request, 2026-10-16): the glow shows each value, saved when let go
            slider.valueChanged.connect(lambda v, k=key, w=slider, sc=scale:
                                        self._glow_edited(k, v / sc, save=not w.isSliderDown()))
            slider.sliderReleased.connect(lambda: self._glow_edited(None, None))
            slider.wheelEvent = lambda e, w=slider: _scroll_instead(w, e)
            self.glow_sliders[key] = slider
            g.addWidget(QLabel(label), row, 0)
            g.addWidget(slider, row, 1)
        g.setColumnStretch(1, 1)

        # the draft's mark: a few colors and 自訂 (the user's request, 2026-10-16)
        self.mark_group = QButtonGroup(self, exclusive=True)
        mark_row = QHBoxLayout()
        mark_row.setSpacing(4)
        for color, name in MARK_COLORS:
            b = QToolButton(checkable=True, icon=_swatch(color), autoRaise=True)
            b.setProperty("color", color)
            self.mark_group.addButton(b)
            mark_row.addWidget(b)
        self.mark_custom = QToolButton(checkable=True, autoRaise=True)
        self.mark_group.addButton(self.mark_custom)
        mark_row.addWidget(self.mark_custom)
        mark_row.addWidget(QPushButton("自訂…", clicked=self._pick_mark_color))
        mark_row.addStretch()
        self.mark_group.buttonClicked.connect(self._mark_clicked)

        self.button_look = QComboBox()
        for k, label in LOOKS.items():
            self.button_look.addItem(label, k)
        # the floating button's example next to the drop-down (2026-10-17, the user's request; the bubble's smaller
        # one was dropped with the 輸入框旁的按鈕 checkboxes)
        self.look_samples = [_OrbSample(44)]
        for w in self.look_samples:
            w.clicked.connect(w.clicked_demo)
        look_row = QHBoxLayout()
        look_row.addWidget(self.button_look)
        look_row.addSpacing(4)
        look_row.addWidget(self.look_samples[0], 0, Qt.AlignVCenter)
        look_row.addStretch()
        self.button_look.currentIndexChanged.connect(self._look_changed)
        self.orb_lite = QCheckBox("節流模式")
        self.orb_lite.toggled.connect(self._look_changed)
        # 按鈕大小 (2026-10-16, the user's request): 75-125% of the usual, shown as a percent with 標準 at 100%
        self.button_scale = QSlider(Qt.Horizontal, minimum=BUTTON_SCALE_RANGE[0], maximum=BUTTON_SCALE_RANGE[1],
                                    singleStep=5, pageStep=5, tickInterval=25)
        self.button_scale.setTickPosition(QSlider.TicksBelow)
        self.button_scale.setFixedWidth(180)
        self.button_scale.wheelEvent = lambda e, w=self.button_scale: _scroll_instead(w, e)
        self.button_scale_text = QLabel()
        self.button_scale_text.setMinimumWidth(90)
        self.button_scale.valueChanged.connect(self._button_scale_moved)
        self.button_scale.sliderReleased.connect(self._look_changed)
        size_row = QHBoxLayout()
        size_row.addWidget(self.button_scale)
        size_row.addWidget(self.button_scale_text)
        size_row.addStretch()
        form = QFormLayout()
        look_title = _titled("按鈕樣式", "浮動按鈕和語音氣泡的樣子：原本的麥克風，或跟光暈同色的能量球"
                                      "（沒開光暈時用彩虹的顏色）。右邊是浮動按鈕實際大小的範例，"
                                      "滑鼠移上去或點一下可以看動畫")
        look_title.setMinimumHeight(self.look_samples[0].height())   # level with the drop-down, not above it
        form.addRow(look_title, look_row)
        form.addRow(_titled("按鈕大小", "浮動按鈕和語音氣泡的大小，100% 是標準大小；上面的範例會跟著變"), size_row)
        form.addRow(_titled("螢幕邊緣光暈", "麥克風開著時，螢幕邊緣亮起一圈光，講話時會變亮。依序選顏色樣式、"
                                      "動態（柔光／波浪：邊緣像浪一樣起伏／流星：兩道光繞著螢幕跑／漣漪：一圈圈往內擴散）"
                                      "和亮哪幾邊；下面是樣式的參數，可以直接調整，調過的樣式會標「（已編輯）」，"
                                      "按「恢復預設」改回來。選了、調了或按「預覽」會先亮一下讓你看"),
                    glow_row)
        form.addRow("", self.glow_params_box)
        form.addRow(_titled("草稿反白顏色", "麥克風開著時，講完還可能被修正的字會疊上這個顏色，定稿後消失"), mark_row)
        form.addRow(_titled("提示音", "開始音在麥克風打開時、結束音在關掉時播放。同一組的開始音與結束音一起選；"
                                   "選「自定義」可分別挑選"), sound_row)
        # 節流模式 covers the edge glow too since 2026-10-16 (the user's request), so it has a row of its own
        form.addRow(_titled("效能", "動畫用多少 CPU"),
                    _with_info(self.orb_lite, "勾選後動畫改用較省 CPU 的畫法：能量球每秒 15 張、光暈較粗略、光點和細絲較少；"
                                              "螢幕邊緣光暈的波浪、流星、漣漪每秒 24 張。不勾時能量球每秒 30 張、細節完整；"
                                              "會移動的邊緣光暈每秒 48 張，比較順，但光暈的 CPU 用量約多七成"
                                              "（柔光兩種模式都是每秒 24 張）"))
        page = QWidget()
        v = QVBoxLayout(page)
        v.addLayout(form)
        v.addStretch(1)

        self.start_sound.currentIndexChanged.connect(lambda: self._sound_changed(self.start_sound, "start"))
        self.stop_sound.currentIndexChanged.connect(lambda: self._sound_changed(self.stop_sound, "stop"))
        self.sound_set.currentIndexChanged.connect(self._sound_set_changed)
        self.glow.currentIndexChanged.connect(self._glow_changed)
        self.glow_edges.currentIndexChanged.connect(self._glow_changed)
        self.glow_motion.currentIndexChanged.connect(self._glow_changed)
        self._live = QTimer(self, singleShot=True, interval=80, timeout=self._preview)
        return page

    def _glow_params(self) -> dict:
        """The parameters of the style picked, with the user's changes (彩虹's when there is no glow)."""
        style_id = self.glow.currentData() or glowmod.STYLES[0].id
        base = glowmod.params(glowmod.BY_ID[style_id])
        edits = self.cfg.glow_edits.get(style_id, {})
        return {**base, **{k: v for k, v in edits.items() if k in glowmod.PARAM_KEYS}}

    def _show_glow(self):
        """The parameters of the style picked, editable; （已編輯） after the styles changed, 恢復預設 for this one;
        預覽, the motion and the edges only with a glow."""
        style_id = self.glow.currentData()
        on = bool(style_id)
        for w in (self.glow_edges, self.glow_motion, self.glow_params_box):
            w.setEnabled(on)
        playing = self._preview_done.isActive()
        self.glow_preview_button.setEnabled(on and not playing)
        self.glow_preview_button.setText("播放中…" if playing else "▶ 預覽")
        self.glow_reset.setEnabled(on and glowmod.edited(style_id, self.cfg.glow_edits))
        for i in range(1, self.glow.count()):
            st = glowmod.BY_ID[self.glow.itemData(i)]
            self.glow.setItemText(i, st.name + ("（已編輯）" if glowmod.edited(st.id, self.cfg.glow_edits) else ""))
        c = self._glow_params()
        for key, slider in self.glow_sliders.items():
            slider.blockSignals(True)
            slider.setValue(round(float(c[key]) * slider.property("scale")))
            slider.blockSignals(False)
        _clear_layout(self.glow_colors)
        for i, color in enumerate(c["colors"]):
            b = QToolButton(icon=_swatch(color), autoRaise=True, clicked=lambda _=False, i=i: self._glow_color(i))
            self.glow_colors.addWidget(b)
        if len(c["colors"]) < glowmod.MAX_COLORS:
            self.glow_colors.addWidget(QToolButton(text="＋", autoRaise=True, clicked=lambda: self._glow_color(-1)))
        if len(c["colors"]) > 2:
            self.glow_colors.addWidget(QToolButton(text="－", autoRaise=True, clicked=self._glow_fewer))
        self.glow_colors.addStretch()

    def _glow_edited(self, key, value, save: bool = True):
        """A parameter of the style picked changed (key None: a slider let go). While a slider is dragged the glow
        follows it (at most every 0.08s) and nothing is saved yet. Only what differs from the style is kept."""
        style_id = self.glow.currentData()
        if not style_id:
            return
        c = self._glow_params()
        if key is not None:
            c[key] = round(value, 2) if isinstance(value, float) else value
        base = glowmod.params(glowmod.BY_ID[style_id])
        changed = {k: v for k, v in c.items() if v != base[k]}
        edits = dict(self.cfg.glow_edits)
        if changed:
            edits[style_id] = changed
        else:
            edits.pop(style_id, None)
        self.cfg.glow_edits = edits
        if save:
            self._save()
            self._show_glow()
        self._show_samples()
        if not self._live.isActive():
            self._live.start()

    def _reset_glow(self):
        """恢復預設: the style picked as it comes."""
        edits = dict(self.cfg.glow_edits)
        edits.pop(self.glow.currentData(), None)
        self.cfg.glow_edits = edits
        self._save()
        self._show_glow()
        self._show_samples()
        self._preview()

    def _look_changed(self):
        self._apply()
        self._show_samples()

    def _show_samples(self):
        """The button look's examples, in the colors of the glow picked."""
        colors = palette(glowmod.style_for(self.glow.currentData(), self.cfg.glow_edits))
        for w in self.look_samples:
            w.set_look(self.button_look.currentData(), colors, self.orb_lite.isChecked(), self.button_scale.value())

    def _button_scale_moved(self, value: int):
        self.button_scale_text.setText(f"{value}%（標準）" if value == 100 else f"{value}%")
        if not self.button_scale.isSliderDown():   # keys or a click on the groove: no release follows
            self._look_changed()
        else:
            self._show_samples()

    def _glow_color(self, i: int):
        """A color of the style picked changed (i), or added (-1)."""
        colors = list(self._glow_params()["colors"])
        start = QColor(colors[i] if i >= 0 else colors[-1])
        c = QColorDialog.getColor(start, self, "光暈顏色")
        if not c.isValid():
            return
        if i >= 0:
            colors[i] = c.name()
        else:
            colors.append(c.name())
        self._glow_edited("colors", colors)

    def _glow_fewer(self):
        self._glow_edited("colors", list(self._glow_params()["colors"])[:-1])

    def _preview(self):
        """The glow shown for a moment (App._preview_glow); ▶ 預覽 disabled meanwhile."""
        if self.glow.currentData():
            self.glow_preview.emit(self.glow.currentData())
            self._preview_done.start()
            self.glow_preview_button.setEnabled(False)
            self.glow_preview_button.setText("播放中…")

    def _show_mark_color(self):
        """The button of the current color checked; a color of one's own on the 自訂 swatch."""
        color = self.cfg.highlight_color.upper()
        preset = next((b for b in self.mark_group.buttons() if b is not self.mark_custom
                       and b.property("color").upper() == color), None)
        self.mark_custom.setVisible(preset is None)
        if preset is None:
            self.mark_custom.setIcon(_swatch(color))
            self.mark_custom.setProperty("color", color)
            self.mark_custom.setChecked(True)
        else:
            preset.setChecked(True)

    def _mark_clicked(self, button):
        self.cfg.highlight_color = button.property("color")
        self._save()

    def _pick_mark_color(self):
        c = QColorDialog.getColor(QColor(self.cfg.highlight_color), self, "草稿反白顏色",
                                  QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self.cfg.highlight_color = c.name(QColor.HexArgb).upper()
            self._show_mark_color()
            self._save()

    def load_values(self):
        self._loading = True
        self.mic.setCurrentIndex(max(0, self.mic.findData(self.cfg.mic)))
        self.punct.setChecked(self.cfg.punctuation_names)
        self.period_comma.setChecked(self.cfg.period_to_comma)
        self.autostart.setChecked(self.cfg.autostart)
        self.stop_on_enter.setChecked(self.cfg.stop_on_enter)
        self.mute.setChecked(self.cfg.mute_while_recording)
        self.describe.setChecked(self.cfg.describe_char)
        self._show_hotkey()
        near = "listen" if self.cfg.auto_listen else "bubble" if self.cfg.show_bubble else ""
        self.near_box.setCurrentIndex(max(0, self.near_box.findData(near)))
        self.show_float.setChecked(self.cfg.show_float)
        self.glow_edges.setCurrentIndex(max(0, self.glow_edges.findData(self.cfg.glow_edges)))
        self._show_mark_color()
        self.keep_audio.setChecked(self.cfg.save_recordings)
        self.early.setChecked(self.cfg.early_commands)
        self.start_sound.setCurrentIndex(max(0, self.start_sound.findData(self.cfg.start_sound)))
        self.stop_sound.setCurrentIndex(max(0, self.stop_sound.findData(self.cfg.stop_sound)))
        self.glow.setCurrentIndex(max(0, self.glow.findData(self.cfg.glow)))
        self.glow_motion.setCurrentIndex(max(0, self.glow_motion.findData(self.cfg.glow_motion)))
        self.button_look.setCurrentIndex(max(0, self.button_look.findData(self.cfg.button_look)))
        self.orb_lite.setChecked(self.cfg.orb_lite)
        self.button_scale.setValue(self.cfg.button_scale)
        self._button_scale_moved(self.cfg.button_scale)
        self.float_text_only.setChecked(self.cfg.float_text_only)
        self.float_keep.setChecked(self.cfg.float_keep)
        self._show_glow()
        self._show_samples()
        i = self.auto_off.findData(self.cfg.auto_off_minutes)
        if i < 0:   # a value set by hand in config.json
            self.auto_off.addItem(f"{self.cfg.auto_off_minutes} 分鐘沒講話", self.cfg.auto_off_minutes)
            i = self.auto_off.count() - 1
        self.auto_off.setCurrentIndex(i)
        same = self.cfg.start_sound == self.cfg.stop_sound
        self.sound_set.setCurrentIndex(self.sound_set.findData(self.cfg.start_sound) if same
                                       else self.sound_set.count() - 1)
        self._show_sounds()
        self._show_no_way()
        self._loading = False
        self.refresh_rules()
        self.refresh_hotwords()

    def showEvent(self, e):
        super().showEvent(e)
        if self.tabs.currentIndex() == self.rules_tab:
            self._warn_rules()

    def set_status(self, text: str):
        self.status.setText(text)

    def _apply(self):
        if self._loading:
            return
        self.cfg.mic = self.mic.currentData()
        self.cfg.punctuation_names = self.punct.isChecked()
        self.cfg.period_to_comma = self.period_comma.isChecked()
        self.cfg.autostart = self.autostart.isChecked()
        self.cfg.stop_on_enter = self.stop_on_enter.isChecked()
        self.cfg.mute_while_recording = self.mute.isChecked()
        self.cfg.describe_char = self.describe.isChecked()
        near = self.near_box.currentData()
        self.cfg.show_bubble, self.cfg.auto_listen = near == "bubble", near == "listen"
        self.cfg.show_float = self.show_float.isChecked()
        self.cfg.glow_edges = self.glow_edges.currentData()
        self.cfg.glow_motion = self.glow_motion.currentData()
        self.cfg.button_look = self.button_look.currentData()
        self.cfg.orb_lite = self.orb_lite.isChecked()
        self.cfg.button_scale = self.button_scale.value()
        self.cfg.float_text_only = self.float_text_only.isChecked()
        self.cfg.float_keep = self.float_keep.isChecked()
        if config.DEBUG:
            self.cfg.save_recordings = self.keep_audio.isChecked()
            self.cfg.early_commands = self.early.isChecked()
        self.cfg.start_sound = self.start_sound.currentData()
        self.cfg.stop_sound = self.stop_sound.currentData()
        self.cfg.glow = self.glow.currentData()
        self.cfg.auto_off_minutes = self.auto_off.currentData()
        self._save()
        self._show_no_way()

    def _show_no_way(self):
        self.no_way.setVisible(not (self.cfg.hotkey or self.cfg.auto_listen or self.cfg.show_bubble
                                    or self.cfg.show_float))
        for box in (self.float_text_only, self.float_keep):
            box.setEnabled(self.cfg.show_float)

    def _glow_changed(self):
        self._apply()
        self._show_glow()
        self._show_samples()
        if not self._loading:
            self._preview()

    def _sound_changed(self, box, kind: str):
        if not self._loading:
            cues.play(box.currentData(), kind)
            if box.currentData():
                self._playing(cues.duration(box.currentData(), kind))
            self._show_sounds()
        self._apply()

    def _custom(self) -> bool:
        return self.sound_set.currentData() is None

    def _show_sounds(self):
        """The 開始 / 結束 drop-downs only for 自定義; 試聽 only when there is something to play, and not while it
        plays."""
        self.custom_sounds.setVisible(self._custom())
        playing = self._sound_done.isActive()
        self.sound_listen.setEnabled(bool(self.start_sound.currentData() or self.stop_sound.currentData())
                                     and not playing)
        self.sound_listen.setText("播放中…" if playing else "▶ 試聽")

    def _playing(self, seconds: float):
        """A sound plays for that long: 試聽 disabled meanwhile."""
        self._sound_done.start(int(seconds * 1000) + 100)
        self.sound_listen.setEnabled(False)
        self.sound_listen.setText("播放中…")

    def _sound_set_changed(self):
        cue_id = self.sound_set.currentData()
        if cue_id is not None and not self._loading:   # a set: both sounds, previewed together
            self._loading = True
            self.start_sound.setCurrentIndex(self.start_sound.findData(cue_id))
            self.stop_sound.setCurrentIndex(self.stop_sound.findData(cue_id))
            self._loading = False
            self._play_sounds()
            self._apply()
        self._show_sounds()   # 自定義: the sounds stay as they are, their drop-downs show

    def _play_sounds(self):
        """Previewed as a recording: the start sound, a pause, the end sound (the user's request)."""
        self._set_timer.stop()
        start, stop = self.start_sound.currentData(), self.stop_sound.currentData()
        cues.play(start, "start")
        total = cues.duration(start, "start") if start else 0
        if stop:
            wait = (total + _SET_PAUSE) if start else 0
            self._set_timer.setProperty("cue", stop)
            self._set_timer.start(int(wait * 1000))
            total = wait + cues.duration(stop, "stop")
        if total:
            self._playing(total)

    def _save(self):
        self.cfg.save()
        self.applied.emit()

    def _open_recordings(self):
        recordings.DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(recordings.DIR)

    # --- 詞庫 (hotwords) ---
    def _hotwords_page(self) -> QWidget:
        """Four sections, one open at a time (2026-10-14, the user's design): the open one fills the page and
        scrolls inside, the other headers stay in view; the open one is remembered (hotword_section)."""
        pack_top = QHBoxLayout()
        pack_note = QLabel("勾選的詞包裡的詞比較容易被辨識出來")
        pack_note.setStyleSheet("color: gray")
        pack_top.addWidget(_with_info(pack_note, f"整包的詞以優先度 {_shown(packs.PCT)} 辨識；選字選過或被換掉的詞會列在"
                                                 "詞庫列表，以那裡的優先度為準。「編輯」用記事本開啟這個詞包的文字檔："
                                                 "一行一個詞，存檔後下次說話就生效"))
        self.pack_list, no_packs, pack_body = _card_list("", pack_top)
        no_packs.hide()
        self._pack_stamp = None

        # typing a word here replaced the 選字 menu's input box (2026-10-16, the user's choice): 200%, like before
        self.hw_input = QLineEdit(placeholderText="輸入詞語加入詞庫")
        self.hw_input.returnPressed.connect(self._add_hotword)
        add = QPushButton("加入")
        add.clicked.connect(self._add_hotword)
        self.hw_input.setFixedWidth(180)
        hw_top = self._sort_row(HOTWORD_SORTS, "hotword_sort",   # 排序 [drop-down] ⓘ … [input] [加入]
                                "優先度：0% 不影響辨識；正的越容易辨識成這個詞，負的越不容易。選字選到會提高，被換掉會降低")
        hw_top.addWidget(self.hw_input)
        hw_top.addWidget(add)
        self.hw_list, self.hw_empty, hw_body = _card_list(
            "詞庫裡還沒有詞。選字時選了詞語（被換掉的詞也會列出，優先度較低），或在上面輸入詞語，就會加到這裡。", hw_top)
        self.pick_list, self.pick_empty, pick_body = _card_list(
            "還沒有記下的字。用選字換掉單一個中文字，就會記下它前後的字，之後在同樣的前後文自動換成那個字。",
            self._sort_row(PICK_SORTS, "pick_sort", "「這個ying3片是 → 這個影片是」：聽成這個讀音、前後是這些字時，"
                                                    "自動換成右邊的字"))
        self.alias_list, self.alias_empty, alias_body = _card_list(
            "還沒有強制替換。選字或打字把英文換成另一種拼法的詞（例如 Dipsick 換成 DeepSeek），之後辨識出舊拼法就一律改成新的。",
            self._sort_row(ALIAS_SORTS, "alias_sort", "辨識出左邊的拼法時，一律改成右邊的詞"))

        self._sections = {}
        page = QWidget()
        self._section_layout = QVBoxLayout(page)
        self._section_layout.setSpacing(2)
        for key, body in (("packs", pack_body), ("words", hw_body), ("picks", pick_body), ("aliases", alias_body)):
            header = QToolButton(checkable=True, autoRaise=True, toolButtonStyle=Qt.ToolButtonTextBesideIcon)
            header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            header.setStyleSheet("QToolButton { font-weight: bold; padding: 4px; }"
                                 " QToolButton:checked { background: transparent; border: none; }")
            header.clicked.connect(lambda on, k=key: self._open_section(k if on else ""))
            body.setVisible(False)
            self._section_layout.addWidget(header)
            self._section_layout.addWidget(body)
            self._sections[key] = (header, body)
        self._section_layout.addStretch(1)
        self._open_section(self.cfg.hotword_section, save=False)
        return page

    def _open_section(self, key: str, save: bool = True):
        for k, (header, body) in self._sections.items():
            on = k == key
            header.setChecked(on)
            header.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
            body.setVisible(on)
            self._section_layout.setStretchFactor(body, 1 if on else 0)
        self._section_layout.setStretch(self._section_layout.count() - 1, 0 if key in self._sections else 1)
        if save and key != self.cfg.hotword_section:
            self.cfg.hotword_section = key
            self.cfg.save()

    def _sort_row(self, sorts, setting: str, tip: str = "") -> QHBoxLayout:
        """排序 and its drop-down (the choice is saved as cfg.<setting>), and the list's ⓘ."""
        combo = _combo(sorts, getattr(self.cfg, setting))
        combo.currentIndexChanged.connect(lambda: self._sort_changed(setting, combo.currentData()))
        row = QHBoxLayout()
        row.addWidget(QLabel("排序"))
        row.addWidget(combo)
        if tip:
            row.addWidget(_Info(tip))
        row.addStretch()
        return row

    def _sort_changed(self, setting: str, value: str):
        setattr(self.cfg, setting, value)
        self.cfg.save()
        self.refresh_hotwords()

    def _set_headers(self):
        texts = {"packs": f"詞包（已勾選 {len(self.cfg.packs)}）", "words": f"詞庫列表（{len(self.hotwords.listed())}）",
                 "picks": f"選字記憶（{len(self.memory.listed())}）",
                 "aliases": f"英文強制替換（{len(self.hotwords.aliases())}）"}
        for k, (header, _) in self._sections.items():
            header.setText(texts[k])

    def refresh_hotwords(self):
        """The whole 詞庫 tab: term packs, hotwords, 選字記憶 (smart picks), English replacements and the section
        headers."""
        self._refresh_packs()
        self._refresh_words()
        self._refresh_picks()
        self._refresh_aliases()
        self._set_headers()

    def _refresh_packs(self):
        """One row per pack (2026-10-14, the user's design): check box with the count, its first terms (the files
        list the best known first), and 編輯, which opens the pack's own file in DATA_DIR/packs."""
        self._pack_stamp = packs.stamp()
        _clear(self.pack_list)
        for pack in packs.available():
            card, row = _card()
            box = QCheckBox(f"{pack.name}（{len(pack.words)}）", checked=pack.id in self.cfg.packs)
            box.toggled.connect(lambda on, i=pack.id: self._toggle_pack(i, on))
            box.setMinimumWidth(150)
            row.addWidget(box)
            terms = QLabel("、".join(pack.words[:_PACK_SHOWN]) + ("…" if len(pack.words) > _PACK_SHOWN else ""))
            terms.setStyleSheet("color: gray")
            terms.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # cut, never widening the window
            row.addWidget(terms, 1)
            edit = QPushButton("編輯", clicked=lambda _=False, i=pack.id: self._edit_pack(i))
            row.addWidget(edit)
            self.pack_list.addWidget(card)

    def _edit_pack(self, pack_id: str):
        path = packs.path(pack_id)
        if not path.exists():
            packs.install()
        os.startfile(path)

    def changeEvent(self, e):
        """Back from editing a pack file: show its new terms."""
        super().changeEvent(e)
        if e.type() == QEvent.ActivationChange and self.isActiveWindow() and packs.stamp() != self._pack_stamp:
            self.refresh_hotwords()

    def _refresh_words(self):
        """Each word: date added, its 優先度 (read only since 2026-10-14) and ✕, which puts it back where it would be
        unlisted."""
        _clear(self.hw_list)
        items = self._sorted_hotwords()
        for h in items:
            card, row = _card()
            row.addWidget(QLabel(h.word))
            row.addStretch(1)
            row.addWidget(_date_label(h.added))
            percent = QLabel()
            _show_pct(percent, h.pct)
            percent.setMinimumWidth(48)
            percent.setAlignment(Qt.AlignCenter)
            row.addWidget(percent)
            row.addWidget(_remove_button("移除，優先度回到預設", lambda _=False, w=h.word: self._remove_hotword(w)))
            self.hw_list.addWidget(card)
        self.hw_empty.setVisible(not items)

    def _refresh_picks(self):
        """Each example as heard -> as picked, the character shown by its reading on the left: 這個ying3片是 ->
        這個影片是 (the user's design, 2026-10-14)."""
        _clear(self.pick_list)
        rows = self.memory.listed()
        order = self.cfg.pick_sort
        if order in ("reading", "reading_desc"):
            rows.sort(key=lambda e: (e["key"], e["value"]), reverse=order == "reading_desc")
        else:
            rows.sort(key=lambda e: (e["added"], e["serial"]), reverse=order != "date_old")
        for e in rows:
            card, row = _card()
            left = "".join(c for c in e["left"] if c != BOUNDARY)
            right = "".join(e["right"])
            label = QLabel(f"{html.escape(left + e['key'] + right)} <span style='color:gray'>→</span> "
                           f"{html.escape(left + e['value'] + right)}")
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(_date_label(e["added"]))
            row.addWidget(_remove_button("移除這筆", lambda _=False, k=e["key"], n=e["serial"]:
                                         self._remove_pick(k, n)))
            self.pick_list.addWidget(card)
        self.pick_empty.setVisible(not rows)

    def _remove_pick(self, key: str, serial: int):
        self.memory.remove(key, serial)
        self.refresh_hotwords()

    def _refresh_aliases(self):
        _clear(self.alias_list)
        rows = [(a, w, self.hotwords.alias_date(w, a)) for a, w in self.hotwords.aliases()]
        order = self.cfg.alias_sort
        if order in ("name", "name_desc"):
            rows.sort(key=lambda r: (r[0].casefold(), r[1].casefold()), reverse=order == "name_desc")
        else:
            rows.sort(key=lambda r: r[2], reverse=order != "date_old")
        for alias, word, added in rows:
            card, row = _card()
            label = QLabel(f"{html.escape(alias)} <span style='color:gray'>→</span> {html.escape(word)}")
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(_date_label(added))
            row.addWidget(_remove_button("不再替換", lambda _=False, w=word, a=alias: self._remove_alias(w, a)))
            self.alias_list.addWidget(card)
        self.alias_empty.setVisible(not rows)

    def _sorted_hotwords(self) -> list:
        """The list in the chosen order; ties by percentage, then name. Names sort by their pinyin, so Chinese words
        sit among the English ones by sound (程式 near Claude)."""
        def name(h):
            return "".join(lazy_pinyin(h.word)).casefold()
        items = sorted(self.hotwords.listed(), key=lambda h: (-h.pct, name(h)))
        order = self.cfg.hotword_sort
        if order in ("name", "name_desc"):
            items.sort(key=name, reverse=order == "name_desc")
        elif order in ("date", "date_old"):
            items.sort(key=lambda h: h.added, reverse=order == "date")
        return items

    def _toggle_pack(self, pack_id: str, on: bool):
        ids = [i for i in self.cfg.packs if i != pack_id] + ([pack_id] if on else [])
        self.cfg.packs = ids
        self.cfg.save()
        self.hotwords.set_packs(packs.words_for(ids), packs.PCT)
        self._refresh_words()   # a listed word now at its pack's percentage leaves the list
        self._set_headers()

    def _remove_alias(self, word: str, alias: str):
        self.hotwords.remove_alias(word, alias)
        self.refresh_hotwords()

    def _add_hotword(self):
        word = self.hw_input.text().strip()
        if not word:
            return
        if not self.hotwords.add(word):
            QToolTip.showText(self.hw_input.mapToGlobal(self.hw_input.rect().bottomLeft()), "單一個中文字不能加入詞庫",
                              self.hw_input)
            return
        self.hw_input.clear()
        self.refresh_hotwords()

    def _remove_hotword(self, word: str):
        self.hotwords.remove(word)
        self.refresh_hotwords()

    # --- 辨識紀錄 ---
    def _log_page(self) -> QWidget:
        self.log = _LogView(openLinks=False)
        self.log.setPlaceholderText("開麥克風後，每段話聽到什麼、畫面上變成什麼會顯示在這裡（只保留這次執行期間）")
        self.log.document().setDefaultStyleSheet("a { color: #1F2328; text-decoration: none; }")
        self.log.anchorClicked.connect(self._log_link)
        self.log.highlighted.connect(self._log_hover)
        self._log_sessions = []
        self._log_rows: dict[int, dict] = {}
        return self.log

    def _log_link(self, url):
        """複製 copies the sentence a row finished; a click elsewhere on a row does nothing."""
        row = self._log_rows.get(int(url.path() or -1))
        if row is not None and url.scheme() == "copy":
            QApplication.clipboard().setText(row["copy"])
            QToolTip.showText(QCursor.pos(), "已複製", self.log)

    def _log_hover(self, url):
        """The pointer over a row: its why and details as a tooltip."""
        row = self._log_rows.get(int(url.path() or -1))
        if row is None:
            text = ""
        elif url.scheme() == "copy":
            text = "複製這句"
        elif url.scheme() == "bank":
            text = "\n".join(["詞庫可能影響了這句："] + row["bank"])
        else:
            text = "\n".join(x for x in (row["tag"], row["tip"]) if x)
        if text:
            QToolTip.showText(QCursor.pos(), text, self.log)
        else:
            QToolTip.hideText()

    def set_log(self, sessions):
        """What was heard next to what the screen became, as a diff (the user's pick, 2026-10-15, design B; logbook.py
        builds it): one group per listening session and one row per event, both newest first (the user's request, so
        the latest needs no scrolling): time, what was heard (a gray cell), the change (new text green, removed red
        and struck through) and, for a row that finished a sentence, a copy icon at its right end. What kind of change
        it was (整句重聽, 標點 …), why, and the recognizer's details are the row's tooltip (the user's request: no small
        print under the rows, details only when the pointer goes there)."""
        gray, ink = "#5F6670", "#1F2328"
        self._log_sessions = list(sessions)
        self._log_rows = {r["id"]: r for g in self._log_sessions for r in g["rows"]}

        def row(r):
            tip = f"tip:{r['id']}"
            heard = html.escape(r["heard"]) if r["heard"] else ""
            # （游標移到別處）, （關掉麥克風）…: what happened, not what was said, so plain gray text without the
            # cell said words have (the user's request, 2026-10-15)
            event = r["heard"].startswith("（") and r["heard"].endswith("）")
            copy = (f"<a href='copy:{r['id']}'><img src='{_COPY_ICON}' width=14 height=14></a>" if r["copy"] else "")
            # the 詞庫 took part (logbook.bank_of): a small yellow ! after what was heard, its tooltip says how
            bank = (f"<td style='padding-left:4px'><a href='bank:{r['id']}'><span style='background-color:#FFD84D; "
                    f"color:#5C4300; font-weight:bold; font-size:11px'>&nbsp;!&nbsp;</span></a></td>"
                    if r.get("bank") else "")
            return (f"<tr><td valign=top width=54 style='color:{gray}; font-size:11px; padding:5px 0 5px 0; "
                    f"font-family:Consolas,monospace'><a href='{tip}' style='color:{gray}'>{r['time']}</a></td>"
                    f"<td valign=top width='36%' style='padding:3px 8px 3px 0'>"
                    + (f"<div style='padding:2px 0'><a href='{tip}' style='color:{gray}'>{heard}</a></div>" if event
                       else f"<table cellspacing=0 cellpadding=0><tr><td bgcolor='#EEF1F5' style='padding:2px 7px'>"
                       f"<a href='{tip}' style='color:{ink}'>{heard}</a></td>{bank}</tr></table>" if heard else "")
                    + f"</td><td valign=top style='padding:4px 0'><a href='{tip}' style='color:{ink}'>{r['change']}</a>"
                    + f"</td><td valign=top align=right width=22 style='padding:5px 0 0 4px'>{copy}</td></tr>")

        def group(g):
            n = g["counts"]
            chips = [f"{n['pieces']} 段話"] if n["pieces"] else []
            chips += [f"{n['commands']} 個指令"] if n["commands"] else []
            chips += [f"復原 {n['undo']} 次"] if n["undo"] else []
            span = g["start"] if g["start"] == g["end"] else f"{g['start']}–{g['end']}"
            head = ("麥克風開著" if g["listening"] else "沒開麥克風時")
            title = (f"<b>{span}</b>　<span style='color:{gray}'>{head}" + ("　·　" if chips else "")
                     + "　·　".join(chips) + "</span>")
            cols = (f"<tr><td style='color:{gray}; font-size:11px'>時間</td><td style='color:{gray}; font-size:11px'>"
                    f"聽到</td><td style='color:{gray}; font-size:11px'>畫面上</td><td></td></tr>")
            rows = "".join(row(r) for r in reversed(g["rows"])) or (f"<tr><td colspan=4 style='color:{gray}; "
                                                                   f"padding:4px 0'>"
                                                         "（還沒有聽到講話）</td></tr>")
            return (f"<table width='100%' cellspacing=0 cellpadding=0 border=1 style='border-collapse:collapse; "
                    f"border-color:#D5DAE1; border-style:solid; margin-bottom:8px'>"
                    f"<tr><td bgcolor='#E6EAF0' style='padding:5px 8px; font-size:13px'>{title}</td></tr>"
                    f"<tr><td style='padding:4px 8px 4px 8px'><table width='100%' cellspacing=0 cellpadding=0 "
                    f"style='font-size:13px'>{cols}{rows}</table></td></tr></table>")

        self.log.setHtml("".join(group(g) for g in reversed(self._log_sessions)))
        self.log.verticalScrollBar().setValue(0)

    # --- 自訂操作: the simple editor (2026-10-16, the user's design): a row per spoken phrase, grouped ---
    def _rules_page(self) -> QWidget:
        self.rules_body = QVBoxLayout()
        self.rules_body.setSpacing(6)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 8, 0)
        v.addLayout(self.rules_body)
        v.addStretch(1)
        self.rules_scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        self.rules_scroll.setWidget(inner)
        self.rules_scroll.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self.rules_scroll, 1)
        return page

    def refresh_rules(self):
        """Rows from cfg.rules, the spoken operations."""
        rs = self.cfg.rules
        # one row per action: phrases with the same step share a row (復原、撤銷)
        self._own = []   # [phrases, step type, value]
        for r in rs:
            if not (r.enabled and rules.spoken_ok(r)):
                continue
            st = r.steps[0]
            row = next((o for o in self._own if (o[1], o[2]) == (st.type, st.value)), None)
            if row is None:
                self._own.append([r.phrase, st.type, st.value])
            else:
                row[0] = "、".join(x for x in (row[0], r.phrase) if x)
        for kind, value in _BUILT_IN:   # a default turned off (its phrase left empty) stays listed
            if not any((o[1], o[2]) == (kind, value) for o in self._own):
                self._own.append(["", kind, value])
        self._draw_rules()

    def _draw_rules(self):
        bar = self.rules_scroll.verticalScrollBar()
        pos = bar.value()
        _clear_layout(self.rules_body)
        note = QLabel("整句只說這些話時才執行。可以填好幾種說法，用「、」分開。")
        note.setStyleSheet("color: gray")
        self.rules_body.addWidget(_with_info(note, "「左右輸入文字」：說出時在游標左右加入這兩段文字，游標留在中間；"
                                                   "有選取文字時加在選取的文字兩邊"))
        self._own.sort(key=_place)   # by what they do (stable: rows of one kind keep their order)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        line, group = 0, None
        for row in self._own:
            if _place(row)[0] != group:
                group = _place(row)[0]
                head = _heading(_GROUPS[group])
                head.setStyleSheet("font-weight: bold; color: #5F6670; padding-top: 6px")
                grid.addWidget(head, line, 0, 1, 6)
                line += 1
            i, line = line, line + 1
            edit = QLineEdit(row[0], placeholderText="要說的話")
            edit.textEdited.connect(lambda t, r=row: (r.__setitem__(0, t), self._rules_edited()))
            fixed = _built_in(row)
            grid.addWidget(QLabel("說 "), i, 0)
            grid.addWidget(edit, i, 1)
            grid.addWidget(QLabel(" 就會"), i, 2)
            if fixed:   # a default: what it does in words, only the phrase is edited
                edit.setPlaceholderText("（不使用）")
                does = QLabel(_does(row[1], row[2]), wordWrap=True)
                does.setStyleSheet("color: #5F6670")
                grid.addWidget(does, i, 3, 1, 2)
                continue
            current = row[2] if row[1] == rules.COMMAND else row[1]
            # a command a default row already does is not offered again (one more phrase goes in that row)
            kind = _combo([a for a in SPOKEN_ACTIONS if a[0] not in _BUILT_IN_COMMANDS or a[0] == current], current)
            kind.setMinimumContentsLength(6)
            kind.currentIndexChanged.connect(lambda _, k=kind, r=row: self._own_type(r, k.currentData()))
            if row[1] == rules.KEYS:
                value = KeyCapture(row[2])
                value.captured.connect(lambda t, r=row: (r.__setitem__(2, t), self._rules_edited()))
            elif row[1] == rules.TEXT:
                value = QLineEdit(row[2], placeholderText="要輸入的文字")
                value.textEdited.connect(lambda t, r=row: (r.__setitem__(2, t), self._rules_edited()))
            elif row[1] == rules.WRAP:
                # two boxes: what goes left and right of the caret, or of the selected text
                pair = list(row[2]) if isinstance(row[2], (list, tuple)) and len(row[2]) == 2 else ["", ""]
                row[2] = pair
                value = QWidget()
                h = QHBoxLayout(value)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(4)
                for k, hint in ((0, "左邊"), (1, "右邊")):
                    box = QLineEdit(pair[k], placeholderText=hint)
                    box.textEdited.connect(lambda t, r=row, k=k: (r[2].__setitem__(k, t), self._rules_edited()))
                    h.addWidget(box)
            else:
                value = QLabel(_COMMAND_NOTES.get(row[2], ""))
                value.setStyleSheet("color: gray")
            value.setMinimumWidth(90)
            grid.addWidget(kind, i, 3)
            grid.addWidget(value, i, 4)
            grid.addWidget(_remove_button("刪除這條", lambda _=False, r=row: self._remove_own(r)), i, 5)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(4, 1)
        self.rules_body.addLayout(grid)
        add = QPushButton("＋ 新增口說操作", flat=True, clicked=self._add_own)
        add_row = QHBoxLayout()
        add_row.addWidget(add)
        add_row.addStretch()
        self.rules_body.addLayout(add_row)
        self.spoken_problems = _problem_label()
        self.rules_body.addWidget(self.spoken_problems)
        self._show_problems()
        QTimer.singleShot(0, lambda: bar.setValue(pos))

    def _collect_rules(self) -> list:
        out = []
        for text, step_type, value in self._own:
            for phrase in rules.phrases(text) or [""]:
                out.append(Rule(rules.SPEECH, phrase=phrase, steps=[Step(step_type, value)]))
        return out

    def _rules_edited(self):
        self.cfg.rules = self._collect_rules()
        self._save()
        self._show_problems()

    def _row_problems(self) -> list:
        """(row, text) for each rule with a problem (rules.problems: it is skipped); a default left empty is off."""
        pairs = []
        for row in self._own:
            for phrase in rules.phrases(row[0]) or [""]:
                pairs.append((row, Rule(rules.SPEECH, phrase=phrase, steps=[Step(row[1], row[2])])))
        rs = [r for _, r in pairs]
        out = []
        for row, r in pairs:
            if not rules.normalize(r.phrase) and _built_in(row):
                continue
            text = "、".join(rules.problems(r, rs))
            if text:
                out.append((row, f"「{r.phrase or '（空白）'}」：{text}"))
        return out

    def _warn_rules(self):
        """The 自訂操作 tab comes into view: the problems of now are shown (2026-10-16, the user's request: only
        then, so a row just added and not filled in yet does not bring a warning)."""
        self._warn_rows = [row for row, _ in self._row_problems()]
        self._show_problems()

    def _show_problems(self):
        """The problems the rows cannot show on their own, of the rows that had them when the tab came into view: one
        fixed goes at once, a new one waits until the tab is opened again."""
        if not hasattr(self, "spoken_problems"):
            return
        spoken = [text for row, text in self._row_problems()
                  if any(row is w for w in getattr(self, "_warn_rows", ()))]
        self.spoken_problems.setText("\n".join(f"⚠ {t}" for t in spoken))
        self.spoken_problems.setVisible(bool(spoken))

    def _own_type(self, row: list, kind: str):
        row[1], row[2] = (rules.COMMAND, kind) if kind in (rules.UNDO, rules.STOP) + rules.EDIT_COMMANDS \
            else (kind, ["", ""]) if kind == rules.WRAP else (kind, "")
        self._rules_edited()
        self._draw_rules()

    def _add_own(self):
        self._own.append(["", rules.KEYS, ""])
        self._rules_edited()
        self._draw_rules()
        bar = self.rules_scroll.verticalScrollBar()
        QTimer.singleShot(50, lambda: bar.setValue(bar.maximum()))

    def _remove_own(self, row: list):
        self._own.remove(row)
        self._rules_edited()
        self._draw_rules()

