"""系統: 外觀模式 (light, dark, Windows'), autostart, the settings file, developer options (--debug), about."""
import os
import time
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from .. import __version__, config, paths, recordings, userdata
from . import theme
from .kit import Choice, Switch, T, button, card, dim, draw_icon, hbox, icon, label, sep, titled, vbox


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
                   "或點這裡選擇檔案。詞庫會合併；麥克風、開機啟動、浮動按鈕位置不會被覆蓋")


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

        def row(title, sub, body, last=False):
            r = QHBoxLayout()
            r.setContentsMargins(0, 18, 0, 18)
            r.setSpacing(24)
            t = titled(title, sub, 14.5, 700)
            t.setFixedWidth(210)
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
        self.mode_row = row("外觀模式", "-", vbox(self.modes, None))
        self.auto = Switch(name="開機時自動啟動")
        self.auto.toggled.connect(self._auto)
        self.auto_note = label("")
        row("開機時自動啟動", "登入 Windows 後在背景啟動，常駐在右下角", hbox(self.auto, self.auto_note, None, spacing=10))
        drop = Drop()
        drop.dropped.connect(self._import_file)
        drop.clicked.connect(self._import_pick)
        export = button("匯出設定檔…", self._export, pri=True)
        reset = button("還原成預設值", self._reset, link=True)
        row("設定檔", "所有設定與詞庫存成一個檔案，換電腦時帶走",
            vbox(drop, 10, hbox(export, None, reset, spacing=8), spacing=0))
        self.dev_row = QWidget()
        if config.DEBUG:
            dev = vbox(spacing=0)
            self.dev_toggle = button("", self._toggle_dev)
            self.dev_toggle.setStyleSheet("QPushButton { background: transparent; border: none; padding: 4px 0; "
                                          "text-align: left; font-size: 13.5px; }")
            badge = label("--debug")
            badge.setFont(theme.font(11, 700, num=True))
            badge.setStyleSheet("background: #15171A; color: #FFC23D; border-radius: 4px; padding: 2px 7px;")
            badge.setFixedHeight(20)
            dev.addLayout(hbox(self.dev_toggle, badge, None, spacing=8))
            self.dev_box = QFrame(objectName="card")
            self.dev_box.setAttribute(Qt.WA_StyledBackground)
            box = QVBoxLayout(self.dev_box)
            box.setContentsMargins(14, 12, 14, 12)
            box.setSpacing(12)
            self.rec = Switch(name="保存錄音")
            self.rec.toggled.connect(self._rec)
            folder = button("開啟錄音資料夾", self._open_recordings)
            box.addLayout(hbox(titled("保存錄音", "每段錄音存成檔案，方便重播測試；不會自動刪除", 13.5), None, folder,
                               self.rec))
            self.quick = Switch(name="短停頓就執行指令")
            self.quick.toggled.connect(self._quick)
            box.addLayout(hbox(titled("短停頓就執行指令", "單獨說出的指令停 0.15 秒就執行，不等 0.3 秒；下次開麥克風時"
                                                    "生效", 13.5), None, self.quick))
            self.dev_box.hide()
            dev.addSpacing(10)
            dev.addWidget(self.dev_box)
            row("開發者選項", "只有用 --debug 啟動時才看得到", dev)
        about = hbox(spacing=24)
        for k, val in (("版本", __version__), ("辨識引擎", "X-ASR · 本機")):
            about.addLayout(self._kv(k, val))
        folder = button("%LOCALAPPDATA%\\ArtVoiceInput", lambda: os.startfile(paths.DATA_DIR), link=True)
        folder.setFont(theme.font(13, 600, num=True))
        about.addLayout(vbox(dim("資料夾"), folder, spacing=1))
        about.addStretch(1)
        row("關於", "阿特語音輸入法 Art VoiceInput", about, last=True)
        v.addWidget(frm)
        v.addStretch(1)
        self.restyle()

    @staticmethod
    def _kv(k, val):
        b = label(val)
        b.setFont(theme.font(15, 600, num=True))
        return vbox(dim(k), b, spacing=1)

    def restyle(self):
        ink = T("ink")
        for key, name in (("light", "sun"), ("dark", "moon"), ("system", "pc")):
            self.modes.buttons[key].setIcon(icon(name, ink, 16, 1.8))
            self.modes.setText(key, dict(theme.MODES)[key])

    def load(self):
        self.modes.set(self.cfg.theme)
        self._mode_note()
        self.auto.set_quiet(self.cfg.autostart)
        self._auto_note()
        if config.DEBUG:
            self.rec.set_quiet(self.cfg.save_recordings)
            self.quick.set_quiet(self.cfg.early_commands)
            self._dev_label()

    def summary(self) -> str:
        return f"{dict(theme.MODES)[self.cfg.theme]}模式、開機" + ("自動啟動" if self.cfg.autostart else "不啟動") + "、設定檔"

    def notice(self, text: str):
        self.note.setText(text)
        self.note.show()
        self._note_timer.start()

    # --- 外觀模式 ---
    def _mode(self, mode: str):
        self.cfg.theme = mode
        self.win.save()
        self.win.theme.set_mode(mode)
        self._mode_note()

    def _mode_note(self):
        if self.cfg.theme == "system":
            text = "目前 Windows 是" + ("暗色" if theme.system_dark() else "亮色") + "，跟著一起換"
        else:
            text = "不管 Windows 怎麼設，都用" + ("暗色" if self.cfg.theme == "dark" else "亮色")
        self.mode_row.sub.setText(text)

    # --- autostart ---
    def _auto(self, on: bool):
        self.cfg.autostart = on
        self.win.save()
        self._auto_note()

    def _auto_note(self):
        self.auto_note.setText("下次開機會自動啟動" if self.cfg.autostart else "要自己打開")

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
        self.notice(f"已匯出到 {path}")

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
        if QMessageBox.question(self, "還原成預設值", "把所有設定還原成預設，並清空詞庫（詞庫列表、選字記憶、英文強制"
                                                  "替換，詞包恢復原始內容並取消勾選）？\n這個動作無法復原，需要的話先匯出。"
                                ) != QMessageBox.Yes:
            return
        userdata.reset(self.cfg, self.win.hotwords, self.win.memory)
        self.win.data_changed()
        self.notice("已還原預設")

    # --- developer options ---
    def _toggle_dev(self):
        self.dev_box.setVisible(not self.dev_box.isVisible())
        self._dev_label()

    def _dev_label(self):
        open_ = self.dev_box.isVisible()
        self.dev_toggle.setText(("▾ 收起" if open_ else "▸ 展開") + " 2 個選項")

    def _rec(self, on: bool):
        self.cfg.save_recordings = on
        self.win.save()

    def _quick(self, on: bool):
        self.cfg.early_commands = on
        self.win.save()

    def _open_recordings(self):
        recordings.DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(recordings.DIR)
