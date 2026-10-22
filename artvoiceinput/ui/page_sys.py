"""系統: 外觀模式 (light, dark, Windows'), autostart, the tray icon on the taskbar, the settings file, about; with
--debug a Debug card of test options under them."""
import os
import time
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from .. import __version__, appicon, config, paths, userdata
from . import theme
from .kit import (Choice, Info, Switch, T, button, card, crossfade, dim, draw_icon, hbox, icon, label, sep,
                  set_calm, titled, vbox)


LEFT = 300   # the names' column: each gray line on one line (210 wrapped them, 2026-10-21, the user's request)
CLICKS = (("settings", "打開設定視窗"), ("mic", "開關麥克風"))   # Config.tray_click


def _state(on: bool, text: str) -> str:
    """A switch's note, led by the state it describes (開： / 關：, 2026-10-21, the user's request)."""
    return f"<b>{'開' if on else '關'}：</b>{text}"


class TrayMark(QWidget):
    """The tray icon itself in 點一下 [icon] [dropdown], where the words said 圖示 (2026-10-21, the user's request)."""
    S = 20

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.S, self.S)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        appicon.paint(p, self.S)


class Drop(QWidget):
    """A dashed box a settings file is dropped on (or clicked, to pick one)."""
    dropped = Signal(str)
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(64)
        self._hot = False

    def enterEvent(self, e):
        self._hot = True
        self.update()

    def leaveEvent(self, e):
        self._hot = False
        self.update()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hot = True
            self.update()

    def dragLeaveEvent(self, e):
        self._hot = False
        self.update()

    def dropEvent(self, e):
        self._hot = False
        self.update()
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.dropped.emit(urls[0])

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        pen = QPen(T("acc") if self._hot else T("line"), 1.5, Qt.DashLine)
        pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.setBrush(T("accbg") if self._hot else Qt.NoBrush)
        p.drawRoundedRect(r, 6, 6)
        draw_icon(p, "down", QRectF(16, r.center().y() - 11, 22, 22), T("acct") if self._hot else T("muted"), 1.8)
        p.setPen(T("ink"))
        p.setFont(theme.font(13.5, 700))
        p.drawText(QRectF(50, 12, r.width() - 60, 20), Qt.AlignLeft | Qt.AlignVCenter, "把設定檔拖到這裡匯入")
        p.setFont(theme.font(12))
        p.setPen(T("muted"))
        p.drawText(QRectF(50, 32, r.width() - 60, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "或點這裡選擇檔案。詞庫會合併，麥克風等這台電腦的設定不會被覆蓋")


class SysPage(QWidget):
    title = "系統"

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        self.note = label("", warn=True)
        self.note.hide()
        self._note_timer = QTimer(self, singleShot=True, interval=6000, timeout=self.note.hide)
        v.addWidget(self.note)
        frm, rows = card(margins=(22, 0, 22, 0), spacing=0)

        def row(title, sub, body, last=False, info=None):
            r = QHBoxLayout()
            r.setContentsMargins(0, 16, 0, 16)
            r.setSpacing(24)
            t = titled(title, sub, 14.5, 700)
            t.setFixedWidth(LEFT)
            if info is not None:   # the ⓘ after the name
                t.layout().removeWidget(t.title)
                t.layout().insertLayout(0, hbox(t.title, Info(info), None, spacing=6))
            r.addWidget(t, 0, Qt.AlignTop)
            if isinstance(body, QWidget):
                r.addWidget(body, 1)
            else:
                r.addLayout(body, 1)
            rows.addLayout(r)
            if not last:
                rows.addWidget(sep())
            return t

        self.modes = Choice([(k, n, None) for k, n in theme.MODES], kind="seg", big=True)
        self.modes.picked.connect(self._mode)
        self.modes.settled.connect(self._apply_mode)
        self.mode_row = row("外觀模式", "-", vbox(self.modes, None))
        self.auto = Switch(name="開機時自動啟動")
        self.auto.toggled.connect(self._auto)
        self.auto_note = label("")
        row("開機時自動啟動", "登入 Windows 後在背景啟動，常駐在右下角", hbox(self.auto, self.auto_note, None, spacing=10))
        # the tray icon on the taskbar itself (2026-10-21, the user's request; tray.promote)
        self.pin = Switch(name="圖示固定在工作列")
        self.pin.toggled.connect(self._pin)
        self.pin_note = label("")
        # what a left click on the icon does, after the switch (2026-10-21, the user's request)
        self.click = QComboBox()
        self.click.setAccessibleName("點一下圖示時")
        self.click.setCursor(Qt.PointingHandCursor)
        for key, name in CLICKS:
            self.click.addItem(name, key)
        self.click.currentIndexChanged.connect(self._click)
        row("圖示固定在工作列", "右下角直接看得到，不收進隱藏的圖示",
            hbox(self.pin, self.pin_note, None, hbox(label("點一下"), TrayMark(), self.click, spacing=6), spacing=10),
            info="左鍵點圖示做的事在右邊選，右鍵打開選單。關閉時圖示收回隱藏的圖示裡")
        # 節流模式 (moved here from 外觀與聲音, 2026-10-20, the user's request): the orbs and the glow draw less, and
        # this window skips its animations (kit.calm)
        self.lite = Switch(name="節流模式")
        self.lite.slides = True
        self.lite.toggled.connect(self._lite)
        self.lite_note = label("")
        row("節流模式", "省 CPU：按鈕和光暈畫得簡單，這個視窗不播動畫", hbox(self.lite, self.lite_note, None, spacing=10),
            info="開啟後：能量球每秒 15 張、光暈較粗略，螢幕邊緣光暈的波浪、流星、漣漪每秒 24 張；這個設定視窗直接切換頁面，"
                 "不播滑過、燈號閃爍和預覽的動畫。關閉時能量球每秒 30 張、會移動的光暈每秒 48 張，比較順，但 CPU 用量約多七成")
        drop = Drop()
        drop.dropped.connect(self._import_file)
        drop.clicked.connect(self._import_pick)
        export = button("匯出設定檔…", self._export, pri=True)
        # 清空並重新設定 (2026-10-21, the user's design: like a phone's factory reset): everything cleared, then the
        # setup wizard from its first step
        reset = button("清空並重新設定…", self._reset, danger=True)
        row("設定檔", "所有設定與詞庫存成一個檔案，換電腦時帶走",
            vbox(drop, 10, hbox(export, None, reset, spacing=8), spacing=0))
        # names on one line, values on the next, all values alike (the folder link was a button: the buttons'
        # style-sheet size made it smaller, 2026-10-21)
        about = QGridLayout()
        about.setHorizontalSpacing(24)
        about.setVerticalSpacing(1)
        folder = label("%LOCALAPPDATA%\\ArtVoiceInput")
        folder.setCursor(Qt.PointingHandCursor)
        folder.mouseReleaseEvent = lambda e: os.startfile(paths.DATA_DIR) if e.button() == Qt.LeftButton else None
        self.folder = folder
        for col, (k, val) in enumerate((("版本", __version__), ("辨識引擎", "X-ASR · 本機"), ("資料夾", folder))):
            if isinstance(val, str):
                val = label(val)
            val.setFont(theme.font(15, 600, num=True))
            val.setFixedHeight(24)
            if k == "辨識引擎":
                # 本機 falls back to Noto Sans TC, whose taller line, centered, put the baseline 2px lower than the
                # others' (2026-10-21); from the top it lands on theirs
                val.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            about.addWidget(dim(k), 0, col, Qt.AlignLeft | Qt.AlignBottom)
            about.addWidget(val, 1, col, Qt.AlignLeft | Qt.AlignVCenter)
        folder.setFont(theme.font(13.5, 600, num=True))   # the long path a little smaller (2026-10-21)
        about.setColumnStretch(3, 1)
        row("關於", "阿特語音輸入法 Art VoiceInput", about, last=True)
        v.addWidget(frm)
        self.debug_switches = []   # (switch, its note, config field, note when on, note when off)
        if config.DEBUG:
            self._debug_card(v)
        v.addStretch(1)
        self.restyle()

    def _debug_card(self, v):
        """With --debug: test options, plain (2026-10-22, the user's request). Options come and go as tests end; the
        card shows only while it has one, so keep this method and its row() for the next."""
        options = []

        def switch(field, title, sub, on, off):
            sw, note = Switch(name=title), label("")
            sw.toggled.connect(lambda v, f=field: self._debug_set(f, v))
            self.debug_switches.append((sw, note, field, on, off))
            options.append((title, sub, hbox(sw, note, None, spacing=10)))
        # pieces not decoded alone, straight to the sentence's decode (2026-10-22: the pause's latency)
        switch("skip_alone", "長句不單獨辨識", "超過 2 秒的一段話直接整句辨識，停頓後早一點出字",
               "長句直接整句辨識", "先單獨辨識再整句（舊做法）")
        switch("skip_short", "短句不單獨辨識", "2 秒內的一段話不是指令就直接整句辨識，短句早點出字",
               "短句少辨識兩次", "單獨辨識兩三次（舊做法）")
        # the setup wizard at once, dark, nothing cleared (2026-10-21, the user's request; it applies what is picked
        # like the real one)
        options.append(("設定精靈", "直接進入設定精靈（暗色），不清空任何資料",
                        hbox(button("進入設定精靈", self._wizard_dark), None)))
        if not options:
            return
        frm, rows = card(margins=(22, 6, 22, 0), spacing=0)
        rows.addWidget(dim("Debug（--debug 啟動時才有）"))
        for i, (title, sub, body) in enumerate(options):
            self._row(rows, title, sub, body, i == len(options) - 1)
        v.addWidget(frm)

    @staticmethod
    def _row(into, title, sub, body, last):
        r = QHBoxLayout()
        r.setContentsMargins(0, 12, 0, 12)
        r.setSpacing(24)
        t = titled(title, sub, 14.5, 700)
        t.setFixedWidth(LEFT)
        r.addWidget(t, 0, Qt.AlignTop)
        r.addLayout(body, 1)
        into.addLayout(r)
        if not last:
            into.addWidget(sep())

    def restyle(self):
        self.folder.setStyleSheet(f"color: {T('acct').name()}; text-decoration: underline;")
        ink = T("ink")
        for key, name in (("light", "sun"), ("dark", "moon"), ("system", "pc")):
            self.modes.buttons[key].setIcon(icon(name, ink, 16, 1.8))
            self.modes.setText(key, dict(theme.MODES)[key])

    def load(self):
        self.modes.set(self.cfg.theme)
        self._mode_note()
        self.auto.set_quiet(self.cfg.autostart)
        self._auto_note()
        self.pin.set_quiet(self.cfg.tray_pinned)
        self._pin_note()
        self.click.blockSignals(True)
        self.click.setCurrentIndex(max(0, self.click.findData(self.cfg.tray_click)))
        self.click.blockSignals(False)
        self.lite.set_quiet(self.cfg.orb_lite)
        self._lite_note()
        for sw, _, field, *_ in self.debug_switches:
            sw.set_quiet(getattr(self.cfg, field))
        self._debug_notes()
        set_calm(self.cfg.orb_lite)

    def summary(self) -> str:
        return f"{dict(theme.MODES)[self.cfg.theme]}模式、開機" + ("自動啟動" if self.cfg.autostart else "不啟動") + "、設定檔"

    def notice(self, text: str):
        self.note.setText(text)
        self.note.show()
        self._note_timer.start()

    # --- 外觀模式 ---
    def _mode(self, mode: str):
        """Saved at once; the colors change when the card has slid there (_apply_mode)."""
        self.cfg.theme = mode
        self.win.save()
        self._mode_note()

    def _apply_mode(self):
        if self.win.theme.mode == self.cfg.theme:
            return
        crossfade(self.window())   # the old look, the card already moved, fades away over the new colors
        self.win.theme.set_mode(self.cfg.theme)

    def _mode_note(self):
        if self.cfg.theme == "system":
            text = "目前 Windows 是" + ("暗色" if theme.system_dark() else "亮色") + "，跟著一起換"
        else:
            text = "不管 Windows 怎麼設，都用" + ("暗色" if self.cfg.theme == "dark" else "亮色")
        self.mode_row.sub.setText(text)

    # --- 節流模式 ---
    def _lite(self, on: bool):
        self.cfg.orb_lite = on
        self.win.save()
        set_calm(on)
        self._lite_note()
        self.win.look_page.refresh_orb()

    def _lite_note(self):
        self.lite_note.setText(_state(self.cfg.orb_lite, "動畫從簡" if self.cfg.orb_lite else "動畫完整播放"))

    # --- Debug ---
    def _debug_set(self, field: str, on: bool):
        setattr(self.cfg, field, on)
        self.win.save()
        self._debug_notes()

    def _debug_notes(self):
        for _, note, field, on, off in self.debug_switches:
            value = getattr(self.cfg, field)
            note.setText(_state(value, on if value else off))

    # --- autostart ---
    def _auto(self, on: bool):
        self.cfg.autostart = on
        self.win.save()
        self._auto_note()

    def _auto_note(self):
        self.auto_note.setText(_state(self.cfg.autostart, "下次開機會自動啟動" if self.cfg.autostart else "要自己打開"))

    # --- the tray icon ---
    def _pin(self, on: bool):
        self.cfg.tray_pinned = on
        self.win.save()
        self._pin_note()

    def _pin_note(self):
        self.pin_note.setText(_state(self.cfg.tray_pinned, "顯示在工作列" if self.cfg.tray_pinned else "收在隱藏的圖示裡"))

    def _click(self):
        self.cfg.tray_click = self.click.currentData()
        self.win.save()

    # --- 設定檔 ---
    def _export(self):
        name = f"Art VoiceInput 設定 {time.strftime('%Y-%m-%d')}.json"
        path, _ = QFileDialog.getSaveFileName(self, "匯出設定", str(Path.home() / "Documents" / name),
                                              "Art VoiceInput 設定檔 (*.json)")
        if not path:
            return
        try:
            userdata.export(Path(path), self.cfg, self.win.hotwords, self.win.memory)
        except OSError as e:
            QMessageBox.warning(self, "匯出設定", f"無法寫入檔案：{e}")
            return

    def _import_pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入設定", str(Path.home() / "Documents"),
                                              "Art VoiceInput 設定檔 (*.json)")
        if path:
            self._import_file(path)

    def _import_file(self, path: str):
        try:
            data = userdata.load(Path(path))
            n = userdata.import_into(data, self.cfg, self.win.hotwords, self.win.memory)
        except (OSError, ValueError, TypeError) as e:
            QMessageBox.warning(self, "匯入設定", f"無法匯入：{e}")
            return
        self.win.data_changed()
        self.notice(f"已套用設定，並合併詞庫：詞庫列表 {n['words']} 個詞、選字記憶 {n['picks']} 筆、"
                    f"詞包新增 {n['pack_terms']} 個詞")

    def _reset(self):
        from .sheet import Sheet
        sheet = Sheet(self.window(), "清空所有資料並重新設定？",
                      "設定、詞庫列表、選字記憶、英文強制替換和詞包的修改都會清掉，無法復原。\n"
                      "辨識模型會保留，清空後回到設定精靈。", "清空並重新設定", "先匯出設定檔…")
        sheet.linked.connect(self._export)
        sheet.accepted.connect(self._reset_now)
        sheet.open()

    def _wizard_dark(self):
        self.cfg.theme = "dark"
        self.cfg.setup_done = False   # the app rests until it is finished, as after 清空並重新設定
        self.modes.set("dark")
        self._mode_note()
        self.win.save()
        self.win.theme.set_mode("dark")
        self.win.start_wizard()

    def _reset_now(self):
        """Cleared and saved, then the app closes and starts again as new (the user's request, 2026-10-21: nothing
        carried over); setup_done is false, so the new one opens on the setup wizard."""
        userdata.reset(self.cfg, self.win.hotwords, self.win.memory)
        self.win.data_changed()
        self.win.restart.emit()
