"""系統: 外觀模式 (light, dark, Windows'), autostart, the settings file, about."""
import os
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QFileDialog, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
                               QVBoxLayout, QWidget)

from .. import __version__, paths, userdata
from . import theme
from .kit import (Choice, Info, Switch, T, button, calm, card, dim, draw_icon, hbox, icon, label, sep, set_calm, titled,
                  vbox)


def _state(on: bool, text: str) -> str:
    """A switch's note, led by the state it describes (開： / 關：, 2026-10-21, the user's request)."""
    return f"<b>{'開' if on else '關'}：</b>{text}"


def _crossfade(win: QWidget):
    """The window as it looks now laid over it and faded out (220ms) while the new colors come in under it; not
    with 節流模式."""
    if calm() or not win.isVisible():
        return
    cover = QLabel(win)
    cover.setPixmap(win.grab())
    cover.setGeometry(win.rect())
    cover.setAttribute(Qt.WA_TransparentForMouseEvents)
    fx = QGraphicsOpacityEffect(cover, opacity=1.0)
    cover.setGraphicsEffect(fx)
    cover.show()
    cover.raise_()
    anim = QPropertyAnimation(fx, b"opacity", cover, duration=220, startValue=1.0, endValue=0.0,
                              easingCurve=QEasingCurve.InOutQuad)
    anim.finished.connect(cover.deleteLater)
    anim.start()


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

        def row(title, sub, body, last=False, info=None):
            r = QHBoxLayout()
            r.setContentsMargins(0, 18, 0, 18)
            r.setSpacing(24)
            t = titled(title, sub, 14.5, 700)
            t.setFixedWidth(210)
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
        self.mode_row = row("外觀模式", "-", vbox(self.modes, None))
        self.auto = Switch(name="開機時自動啟動")
        self.auto.toggled.connect(self._auto)
        self.auto_note = label("")
        row("開機時自動啟動", "登入 Windows 後在背景啟動，常駐在右下角", hbox(self.auto, self.auto_note, None, spacing=10))
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
        reset = button("還原成預設值", self._reset, link=True)
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
        v.addStretch(1)
        self.restyle()

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
        self.lite.set_quiet(self.cfg.orb_lite)
        self._lite_note()
        set_calm(self.cfg.orb_lite)

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
        _crossfade(self.window())   # before the new colors: the old look fades away over them
        self.win.theme.set_mode(mode)
        self._mode_note()

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

    # --- autostart ---
    def _auto(self, on: bool):
        self.cfg.autostart = on
        self.win.save()
        self._auto_note()

    def _auto_note(self):
        self.auto_note.setText(_state(self.cfg.autostart, "下次開機會自動啟動" if self.cfg.autostart else "要自己打開"))

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
