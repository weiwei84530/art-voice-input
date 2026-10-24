"""The setup window, layout B: the app icon, the name, one button (安裝 / 開始使用 / 解除安裝) that a progress bar takes the
place of while working, and a line at the bottom with the folder and a link (換個位置, 取消安裝 …). Light only, the
settings window's tokens (`theme.LIGHT`)."""
import ctypes
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from artvoiceinput import __version__, appicon
from artvoiceinput.ui import theme

from . import ops

T = theme.LIGHT
W, H = 520, 360


def _qss() -> str:
    check = theme._CHECK
    return f"""
QWidget {{ color: {T['ink']}; }}
QLabel {{ background: transparent; }}
QPushButton#pri {{ background: {T['acc']}; color: #FFFFFF; border: none; border-radius: 7px; font-size: 15px;
                  font-weight: 500; min-height: 44px; max-height: 44px; }}
QPushButton#pri:hover {{ background: #F0392E; }}
QPushButton#pri:focus {{ outline: none; }}
QPushButton#danger {{ background: {T['tile2']}; color: {T['acct']}; border: 1px solid {T['line']}; border-radius: 7px;
                     font-size: 15px; font-weight: 500; min-height: 42px; max-height: 42px; }}
QPushButton#danger:hover {{ border-color: {T['acc']}; }}
QPushButton#link {{ background: transparent; border: none; color: {T['acct']}; text-decoration: underline;
                   font-size: 12px; padding: 0; }}
QPushButton#link:hover {{ color: #A01E16; }}
QCheckBox {{ font-size: 14px; font-weight: 500; spacing: 8px; margin-bottom: 14px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1.5px solid {T['muted']}; }}
QCheckBox::indicator:checked {{ background: {T['acc']}; border-color: {T['acc']}; image: url({check}); }}
"""


class Icon(QWidget):
    """The app icon, 76px, over a soft dark red shadow (the setup wizard's badge)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 76)
        shadow = QGraphicsDropShadowEffect(self, blurRadius=22, offset=QPointF(0, 6))
        shadow.setColor(QColor(120, 10, 0, 70))
        self.setGraphicsEffect(shadow)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        appicon.paint(p, self.width())


class Progress(QWidget):
    """An 8px orange bar and the percent after it, 240 wide like the button it stands in for."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 44)
        self.value = 0.0

    def set(self, v: float):
        self.value = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bar = QRectF(0, 18, self.width() - 52, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T["line"]))
        p.drawRoundedRect(bar, 4, 4)
        if self.value > 0:
            p.setBrush(QColor(T["acc"]))
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), max(8, bar.width() * self.value), 8), 4, 4)
        p.setPen(QColor(T["ink"]))
        p.setFont(theme.font(20, 500, num=True))
        p.drawText(QRectF(bar.right(), 0, 52, self.height()), Qt.AlignRight | Qt.AlignVCenter,
                   f"{round(self.value * 100)}%")


class CloseButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 32)
        self.setAccessibleName("關閉")
        self.setCursor(Qt.ArrowCursor)
        self._over = False

    def enterEvent(self, e):
        self._over = True
        self.update()

    def leaveEvent(self, e):
        self._over = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        over = self._over and self.isEnabled()
        if over:
            p.fillRect(self.rect(), QColor("#C42B1C"))
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#FFFFFF") if over else QColor(T["ink" if self.isEnabled() else "line"]), 1.2))
        cx, cy = self.width() / 2, self.height() / 2
        p.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))
        p.drawLine(QPointF(cx + 5, cy - 5), QPointF(cx - 5, cy + 5))


class Worker(QObject):
    """Runs install / uninstall on a thread; the window hears it through queued signals."""
    progressed = Signal(float, str)
    finished = Signal(str)   # "" when it went well, else the reason

    def run(self, job, *args):
        def go():
            try:
                job(*args, lambda v, what: self.progressed.emit(v, what))
                self.finished.emit("")
            except ops.SetupError as e:
                self.finished.emit(str(e))
            except Exception as e:   # anything else still ends the busy state
                self.finished.emit(f"發生錯誤：{e}")
        threading.Thread(target=go, daemon=True).start()


