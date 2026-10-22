"""麥克風: the ways to turn listening on (hotkey, clicking into a text box, the floating button), when it turns off,
and the device."""
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QVBoxLayout, QWidget)

from .. import audio
from ..keys import hotkey_label
from . import theme
from .illus import Illustration
from .kit import (Choice, Info, Pill, Switch, T, button, card, dim, hbox, label, prop, sep, titled, vbox)

NEARS = [("", "不使用", "點進輸入框時什麼都不做"),
         ("bubble", "語音氣泡", "點擊處旁出現小按鈕，點一下開麥克風"),
         ("listen", "自動開麥克風", "點進輸入框時直接開麥克風")]
# when the floating button shows (2026-10-22, the user's design: like NEARS, but any number ticked)
FLOATS = [("float_box", "偵測到輸入區域時顯示", "游標在可以打字的地方時顯示"),
          ("float_rec", "錄音時顯示", "變小轉快，點一下關麥克風"),
          ("float_away", "未偵測到輸入區域時顯示", "游標在不能打字的地方時也顯示")]
# small chips on one line (2026-10-21: the room went to the cards' illustrations)
OFFS = [(0, "不關閉")] + [(m, f"{m} 分") for m in (1, 3, 5, 10, 30)]
CUSTOM_MINUTES = (1, 240, 15)   # the 自訂 chip: lowest, highest, first offered
TEST_IDLE = "按「測試麥克風」後說幾句話，看看音量有沒有跟著動"
TEST_LISTENING = "正在聽，說幾句話試試看"
TEST_HEARD_TEXT = "聽得到你的聲音，燈格跟著說話亮起來就沒問題"
TEST_HEARD = 0.45   # a level this high (about -33 dBFS) counts as having heard speech


class LevelMeter(QWidget):
    """測試麥克風's meter, design I1 (2026-10-20, the user's pick): 24 segments lit from the left, the last six warmer
    (too loud), a tick at the recent peak that falls back slowly."""
    SEGMENTS = 24

    def __init__(self):
        super().__init__()
        self.setFixedHeight(18)
        self.level = 0.0          # 0..1, eased
        self.peak = 0.0
        self.on = False
        self.setAccessibleName("麥克風音量")

    def set(self, level: float, on: bool = True):
        self.on = on
        # quick to rise, slower to fall, like a VU meter
        self.level = level if level > self.level else self.level * 0.82 + level * 0.18
        self.peak = max(self.level, self.peak - 0.012)
        self.update()

    def reset(self):
        self.level = self.peak = 0.0
        self.on = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(T("line"), 1))
        p.setBrush(T("tile2"))
        p.drawRoundedRect(r, 4, 4)
        inner = r.adjusted(3, 3, -3, -3)
        gap = 3
        n = self.SEGMENTS
        w = (inner.width() - gap * (n - 1)) / n
        lit = round(self.level * n)
        p.setPen(Qt.NoPen)
        for i in range(n):
            seg = QRectF(inner.x() + i * (w + gap), inner.y(), w, inner.height())
            if self.on and i < lit:
                p.setBrush(QColor("#E0182D" if i >= n - 2 else "#FF8A3D" if i >= n - 6 else theme.ACCENT))
            else:
                p.setBrush(T("line"))
            p.drawRoundedRect(seg, 2, 2)
        if self.on and self.peak > 0.02:
            x = inner.x() + min(self.peak, 1.0) * inner.width()
            c = T("ink")
            c.setAlphaF(0.55)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(min(x, inner.right() - 3), inner.y(), 3, inner.height()), 1.5, 1.5)


