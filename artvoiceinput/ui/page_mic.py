"""麥克風: the ways to turn listening on (hotkey, clicking into a text box, the floating button), when it turns off,
and the device."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QConicalGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QCheckBox, QComboBox, QGridLayout, QVBoxLayout, QWidget

from .. import audio
from ..keys import hotkey_label
from . import theme
from .kit import (Choice, Info, Pill, Switch, T, button, card, dim, hbox, label, prop, sep, titled, vbox)

NEARS = [("", "不使用", "點進輸入框時什麼都不做"),
         ("bubble", "語音氣泡", "點擊處旁出現小按鈕，點一下開麥克風"),
         ("listen", "自動開麥克風", "直接開麥克風，離開輸入框時關閉")]
OFFS = [(0, "不自動關閉")] + [(m, f"{m} 分鐘") for m in (1, 3, 5, 10, 30)]


class KeyCap(QWidget):
    """The hotkey as a big keycap; hatched when there is none; outlined in orange while waiting for a press."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(54)
        self.text, self.state = "", "none"

    def set(self, text: str, state: str):
        self.text, self.state = text, state
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        if self.state == "key":
            p.setPen(QPen(T("line"), 1))
            p.setBrush(T("line"))
            p.drawRoundedRect(r, 8, 8)
            p.setPen(Qt.NoPen)
            p.setBrush(T("tile2"))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -3), 7, 7)
            p.setPen(T("ink"))
            p.setFont(theme.font(17, 600, num=True))
        elif self.state == "wait":
            p.setPen(QPen(T("acc"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            p.setPen(T("acct"))
            p.setFont(theme.font(14, 500))
        else:
            p.setPen(QPen(T("line"), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 8, 8)
            p.save()
            p.setClipRect(r.adjusted(2, 2, -2, -2))
            p.setPen(QPen(T("tile2"), 6))
            for x in range(-60, self.width() + 60, 12):
                p.drawLine(x, self.height(), x + self.height(), 0)
            p.restore()
            p.setPen(T("muted"))
            p.setFont(theme.font(14, 500))
        p.drawText(r, Qt.AlignCenter, self.text)


class Option(QAbstractButton):
    """A radio row: a ring (filled orange when picked), a name and a line under it."""

    def __init__(self, name: str, desc: str):
        super().__init__()
        self.name, self.desc = name, desc
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(46)
        self.setAccessibleName(name)
        self._over = False

    def enterEvent(self, e):
        self._over = True
        self.update()

    def leaveEvent(self, e):
        self._over = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        if self.isChecked() or self._over:
            p.setPen(Qt.NoPen)
            p.setBrush(T("accbg") if self.isChecked() else T("tile2"))
            p.drawRoundedRect(r, 6, 6)
        c = r.center().y()
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(T("acc"))
            p.drawEllipse(QRectF(8, c - 8, 16, 16))
            p.setBrush(T("tile"))
            p.drawEllipse(QRectF(13, c - 3, 6, 6))
        else:
            p.setPen(QPen(T("muted"), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(8.75, c - 7.25, 14.5, 14.5))
        p.setPen(T("ink"))
        p.setFont(theme.font(13.5, 500))
        p.drawText(QRectF(34, 5, r.width() - 40, 19), Qt.AlignLeft | Qt.AlignVCenter, self.name)
        p.setPen(T("muted"))
        p.setFont(theme.font(12))
        fm = p.fontMetrics()
        p.drawText(QRectF(34, 24, r.width() - 40, 17), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(self.desc, Qt.ElideRight, int(r.width() - 40)))


class FloatSample(QWidget):
    """A text box and the floating button near it, faint while the button is off."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(60)
        self.on = True

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(T("line"), 1))
        p.setBrush(T("tile2"))
        p.drawRoundedRect(r, 6, 6)
        p.setBrush(T("tile"))
        p.drawRoundedRect(QRectF(12, 12, min(120, r.width() - 70), 36), 4, 4)
        p.setOpacity(1 if self.on else 0.25)
        orb = QRectF(r.right() - 18 - 28, r.bottom() - 12 - 28, 28, 28)
        g = QConicalGradient(orb.center(), 90)
        for i, c in enumerate(("#3d7bff", "#a259ff", "#ff4fa3", "#ff9f43", "#29d3ff", "#3d7bff")):
            g.setColorAt(i / 5, QColor(c))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(orb)
        hl = QRadialGradient(orb.center().x(), orb.top() + orb.height() * 0.38, orb.width() * 0.38)
        hl.setColorAt(0, QColor(255, 255, 255, 190))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hl))
        p.drawEllipse(orb)


class MicPage(QWidget):
    title = "麥克風"

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self._capturing = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        self.no_way = label("目前沒有任何方式能開麥克風，請至少開啟一種", warn=True)
        v.addLayout(hbox(label("開麥克風的方式", sh=True), self.no_way, None, spacing=10))
        grid = QGridLayout()
        grid.setSpacing(12)
        for i in range(3):
            grid.setColumnStretch(i, 1)

        # 快捷鍵
        self.hk_card, c = card()
        self.hk_pill = Pill()
        c.addLayout(hbox(label("快捷鍵", h3=True), Info(
            "按「設定按鍵」，再按下想用的鍵盤按鍵（可以加 Ctrl、Shift、Alt、Win）或滑鼠按鍵（左鍵以外）；按 Esc 或點滑鼠左鍵"
            "取消。之後按一下這個鍵就開麥克風，再按一下關。這個鍵原本的功能會被取代"), None, self.hk_pill, spacing=6))
        self.cap = KeyCap()
        c.addWidget(self.cap)
        c.addWidget(dim("按一下開，再按一下關；滑鼠側鍵也可以", wrap=True))
        c.addStretch(1)
        self.cap_button = button("設定按鍵", self._capture_clicked, pri=True)
        self.clear_button = button("清除", self._clear_hotkey)
        c.addLayout(hbox(self.cap_button, self.clear_button, spacing=8))
        grid.addWidget(self.hk_card, 0, 0)

        # 點進輸入框時
        self.near_card, c = card()
        self.near_pill = Pill()
        c.addLayout(hbox(label("點進輸入框時", h3=True), Info(
            "用滑鼠左鍵點進可以打字的地方時：\n・語音氣泡：點擊處旁出現小按鈕，點一下開麥克風；打字、捲動滾輪或點到不能打字的"
            "地方就收起來\n・自動開麥克風：直接開麥克風，點到不能打字的地方就關掉；用其他方式關掉後，再點一次輸入框就會重新"
            "打開"), None, self.near_pill, spacing=6))
        self.nears = {}
        box = vbox(spacing=2)
        for key, name, desc in NEARS:
            o = Option(name, desc)
            o.clicked.connect(lambda _=False, k=key: self._near(k))
            self.nears[key] = o
            box.addWidget(o)
        c.addLayout(box)
        c.addStretch(1)
        grid.addWidget(self.near_card, 0, 1)

        # 浮動按鈕
        self.float_card, c = card()
        self.float_switch = Switch(name="浮動按鈕")
        self.float_switch.toggled.connect(self._float)
        c.addLayout(hbox(label("浮動按鈕", h3=True), Info("停在螢幕上的按鈕，點一下開麥克風，拖到哪就留在哪；樣子和大小在"
                                                       "「外觀與聲音」設定"), None, self.float_switch, spacing=6))
        self.float_sample = FloatSample()
        c.addWidget(self.float_sample)
        c.addWidget(dim("停在螢幕上，點一下開麥克風，拖到哪就留在哪", wrap=True))
        self.float_text_only = QCheckBox("未偵測到輸入區域時隱藏")
        self.float_text_only.setToolTip("勾選時，游標不在可以打字的地方就隱藏浮動按鈕；不勾就到處都顯示")
        self.float_hide = QCheckBox("錄音時隱藏按鈕")
        self.float_hide.setToolTip("勾選時，開麥克風時按鈕放大淡出，關掉後縮回來；不勾按鈕會留著，麥克風開著時再點一下就關掉")
        for b in (self.float_text_only, self.float_hide):
            b.setCursor(Qt.PointingHandCursor)
            b.toggled.connect(self._float_opts)
            c.addWidget(b)
        c.addStretch(1)
        grid.addWidget(self.float_card, 0, 2)
        v.addLayout(grid)

        v.addSpacing(8)
        v.addWidget(label("關閉與裝置", sh=True))
        grid2 = QGridLayout()
        grid2.setSpacing(12)
        grid2.setColumnStretch(0, 1)
        grid2.setColumnStretch(1, 1)
        off_card, c = card()
        c.addLayout(hbox(label("沒講話多久自動關閉", h3=True), Info("麥克風開著卻一直沒聽到人聲時自動關掉，避免忘了關；"
                                                              "關掉時播結束音"), None, spacing=6))
        self.offs = Choice(OFFS)
        self.offs.picked.connect(self._off)
        c.addWidget(self.offs)
        c.addWidget(sep())
        self.enter_switch = Switch(name="送出訊息後關閉")
        self.enter_switch.toggled.connect(self._enter)
        c.addLayout(hbox(titled("送出訊息後關閉", "按 Enter 或說「送出」之後；Shift+Enter 換行不算"), None,
                         self.enter_switch))
        c.addStretch(1)
        grid2.addWidget(off_card, 0, 0)
        dev_card, c = card()
        c.addWidget(label("使用的麥克風", h3=True))
        self.mic = QComboBox()
        self.mic.setCursor(Qt.PointingHandCursor)
        self.mic.addItem("系統預設", "")
        for name in audio.list_input_devices():
            self.mic.addItem(name, name)
        self.mic.currentIndexChanged.connect(self._mic)
        c.addWidget(self.mic)
        c.addWidget(sep())
        self.mute_switch = Switch(name="錄音時靜音電腦音效")
        self.mute_switch.toggled.connect(self._mute)
        c.addLayout(hbox(titled("錄音時靜音電腦音效", "關掉麥克風後恢復；原本就靜音的話不會動"), None, self.mute_switch))
        c.addStretch(1)
        grid2.addWidget(dev_card, 0, 1)
        v.addLayout(grid2)
        v.addStretch(1)

    # --- values ---
    def load(self):
        cfg = self.cfg
        self._show_hotkey()
        self._show_near()
        self.float_switch.set_quiet(cfg.show_float)
        self.float_text_only.setChecked(cfg.float_text_only)
        self.float_hide.setChecked(not cfg.float_keep)
        self._show_float()
        self.offs.set(cfg.auto_off_minutes)
        self.enter_switch.set_quiet(cfg.stop_on_enter)
        self.mute_switch.set_quiet(cfg.mute_while_recording)
        self.mic.blockSignals(True)
        self.mic.setCurrentIndex(max(0, self.mic.findData(cfg.mic)))
        self.mic.blockSignals(False)
        self._show_no_way()

    def summary(self) -> str:
        cfg = self.cfg
        parts = []
        if cfg.hotkey:
            parts.append(f"快捷鍵 {hotkey_label(cfg.hotkey)}")
        if cfg.show_bubble:
            parts.append("點擊處顯示語音氣泡")
        elif cfg.auto_listen:
            parts.append("點進輸入框自動開麥克風")
        if cfg.show_float:
            parts.append("浮動按鈕開著")
        return "，".join(parts) or "目前沒有開麥克風的方式"

    # --- 快捷鍵 (App._capture_hotkey takes the next press) ---
    def _capture_clicked(self):
        self._capturing = not self._capturing
        self._show_hotkey()
        self.win.capture_hotkey.emit(self._capturing)

    def hotkey_captured(self, spec):
        """The press captured (a hotkey spec), or None: cancelled (Esc, a left click)."""
        if not self._capturing:
            return
        self._capturing = False
        if spec:
            self.cfg.hotkey = spec
            self.win.save()
        self._show_hotkey()
        self._show_no_way()

    def stop_capture(self):
        if self._capturing:
            self._capturing = False
            self.win.capture_hotkey.emit(False)
            self._show_hotkey()

    def _clear_hotkey(self):
        self.stop_capture()
        self.cfg.hotkey = ""
        self.win.save()
        self._show_hotkey()
        self._show_no_way()

    def _show_hotkey(self):
        has = bool(self.cfg.hotkey)
        if self._capturing:
            self.cap.set("請按下按鍵…（Esc 取消）", "wait")
        elif has:
            self.cap.set(hotkey_label(self.cfg.hotkey), "key")
        else:
            self.cap.set("未設定", "none")
        self.cap_button.setText("取消" if self._capturing else "重新設定" if has else "設定按鍵")
        self.clear_button.setVisible(has and not self._capturing)
        self.hk_pill.set("已設定" if has else "未設定", has)
        prop(self.hk_card, live=has)

    # --- the rest ---
    def _near(self, key: str):
        self.cfg.show_bubble, self.cfg.auto_listen = key == "bubble", key == "listen"
        self.win.save()
        self._show_near()
        self._show_no_way()

    def _show_near(self):
        key = "listen" if self.cfg.auto_listen else "bubble" if self.cfg.show_bubble else ""
        for k, o in self.nears.items():
            o.setChecked(k == key)
        self.near_pill.set({"": "未使用", "bubble": "語音氣泡", "listen": "自動開"}[key], bool(key))
        prop(self.near_card, live=bool(key))

    def _float(self, on: bool):
        self.cfg.show_float = on
        self.win.save()
        self._show_float()
        self._show_no_way()

    def _float_opts(self):
        if self.win._loading:
            return
        self.cfg.float_text_only = self.float_text_only.isChecked()
        self.cfg.float_keep = not self.float_hide.isChecked()
        self.win.save()

    def _show_float(self):
        on = self.cfg.show_float
        self.float_sample.on = on
        self.float_sample.update()
        for b in (self.float_text_only, self.float_hide):
            b.setEnabled(on)
        prop(self.float_card, live=on)

    def _show_no_way(self):
        self.no_way.setVisible(not (self.cfg.hotkey or self.cfg.auto_listen or self.cfg.show_bubble
                                    or self.cfg.show_float))

    def _off(self, minutes):
        self.cfg.auto_off_minutes = minutes
        self.win.save()

    def _enter(self, on: bool):
        self.cfg.stop_on_enter = on
        self.win.save()

    def _mute(self, on: bool):
        self.cfg.mute_while_recording = on
        self.win.save()

    def _mic(self):
        self.cfg.mic = self.mic.currentData()
        self.win.save()