class Window(QWidget):
    def __init__(self, uninstall_dir: Path | None = None, folder: Path | None = None):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.uninstall_dir = uninstall_dir
        self.folder = folder or ops.installed_dir() or ops.DEFAULT_DIR
        self.busy = False
        self._press_at = None
        self.setWindowTitle(f"{ops.NAME} 解除安裝" if uninstall_dir else f"{ops.NAME} 安裝")
        self.setWindowIcon(appicon.icon())
        self.setFixedSize(W, H + 24 if uninstall_dir else H)   # room for the tick over the button
        self.setStyleSheet(_qss())
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(T["tile"]))
        self.setPalette(pal)

        self.close_button = CloseButton(self)
        self.close_button.move(self.width() - 46, 0)
        self.close_button.clicked.connect(self.close)

        v = QVBoxLayout(self)
        v.setContentsMargins(40, 34, 40, 28)
        v.setSpacing(0)
        v.addWidget(Icon(), 0, Qt.AlignHCenter)
        v.addSpacing(18)
        self.name = self._label(ops.NAME, 26, 700)
        v.addWidget(self.name)
        v.addSpacing(4)
        self.sub = self._label("", 13)
        self.sub.setTextFormat(Qt.RichText)
        v.addWidget(self.sub)
        v.addSpacing(22)

        # the action: a button, the progress bar in its place, or (uninstall) a tick over the button
        self.stack = QStackedWidget()
        self.stack.setFixedHeight(44)
        self.button = QPushButton()
        self.button.setFixedWidth(240)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self._act)
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.button, 0, Qt.AlignHCenter)
        self.progress = Progress()
        pholder = QWidget()
        ph = QHBoxLayout(pholder)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.addWidget(self.progress, 0, Qt.AlignHCenter)
        self.stack.addWidget(holder)
        self.stack.addWidget(pholder)
        self.delete_data = QCheckBox("也刪除我的設定、詞庫和辨識紀錄")
        self.delete_data.setCursor(Qt.PointingHandCursor)
        self.delete_data.hide()
        v.addWidget(self.delete_data, 0, Qt.AlignHCenter)
        v.addWidget(self.stack)
        v.addStretch(1)
        self.note = self._label("", 12)
        v.addWidget(self.note)
        v.addSpacing(2)
        self.link = QPushButton()
        self.link.setObjectName("link")
        self.link.setCursor(Qt.PointingHandCursor)
        self.link.clicked.connect(self._link)
        v.addWidget(self.link, 0, Qt.AlignHCenter)

        self.worker = Worker()
        self.worker.progressed.connect(self._progressed)
        self.worker.finished.connect(self._finished)
        self._show("u-ask" if uninstall_dir else "start")

    def _label(self, text, px, weight=400):
        lab = QLabel(text)
        lab.setFont(theme.font(px, weight))
        lab.setAlignment(Qt.AlignHCenter)
        if px < 20:
            lab.setStyleSheet(f"color: {T['muted']};")
        return lab

    def _path_text(self) -> str:
        fm = QFontMetrics(self.note.font())
        return fm.elidedText(f"安裝到 {self.folder}", Qt.ElideMiddle, W - 80)

    # states: start, busy, done, error; u-ask, u-busy, u-done, u-error
    def _show(self, state: str, message: str = ""):
        self.state = state
        self.busy = state in ("busy", "u-busy")
        self.close_button.setEnabled(not self.busy)
        self.stack.setCurrentIndex(1 if self.busy else 0)
        self.delete_data.setVisible(state == "u-ask")
        self.link.setEnabled(True)
        num = f"font-family: '{theme.NUM_FONT}'; font-size: 15px; font-weight: 500;"
        ok = f"<span style='color: {T['ins']}; font-weight: 500;'>●&nbsp;{{}}</span>"
        err = f"<span style='color: {T['acct']}; font-weight: 500;'>{{}}</span>"
        sub, button, kind, note, link = {
            "start": (f"Art VoiceInput <span style=\"{num}\">&nbsp;{__version__}</span>", "安裝", "pri",
                      self._path_text(), "換個位置"),
            "busy": ("正在準備", "", "pri", self._path_text(), ""),
            "done": (ok.format("安裝完成"), "開始使用", "pri", "之後可以在 Windows 設定的「應用程式」解除安裝",
                     "先不開啟，關閉"),
            "error": (err.format(message), "再試一次", "pri", self._path_text(), "換個位置"),
            "u-ask": ("會移除程式、辨識模型和開機自動啟動", "解除安裝", "danger",
                      "不勾的話會留著，之後重新安裝會接著用", "取消"),
            "u-busy": ("正在準備", "", "danger", "", ""),
            "u-done": (ok.format("已解除安裝"), "關閉", "pri", "", ""),
            "u-error": (err.format(message), "再試一次", "danger", "", "關閉"),
        }[state]
        self.sub.setText(sub)
        self.button.setText(button)
        self.button.setObjectName(kind)
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)
        self.note.setText(note)
        self.link.setText(link)
        self.link.setVisible(bool(link))
        if self.busy:
            self.progress.set(0)

    def _act(self):
        s = self.state
        if s in ("start", "error"):
            self._show("busy")
            self.worker.run(ops.install, self.folder)
        elif s == "done":
            ops.launch(self.folder)
            self.close()
        elif s in ("u-ask", "u-error"):
            self._show("u-busy")
            self.worker.run(ops.uninstall, self.uninstall_dir, self.delete_data.isChecked())
        elif s == "u-done":
            self.close()

    def _link(self):
        if self.state in ("start", "error"):
            chosen = QFileDialog.getExistingDirectory(self, "選擇安裝位置", str(self.folder.parent))
            if chosen:
                self.folder = ops.target(Path(chosen))
                self.note.setText(self._path_text())
        else:
            self.close()

    def _progressed(self, v: float, what: str):
        self.progress.set(v)
        self.sub.setText(what)

    def _finished(self, error: str):
        un = self.state == "u-busy"
        if error:
            self._show("u-error" if un else "error", error)
        else:
            self._show("u-done" if un else "done")

    def closeEvent(self, e):
        if self.busy:
            e.ignore()
            return
        super().closeEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        try:   # Windows 11 rounds the frameless window and gives it the usual shadow
            pref = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except (AttributeError, OSError):
            pass

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and not self.busy:
            self.close()
        else:
            super().keyPressEvent(e)

    # the window moves by dragging anywhere that isn't a control
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_at = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        at = self._press_at
        if at is not None and (e.globalPosition().toPoint() - at).manhattanLength() >= QApplication.startDragDistance():
            self._press_at = None
            self.windowHandle().startSystemMove()

    def mouseReleaseEvent(self, e):
        self._press_at = None