class MinutesChip(QFrame):
    """自訂 at the end of the auto-off chips (2026-10-20, the user's design): a chip; picked, an orange chip holding
    a minutes field that can be typed in."""
    picked = Signal(int)

    def __init__(self):
        super().__init__(objectName="minchip")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedHeight(26)   # as high as the small chips beside it (24) and their border
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.chip = button("自訂", self._open, chip=True)
        self.chip.setProperty("small", True)
        self.box = QLineEdit(str(CUSTOM_MINUTES[2]), objectName="minutes")
        self.box.setValidator(QIntValidator(*CUSTOM_MINUTES[:2], self.box))
        self.box.setAlignment(Qt.AlignCenter)
        self.box.setFixedSize(34, 18)
        self.box.setFont(theme.font(12.5, 700, num=True))
        self.box.setAccessibleName("自訂分鐘數")
        self.box.editingFinished.connect(self._typed)
        self.unit = QLabel("分")
        self.unit.setFont(theme.font(12.5, 500))
        h.addWidget(self.chip)
        h.addWidget(self.box)
        h.addWidget(self.unit)
        self.setStyleSheet("QFrame#minchip[on=\"true\"] { background: %s; border-radius: 13px; }"
                           " QLineEdit#minutes { background: rgba(255,255,255,56); color: #FFFFFF; border: none;"
                           " border-radius: 4px; padding: 0; min-height: 0; selection-background-color: #FFFFFF;"
                           " selection-color: %s; } QLabel { color: #FFFFFF; background: transparent; }"
                           % (theme.ACCENT, theme.ACCENT))
        self.set(None)

    def set(self, minutes):
        """None: the plain 自訂 chip; a number: picked, showing it."""
        on = minutes is not None
        if on:
            self.box.setText(str(minutes))
        prop(self, on=on)   # before hiding the field: losing the focus it sends editingFinished
        self.layout().setContentsMargins(*((6, 0, 10, 0) if on else (0, 0, 0, 0)))
        self.chip.setVisible(not on)
        self.box.setVisible(on)
        self.unit.setVisible(on)
        self.updateGeometry()
        if self.parentWidget() is not None and self.parentWidget().layout() is not None:
            self.parentWidget().layout().invalidate()

    def _typed(self):
        # also sent when the field loses the focus because another chip was picked: then it is no longer picked
        if self.property("on"):
            self.picked.emit(self.value())

    def value(self) -> int:
        try:
            return min(max(int(self.box.text()), CUSTOM_MINUTES[0]), CUSTOM_MINUTES[1])
        except ValueError:
            return CUSTOM_MINUTES[2]

    def _open(self):
        self.set(self.value())
        self.picked.emit(self.value())
        self.box.setFocus()
        self.box.selectAll()

    def sizeHint(self):
        return self.layout().sizeHint()


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
    """A radio row: a ring (filled orange when picked), a name and a line under it; check: a box with a tick
    instead, for rows ticked independently."""

    def __init__(self, name: str, desc: str, check: bool = False):
        super().__init__()
        self.name, self.desc, self.check = name, desc, check
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
        if self.check:
            box = QRectF(8.75, c - 7.25, 14.5, 14.5)
            if self.isChecked():
                p.setPen(Qt.NoPen)
                p.setBrush(T("acc"))
                p.drawRoundedRect(box.adjusted(-0.75, -0.75, 0.75, 0.75), 4, 4)
                p.setPen(QPen(T("tile"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline([QPointF(12, c), QPointF(15, c + 3), QPointF(20.5, c - 3)])
            else:
                p.setPen(QPen(T("muted"), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(box, 3.5, 3.5)
        elif self.isChecked():
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


def _row(text: QWidget, switch: QWidget) -> QHBoxLayout:
    """A setting's name and line, then its switch: the text takes the room (its line stays on one line)."""
    h = hbox(text, switch)
    h.setStretch(0, 1)
    return h


class MicPage(QWidget):
    title = "麥克風"

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self._capturing = False
        self._cancelled_at = 0.0
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.no_way = label("目前沒有任何方式能開麥克風，請至少開啟一種", warn=True)
        v.addWidget(self.no_way)
        grid = QGridLayout()
        grid.setSpacing(12)
        for i in range(3):
            grid.setColumnStretch(i, 1)

        # 快捷鍵
        self.hk_card, c = card()
        self._illustrate(self.hk_card, c, "keys")
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
        self._illustrate(self.near_card, c, "box")
        self.near_pill = Pill()
        c.addLayout(hbox(label("點進輸入框時", h3=True), Info(
            "用滑鼠左鍵點進可以打字的地方時：\n・語音氣泡：點擊處旁出現小按鈕，點一下開麥克風；打字、捲動滾輪或點到不能打字的"
            "地方就收起來\n・自動開麥克風：在語音氣泡會出現的時候直接開麥克風（用鍵盤移進輸入框不算）"), None,
            self.near_pill, spacing=6))
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
        # three ticks like 點進輸入框時's rows (2026-10-22, the user's design; any one ticked turns it on)
        self.float_card, c = card()
        self._illustrate(self.float_card, c, "float")
        self.float_pill = Pill()
        c.addLayout(hbox(label("浮動按鈕", h3=True), Info("停在螢幕上的按鈕，點一下開麥克風，拖到哪就留在哪；樣子和大小在"
                                                       "「外觀與聲音」設定"), None, self.float_pill, spacing=6))
        self.floats = {}
        box = vbox(spacing=2)
        for key, name, desc in FLOATS:
            o = Option(name, desc, check=True)
            o.clicked.connect(lambda on, k=key: self._float(k, on))
            self.floats[key] = o
            box.addWidget(o)
        c.addLayout(box)
        c.addStretch(1)
        grid.addWidget(self.float_card, 0, 2)
        v.addLayout(grid)

        v.addSpacing(4)
        grid2 = QGridLayout()
        grid2.setSpacing(12)
        grid2.setColumnStretch(0, 1)
        grid2.setColumnStretch(1, 1)
        off_card, c = card()
        c.addLayout(hbox(label("沒講話多久自動關閉", h3=True), Info("麥克風開著卻一直沒聽到人聲時自動關掉，避免忘了關；"
                                                              "關掉時播結束音"), None, spacing=6))
        self.offs = Choice(OFFS, small=True)
        for b in self.offs.buttons.values():   # the minutes in the window's number face, as 自訂's (2026-10-22)
            b.setStyleSheet(theme.NUM_FAMILY)
        self.offs.picked.connect(self._off)
        self.custom_off = MinutesChip()
        self.custom_off.picked.connect(self._off)
        self.offs.layout().addWidget(self.custom_off)
        c.addWidget(self.offs)
        c.addWidget(sep())
        self.enter_switch = Switch(name="送出訊息後關閉")
        self.enter_switch.toggled.connect(self._enter)
        c.addLayout(_row(titled("送出訊息後關閉", "按 Enter 或說「送出」後；Shift+Enter 換行不算"), self.enter_switch))
        c.addWidget(sep())
        # 自動關閉麥克風 (auto_off), here since 2026-10-21 with the other ways it goes off
        self.auto_off = Switch(name="離開輸入框後關閉")
        self.auto_off.toggled.connect(self._auto_off)
        c.addLayout(_row(titled("離開輸入框後關閉", "游標移到網頁空白處、按鈕等不能打字的地方時"),
                         self.auto_off))
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
        self.test_button = button("測試麥克風", self._test)
        dev_row = hbox(self.mic, self.test_button, spacing=8)
        dev_row.setStretch(0, 1)
        c.addLayout(dev_row)
        self.meter = LevelMeter()
        c.addWidget(self.meter)
        self.test_hint = dim(TEST_IDLE, wrap=True)
        c.addWidget(self.test_hint)
        self.probe = audio.LevelProbe()
        self._heard = False
        self._test_timer = QTimer(self, interval=33)
        self._test_timer.timeout.connect(self._test_tick)
        c.addWidget(sep())
        self.mute_switch = Switch(name="錄音時靜音電腦音效")
        self.mute_switch.toggled.connect(self._mute)
        c.addLayout(_row(titled("錄音時靜音電腦音效", "關掉麥克風後恢復；原本就靜音的話不會動"), self.mute_switch))
        c.addStretch(1)
        grid2.addWidget(dev_card, 0, 1)
        v.addLayout(grid2)
        v.addStretch(1)

    @staticmethod
    def _illustrate(frame, lay, kind: str):
        ill = Illustration(kind)
        ill.watch(frame)
        lay.addWidget(ill)

    # --- values ---
    def load(self):
        cfg = self.cfg
        self._show_hotkey()
        self._show_near()
        self._show_float()
        self._show_off()
        self.auto_off.set_quiet(cfg.auto_off)
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
        # the left press on 取消 already cancelled the capture (the hook sees it first); its click must not start
        # another one
        if not self._capturing and time.monotonic() - self._cancelled_at < 1.0:
            return
        self._capturing = not self._capturing
        self._show_hotkey()
        self.win.capture_hotkey.emit(self._capturing)

    def hotkey_captured(self, spec):
        """The press captured (a hotkey spec), or None: cancelled (Esc, a left click)."""
        if not self._capturing:
            return
        self._capturing = False
        if not spec:
            self._cancelled_at = time.monotonic()
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

    def _float(self, key: str, on: bool):
        setattr(self.cfg, key, on)
        self.win.save()
        self._show_float()
        self._show_no_way()

    def _show_float(self):
        for k, o in self.floats.items():
            o.setChecked(getattr(self.cfg, k))
        on = self.cfg.show_float
        self.float_pill.set("已開啟" if on else "未開啟", on)

    def _show_no_way(self):
        self.no_way.setVisible(not (self.cfg.hotkey or self.cfg.auto_listen or self.cfg.show_bubble
                                    or self.cfg.show_float))

    def _off(self, minutes):
        self.cfg.auto_off_minutes = minutes
        self.win.save()
        self._show_off()

    def _show_off(self):
        m = self.cfg.auto_off_minutes
        preset = m in dict(OFFS)
        self.offs.set(m if preset else None)
        self.custom_off.set(None if preset else m)

    def _auto_off(self, on: bool):
        self.cfg.auto_off = on
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
        if self.probe.running:   # the test goes on with the newly picked microphone
            self._test_start()

    # --- 測試麥克風 ---
    def _test(self):
        if self.probe.running:
            self._test_stop()
        else:
            self._test_start()

    def _test_start(self):
        try:
            self.probe.start(self.cfg.mic)
        except Exception as e:
            self.probe.stop()
            self._test_show(False)
            self.test_hint.setText(f"打不開這支麥克風：{e}")
            prop(self.test_hint, dim=False, warn=True)
            return
        self._heard = False
        self._test_show(True)
        self._test_timer.start()

    def _test_stop(self):
        self._test_timer.stop()
        self.probe.stop()
        self._test_show(False)

    def _test_show(self, on: bool):
        self.test_button.setText("停止測試" if on else "測試麥克風")
        prop(self.test_button, testing=on)
        prop(self.test_hint, dim=True, warn=False)
        self.test_hint.setText(TEST_LISTENING if on else TEST_IDLE)
        if not on:
            self.meter.reset()

    def _test_tick(self):
        level = self.probe.read()
        self.meter.set(level)
        if not self._heard and level > TEST_HEARD:
            self._heard = True
            self.test_hint.setText(TEST_HEARD_TEXT)

    def hideEvent(self, e):
        """Leaving the page (or the window closing) ends the test: the microphone isn't kept open unseen."""
        if self.probe.running:
            self._test_stop()
        super().hideEvent(e)
