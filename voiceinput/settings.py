"""Settings window in four tabs: 一般 (general), 辨識紀錄 (live transcript log), 自訂操作 (custom operations,
rules.py) and 詞庫 (hotwords.py, the UI name for hotwords since 2026-10-13), in four sections one open at a time:
term packs to tick (packs.py), every listed word with its 優先度 (−100% .. +100%, 0 does nothing; stored as 0 ..
200%; read only); 選字記憶 (the smart picks, memory.py); English replacements (hotword aliases). Each list is dated,
sortable, and its entries removable. Every change is applied and saved immediately."""
import html
import os

from pypinyin import lazy_pinyin
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen, QTextDocument
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QTabWidget, QTextBrowser, QToolButton,
                               QToolTip, QVBoxLayout, QWidget)

from . import audio, cues, hotwords, packs, recordings, rules
from . import glow as glowmod
from .config import GESTURE_TIME_RANGE
from .memory import BOUNDARY
from .keys import KEY_TRIGGERS, MOUSE_TRIGGERS, combo_text, is_modifier
from .rules import Rule, Step

GESTURES = [(rules.TAP, "按一下"), (rules.DOUBLE, "連按兩下"), (rules.HOLD, "按住")]

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
    label = QLabel(added[:10], toolTip=f"加入時間：{added}")
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
    b = QPushButton("✕", toolTip=tip, clicked=slot)
    b.setFixedWidth(28)
    return b


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
        self.tabs.addTab(self._log_page(), "辨識紀錄")
        self.tabs.addTab(self._rules_page(), "自訂操作")
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
        self.punct.setToolTip("逗號、句號、句點、問號、驚嘆號、感嘆號、頓號、分號、冒號、點點點、刪節號、省略號；"
                              "整句只有這個名字才算，例如「逗號很重要」照常輸入")
        self.period_comma = QCheckBox("選取句號後講話，句號改成逗號並接上講的內容")
        self.period_comma.setToolTip("今天很好。明天見 → 選取「。」講「我們去公園」→ 今天很好，我們去公園。明天見")
        self.autostart = QCheckBox("開機時自動啟動")
        self.start_sound, self.stop_sound = QComboBox(), QComboBox()
        for box in (self.start_sound, self.stop_sound):
            for cue_id, name, *_sources in cues.SOUNDS:
                box.addItem(name, cue_id)
            box.addItem("無", "")
        self.start_sound.setToolTip("確定開始錄音時播放（按住約 0.3 秒，連按兩下不會響）；選了會先播一次")
        self.stop_sound.setToolTip("錄音結束時播放；選了會先播一次")
        # a set picks both sounds at once; 自定義 shows a drop-down for each (the user's design, 2026-10-13)
        self.sound_set = QComboBox(toolTip="同一組的開始音與結束音；選「自定義」可分別挑選")
        for cue_id, name, *_sources in cues.SOUNDS:
            self.sound_set.addItem(name, cue_id)
        self.sound_set.addItem("無", "")
        self.sound_set.addItem("自定義", None)
        self._set_timer = QTimer(self, singleShot=True,
                                 timeout=lambda: cues.play(self._set_timer.property("cue"), "stop"))
        self.sound_listen = QPushButton("試聽", clicked=self._play_sounds, toolTip="依序播放開始音與結束音")
        self.sound_listen.setFixedWidth(44)
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
        self.stop_at = QComboBox(toolTip="開了「錄音時暫時靜音電腦音效」時，停止錄音就恢復聲音，好播結束音")
        self.stop_at.addItem("停止錄音時", "stop")
        self.stop_at.addItem("文字輸入完成時", "done")
        stop_at_row = QHBoxLayout()
        stop_at_row.addWidget(QLabel("結束音在"))
        stop_at_row.addWidget(self.stop_at)
        stop_at_row.addWidget(QLabel("播放"))
        stop_at_row.addStretch()
        self.commit_at = QComboBox(toolTip="停頓時字會先打出來並修正；定稿後才固定下來")
        self.commit_at.addItem("講指令或關錄音時", "command")
        self.commit_at.addItem("每次停頓時", "pause")
        self.mute = QCheckBox("錄音時暫時靜音電腦音效")
        self.mute.setToolTip("麥克風開著時把喇叭靜音，關閉麥克風後恢復；原本就靜音的話不會動")
        self.describe = QCheckBox("說「詞＋的＋字」時只輸入那個字，例如「節日的節」")
        self.describe.setToolTip("整句剛好是「某個詞的某個字」才算，輸入的是詞裡讀音相同的那個字")
        self.send_on_stop = QCheckBox("用按鍵關閉麥克風時自動送出（按 Enter）")
        self.stop_on_send = QCheckBox("說「送出」時關閉麥克風")
        self.stop_on_send.setToolTip("說出會按 Enter 的指令（例如「送出」）後，麥克風跟著關掉；沒勾的話送出後繼續聽")
        self.spin = QCheckBox("錄音中正在辨識時，紅點旋轉")
        self.spin.setToolTip("講完一段、程式還在辨識時，錄音指示的紅點外會有一圈在轉")
        self.show_pill = QCheckBox("錄音時顯示指示器（底部的小膠囊）")
        self.show_pill.setToolTip("關掉後，麥克風開著只靠提示音和螢幕邊緣光暈（有開的話）提醒你")
        self.glow = QComboBox(toolTip="麥克風開著時，螢幕四周亮起一圈光，講話時會變亮；選了會先亮一下讓你看")
        self.glow.addItem("關閉", "")
        for st in glowmod.STYLES:
            self.glow.addItem(st.name, st.id)
        self.auto_off = QComboBox(toolTip="麥克風開著卻一直沒聽到人聲時自動關掉，避免忘了關；關掉時播結束音，不按 Enter")
        self.auto_off.addItem("不自動關閉", 0)
        for m in (1, 3, 5, 10, 30):
            self.auto_off.addItem(f"{m} 分鐘沒講話", m)
        self.send_on_stop.setToolTip("定稿後按 Enter；說「送出」關閉時不會再按一次，這次沒有打出任何字時也不會按")
        # development only, to be removed before release (the user's plan): recordings.py
        self.keep_audio = QCheckBox("保存錄音（測試用）")
        self.keep_audio.setToolTip("每句話存成 wav，並記下辨識結果與之後的選字、刪除，用來以真實聲音檢查辨識；不會自動刪除")
        folder = QPushButton("開啟錄音資料夾", clicked=self._open_recordings)
        audio_row = QHBoxLayout()
        audio_row.addWidget(self.keep_audio)
        audio_row.addWidget(folder)
        audio_row.addStretch()
        self.status = QLabel()
        self.status.setStyleSheet("color: gray")
        self.status.setWordWrap(True)

        form = QFormLayout()
        form.addRow("麥克風", self.mic)
        form.addRow("定稿時機", self.commit_at)
        form.addRow("自動關閉麥克風", self.auto_off)
        form.addRow("螢幕邊緣光暈", self.glow)
        form.addRow("提示音", sound_row)
        form.addRow("", stop_at_row)
        form.addRow("", self.mute)
        form.addRow("", self.punct)
        # form.addRow("", self.period_comma)   # not carried over to continuous listening yet
        form.addRow("", self.describe)
        form.addRow("", self.send_on_stop)
        form.addRow("", self.stop_on_send)
        form.addRow("", self.spin)
        form.addRow("", self.show_pill)
        form.addRow("", self.autostart)
        form.addRow("開發測試", audio_row)
        page = QWidget()
        v = QVBoxLayout(page)
        v.addLayout(form)
        v.addStretch(1)
        v.addWidget(self.status)

        self.mic.currentIndexChanged.connect(self._apply)
        self.start_sound.currentIndexChanged.connect(lambda: self._sound_changed(self.start_sound, "start"))
        self.stop_sound.currentIndexChanged.connect(lambda: self._sound_changed(self.stop_sound, "stop"))
        self.sound_set.currentIndexChanged.connect(self._sound_set_changed)
        self.stop_at.currentIndexChanged.connect(self._apply)
        self.commit_at.currentIndexChanged.connect(self._apply)
        self.auto_off.currentIndexChanged.connect(self._apply)
        self.glow.currentIndexChanged.connect(self._glow_changed)
        for box in (self.punct, self.period_comma, self.describe, self.send_on_stop, self.stop_on_send, self.spin, self.show_pill,
                    self.autostart,
                    self.mute, self.keep_audio):
            box.toggled.connect(self._apply)
        return page

    def load_values(self):
        self._loading = True
        self.mic.setCurrentIndex(max(0, self.mic.findData(self.cfg.mic)))
        self.punct.setChecked(self.cfg.punctuation_names)
        self.period_comma.setChecked(self.cfg.period_to_comma)
        self.autostart.setChecked(self.cfg.autostart)
        self.mute.setChecked(self.cfg.mute_while_recording)
        self.describe.setChecked(self.cfg.describe_char)
        self.send_on_stop.setChecked(self.cfg.send_on_stop)
        self.stop_on_send.setChecked(self.cfg.stop_on_send)
        self.spin.setChecked(self.cfg.spin_while_decoding)
        self.show_pill.setChecked(self.cfg.show_indicator)
        self.keep_audio.setChecked(self.cfg.save_recordings)
        self.start_sound.setCurrentIndex(max(0, self.start_sound.findData(self.cfg.start_sound)))
        self.stop_sound.setCurrentIndex(max(0, self.stop_sound.findData(self.cfg.stop_sound)))
        self.stop_at.setCurrentIndex(max(0, self.stop_at.findData(self.cfg.stop_sound_at)))
        self.commit_at.setCurrentIndex(max(0, self.commit_at.findData(self.cfg.commit_at)))
        self.glow.setCurrentIndex(max(0, self.glow.findData(self.cfg.glow)))
        i = self.auto_off.findData(self.cfg.auto_off_minutes)
        if i < 0:   # a value set by hand in config.json
            self.auto_off.addItem(f"{self.cfg.auto_off_minutes} 分鐘沒講話", self.cfg.auto_off_minutes)
            i = self.auto_off.count() - 1
        self.auto_off.setCurrentIndex(i)
        self.gesture_time.setValue(self.cfg.gesture_time)
        same = self.cfg.start_sound == self.cfg.stop_sound
        self.sound_set.setCurrentIndex(self.sound_set.findData(self.cfg.start_sound) if same
                                       else self.sound_set.count() - 1)
        self._show_sounds()
        self._loading = False
        self.refresh_rules()
        self.refresh_hotwords()

    def set_status(self, text: str):
        self.status.setText(text)

    def _apply(self):
        if self._loading:
            return
        self.cfg.mic = self.mic.currentData()
        self.cfg.punctuation_names = self.punct.isChecked()
        self.cfg.period_to_comma = self.period_comma.isChecked()
        self.cfg.autostart = self.autostart.isChecked()
        self.cfg.mute_while_recording = self.mute.isChecked()
        self.cfg.describe_char = self.describe.isChecked()
        self.cfg.send_on_stop = self.send_on_stop.isChecked()
        self.cfg.stop_on_send = self.stop_on_send.isChecked()
        self.cfg.spin_while_decoding = self.spin.isChecked()
        self.cfg.show_indicator = self.show_pill.isChecked()
        self.cfg.save_recordings = self.keep_audio.isChecked()
        self.cfg.start_sound = self.start_sound.currentData()
        self.cfg.stop_sound = self.stop_sound.currentData()
        self.cfg.stop_sound_at = self.stop_at.currentData()
        self.cfg.commit_at = self.commit_at.currentData()
        self.cfg.glow = self.glow.currentData()
        self.cfg.auto_off_minutes = self.auto_off.currentData()
        self._save()

    def _glow_changed(self):
        self._apply()
        if not self._loading and self.glow.currentData():
            self.glow_preview.emit(self.glow.currentData())

    def _sound_changed(self, box, kind: str):
        if not self._loading:
            cues.play(box.currentData(), kind)
            self._show_sounds()
        self._apply()

    def _custom(self) -> bool:
        return self.sound_set.currentData() is None

    def _show_sounds(self):
        """The 開始 / 結束 drop-downs only for 自定義; 試聽 and the timing only when there is something to play."""
        self.custom_sounds.setVisible(self._custom())
        self.sound_listen.setEnabled(bool(self.start_sound.currentData() or self.stop_sound.currentData()))
        self.stop_at.setEnabled(bool(self.stop_sound.currentData()))

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
        if stop:
            self._set_timer.setProperty("cue", stop)
            self._set_timer.start(int(((cues.duration(start, "start") + _SET_PAUSE) if start else 0) * 1000))

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
        self.pack_list, no_packs, pack_body = _card_list("")
        no_packs.hide()
        self._pack_stamp = None

        # typing a word here replaced the 選字 menu's input box (2026-10-16, the user's choice): 200%, like before
        self.hw_input = QLineEdit(placeholderText="輸入詞語加入詞庫")
        self.hw_input.returnPressed.connect(self._add_hotword)
        add = QPushButton("加入")
        add.clicked.connect(self._add_hotword)
        hw_top = QVBoxLayout()
        add_row = QHBoxLayout()
        add_row.addWidget(self.hw_input, 1)
        add_row.addWidget(add)
        hw_top.addLayout(add_row)
        hw_top.addLayout(self._sort_row(HOTWORD_SORTS, "hotword_sort"))
        self.hw_list, self.hw_empty, hw_body = _card_list(
            "詞庫裡還沒有詞。選字時選了詞語（被換掉的詞也會列出，優先度較低），或在上面輸入詞語，就會加到這裡。", hw_top)
        self.pick_list, self.pick_empty, pick_body = _card_list(
            "還沒有記下的字。用選字換掉單一個中文字，就會記下它前後的字，之後在同樣的前後文自動換成那個字。",
            self._sort_row(PICK_SORTS, "pick_sort"))
        self.alias_list, self.alias_empty, alias_body = _card_list(
            "還沒有強制替換。選字或打字把英文換成另一種拼法的詞（例如 Dipsick 換成 DeepSeek），之後辨識出舊拼法就一律改成新的。",
            self._sort_row(ALIAS_SORTS, "alias_sort"))

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

    def _sort_row(self, sorts, setting: str) -> QHBoxLayout:
        """排序 and its drop-down; the choice is saved as cfg.<setting>."""
        combo = _combo(sorts, getattr(self.cfg, setting))
        combo.currentIndexChanged.connect(lambda: self._sort_changed(setting, combo.currentData()))
        row = QHBoxLayout()
        row.addWidget(QLabel("排序"))
        row.addWidget(combo)
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
            box.setToolTip(f"整包的詞以優先度 {_shown(packs.PCT)} 辨識；選字選過或被換掉的詞會列在詞庫列表，以那裡的優先度為準")
            box.toggled.connect(lambda on, i=pack.id: self._toggle_pack(i, on))
            box.setMinimumWidth(150)
            row.addWidget(box)
            terms = QLabel("、".join(pack.words[:_PACK_SHOWN]) + ("…" if len(pack.words) > _PACK_SHOWN else ""))
            terms.setStyleSheet("color: gray")
            terms.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # cut, never widening the window
            terms.setToolTip("、".join(pack.words))
            row.addWidget(terms, 1)
            edit = QPushButton("編輯", toolTip="用記事本開啟這個詞包的文字檔：一行一個詞，存檔後下次說話就生效",
                               clicked=lambda _=False, i=pack.id: self._edit_pack(i))
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
            percent.setToolTip("優先度：0% 不影響辨識；正的越容易辨識成這個詞，負的越不容易。選字選到會提高，被換掉會降低")
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
            label.setToolTip(f"聽成 {e['key']}、前後是這些字時，換成「{e['value']}」")
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
            label.setToolTip(f"辨識出「{alias}」時一律改成「{word}」")
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
        text = "" if row is None else "複製這句" if url.scheme() == "copy" else \
            "\n".join(x for x in (row["tag"], row["tip"]) if x)
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
            return (f"<tr><td valign=top width=54 style='color:{gray}; font-size:11px; padding:5px 0 5px 0; "
                    f"font-family:Consolas,monospace'><a href='{tip}' style='color:{gray}'>{r['time']}</a></td>"
                    f"<td valign=top width='36%' style='padding:3px 8px 3px 0'>"
                    + (f"<div style='padding:2px 0'><a href='{tip}' style='color:{gray}'>{heard}</a></div>" if event
                       else f"<table cellspacing=0 cellpadding=0><tr><td bgcolor='#EEF1F5' style='padding:2px 7px'>"
                       f"<a href='{tip}' style='color:{ink}'>{heard}</a></td></tr></table>" if heard else "")
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

    # --- 自訂操作: the simple editor (2026-10-16, the user's design): a row per thing a key does, a row per phrase ---
    def _gesture_time_changed(self, value: float):
        if not self._loading:
            self.cfg.gesture_time = round(value, 2)
            self._save()

    def _rules_page(self) -> QWidget:
        reset = QPushButton("還原預設", clicked=self._reset_rules)
        self.gesture_time = QDoubleSpinBox(decimals=2, singleStep=0.05, suffix=" 秒", minimum=GESTURE_TIME_RANGE[0],
                                           maximum=GESTURE_TIME_RANGE[1], value=self.cfg.gesture_time)
        self.gesture_time.setToolTip("按著超過這個時間算「按住」；放開後在這個時間內再按一次算「連按兩下」")
        self.gesture_time.valueChanged.connect(self._gesture_time_changed)

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

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("按住／連按判定時間"))
        bottom.addWidget(self.gesture_time)
        bottom.addStretch()
        bottom.addWidget(reset)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self.rules_scroll, 1)
        layout.addLayout(bottom)
        return page

    def refresh_rules(self):
        """Rows from cfg.rules: the key rows, the built-in spoken rows, the user's own spoken rows."""
        rs = self.cfg.rules
        self._keys = {}
        for command, when, _ in rules.KEY_ROWS:
            r = rules.key_rule(rs, command, when)
            self._keys[command] = [r.key if r else "", r.gesture if r else rules.TAP]
        spoken = {kind: [] for kind, _, _ in rules.SPOKEN}
        self._own = []   # [phrase, step type, value]
        for r in rs:
            kind = rules.spoken_kind(r) if r.enabled else None
            if kind:
                spoken[kind].append(r.phrase)
            elif kind == "":
                self._own.append([r.phrase, r.steps[0].type, r.steps[0].value])
        self._spoken = {k: "、".join(v) for k, v in spoken.items()}
        self._draw_rules()

    def _draw_rules(self):
        bar = self.rules_scroll.verticalScrollBar()
        pos = bar.value()
        _clear_layout(self.rules_body)
        self.rules_body.addWidget(_heading("按鍵"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        keys = [("", "不使用")] + [(k, f"滑鼠{label}") for k, label in MOUSE_TRIGGERS.items()] + \
            [(k, label) for k, (label, _) in KEY_TRIGGERS.items()]
        for i, (command, _, label) in enumerate(rules.KEY_ROWS):
            state = self._keys[command]
            key = _combo(keys, state[0])
            gesture = _combo(GESTURES, state[1])
            gesture.setEnabled(bool(state[0]))
            key.currentIndexChanged.connect(
                lambda _, k=key, g=gesture, st=state: (st.__setitem__(0, k.currentData()),
                                                       g.setEnabled(bool(k.currentData())), self._rules_edited()))
            gesture.currentIndexChanged.connect(
                lambda _, g=gesture, st=state: (st.__setitem__(1, g.currentData()), self._rules_edited()))
            grid.addWidget(key, i, 0)
            grid.addWidget(gesture, i, 1)
            grid.addWidget(QLabel(label), i, 2)
        grid.setColumnStretch(3, 1)
        self.rules_body.addLayout(grid)
        self.key_problems = _problem_label()
        self.rules_body.addWidget(self.key_problems)

        self.rules_body.addSpacing(8)
        self.rules_body.addWidget(_heading("口說"))
        note = QLabel("整句只說這些話時才執行。可以填好幾種說法，用「、」分開；清空就不使用。")
        note.setStyleSheet("color: gray")
        note.setWordWrap(True)
        self.rules_body.addWidget(note)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        for i, (kind, _, label) in enumerate(rules.SPOKEN):
            edit = QLineEdit(self._spoken[kind], placeholderText="不使用")
            edit.textEdited.connect(lambda t, k=kind: (self._spoken.__setitem__(k, t), self._rules_edited()))
            grid.addWidget(QLabel("說「"), i, 0)
            grid.addWidget(edit, i, 1)
            grid.addWidget(QLabel("」就會"), i, 2)
            grid.addWidget(QLabel(label), i, 3, 1, 3)
        n = len(rules.SPOKEN)
        if self._own:
            own = QLabel("自訂")
            own.setStyleSheet("color: gray")
            grid.addWidget(own, n, 0, 1, 6)
        for j, row in enumerate(self._own):
            i = n + 1 + j
            edit = QLineEdit(row[0], placeholderText="要說的話")
            edit.textEdited.connect(lambda t, r=row: (r.__setitem__(0, t), self._rules_edited()))
            kind = _combo([(rules.KEYS, "按鍵"), (rules.TEXT, "輸入文字")], row[1])
            kind.currentIndexChanged.connect(lambda _, k=kind, r=row: self._own_type(r, k.currentData()))
            if row[1] == rules.KEYS:
                value = KeyCapture(row[2])
                value.captured.connect(lambda t, r=row: (r.__setitem__(2, t), self._rules_edited()))
            else:
                value = QLineEdit(row[2], placeholderText="要輸入的文字")
                value.textEdited.connect(lambda t, r=row: (r.__setitem__(2, t), self._rules_edited()))
            value.setMinimumWidth(90)
            grid.addWidget(QLabel("說「"), i, 0)
            grid.addWidget(edit, i, 1)
            grid.addWidget(QLabel("」就會"), i, 2)
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
        for command, when, _ in rules.KEY_ROWS:
            key, gesture = self._keys[command]
            if key:
                source = rules.MOUSE if key in MOUSE_TRIGGERS else rules.KEY
                out.append(Rule(source, key, gesture=gesture, when=when, steps=[Step(rules.COMMAND, command)]))
        for kind, (step_type, value), _ in rules.SPOKEN:
            for phrase in rules.phrases(self._spoken[kind]):
                out.append(Rule(rules.SPEECH, phrase=phrase, steps=[Step(step_type, value)]))
        for phrase, step_type, value in self._own:
            out.append(Rule(rules.SPEECH, phrase=phrase.strip(), steps=[Step(step_type, value)]))
        return out

    def _rules_edited(self):
        self.cfg.rules = self._collect_rules()
        self._save()
        self._show_problems()

    def _show_problems(self):
        """Clashes the rows cannot show on their own; a rule with a problem is skipped (rules.problems)."""
        rs = self.cfg.rules
        keys = []
        if not self._keys[rules.RECORD][0]:
            keys.append("「開關麥克風」不使用時無法語音輸入")
        names = dict(GESTURES)
        labels = {c: label for c, _, label in rules.KEY_ROWS}
        for i, (a, wa, _) in enumerate(rules.KEY_ROWS):
            for b, wb, _ in rules.KEY_ROWS[i + 1:]:
                if self._keys[a][0] and self._keys[a] == self._keys[b] and wa == wb:
                    keys.append(f"「{labels[a]}」和「{labels[b]}」是同一個鍵{names[self._keys[a][1]]}，"
                                f"只有「{labels[a]}」會生效")
        spoken = []
        for r in rs:
            if r.source == rules.SPEECH:
                text = "、".join(rules.problems(r, rs))
                if text:
                    spoken.append(f"「{r.phrase or '（空白）'}」：{text}")
        for label, items in ((self.key_problems, keys), (self.spoken_problems, spoken)):
            label.setText("\n".join(f"⚠ {t}" for t in items))
            label.setVisible(bool(items))

    def _own_type(self, row: list, kind: str):
        row[1], row[2] = kind, ""
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

    def _reset_rules(self):
        if QMessageBox.question(self, "還原預設", "把自訂操作還原成預設？目前的設定會被取代。") == QMessageBox.Yes:
            self.cfg.rules = rules.defaults()
            self._save()
            self.refresh_rules()