def _arg(name: str) -> str | None:
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main() -> int:
    exe = Path(sys.executable)
    from . import payload
    z = payload.open_zip(exe)
    uninstalling = z is None
    if z is not None:
        z.close()
    if uninstalling:
        folder = Path(_arg("--from") or exe.parent)
        if _arg("--from") is None:
            # run from a temp copy: the app folder, this exe in it, can then be deleted
            copy = Path(tempfile.gettempdir()) / f"{ops.APP_ID}-uninstall.exe"
            shutil.copyfile(exe, copy)
            import subprocess
            subprocess.Popen([str(copy), "--from", str(folder)] + [a for a in sys.argv[1:] if a == "/quiet"],
                             close_fds=True)
            return 0
        if "/quiet" in sys.argv:
            ops.uninstall(folder, False, lambda v, what: None)
            ops.delete_later(exe)
            return 0
    app = QApplication(sys.argv)
    f = QFont()
    f.setFamilies([theme.FONT, theme.FONT_FALLBACK])
    app.setFont(f)
    preset = _arg("--dir")   # testing: a folder other than the default
    w = Window(uninstall_dir=folder if uninstalling else None, folder=Path(preset) if preset else None)
    w.show()
    code = app.exec()
    if uninstalling:
        ops.delete_later(exe)
    return code
