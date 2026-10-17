"""Shows the redesigned settings window on a copy of the settings, so nothing of the user's is written.

    .venv/Scripts/python dev/settings_preview.py [page] [--dark] [--shot out.png]
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="vi-preview-"))

from voiceinput import paths  # noqa: E402

for name in ("config.json", "hotword-list.json", "smart-picks.json"):
    if (paths.DATA_DIR / name).exists():
        shutil.copy(paths.DATA_DIR / name, TMP / name)
paths.CONFIG_PATH = TMP / "config.json"
from voiceinput import config  # noqa: E402

config.CONFIG_PATH = paths.CONFIG_PATH
config.DEBUG = True
from voiceinput import packs  # noqa: E402

packs.DIR = TMP / "packs"
if (paths.DATA_DIR / "packs").exists():
    shutil.copytree(paths.DATA_DIR / "packs", packs.DIR)
packs._BASE = packs.DIR / "shipped"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from voiceinput.hotwords import Hotwords  # noqa: E402
from voiceinput.memory import Memory  # noqa: E402
from voiceinput.ui.window import SettingsWindow  # noqa: E402


def main():
    args = sys.argv[1:]
    app = QApplication(sys.argv)
    if any(a.endswith(".png") for a in args):   # a screenshot run never waits on an error
        def fail(*exc):
            sys.__excepthook__(*exc)
            app.exit(1)
        sys.excepthook = fail
    cfg = config.Config.load()
    if "--dark" in args:
        cfg.theme = "dark"
    if "--light" in args:
        cfg.theme = "light"
    for a in args:
        if a.startswith("tab="):
            cfg.hotword_section = a[4:]
    win = SettingsWindow(cfg, Hotwords(TMP / "hotword-list.json"), Memory(TMP / "smart-picks.json"))
    win.load_values()
    if "--samplelog" in args:
        from voiceinput.logbook import LogBook
        book = LogBook(lambda: None)
        book.single("選字", "應 → 影", "")
        book.new_session()
        book.heard({"heard": "嗯我覺得這個版本可以"}, "", "我覺得這個版本可以")
        book.committed("我覺得這個版本可以", "我覺得這個版本可以。", True, False)
        book.heard({"heard": "預算大概十五萬"}, "", "預算大概15萬", )
        book.heard({"heard": "預算大概十五萬", "bank": ["英文替換：Dipsick → DeepSeek"]}, "預算大概15萬",
                   "預算大概 15 萬，DeepSeek 下週上線")
        book.undo("好的，", "", "")
        book.committed("預算大概 15 萬，DeepSeek 下週上線", "預算大概 15 萬，DeepSeek 下週上線。", True, True)
        win.set_log(book.sessions)
    win.show()
    scroll = next((int(a[7:]) for a in args if a.startswith("scroll=")), 0)
    page = next((a for a in args if not a.startswith("--") and not a.endswith(".png") and "=" not in a), None)
    shot = next((a for a in args if a.endswith(".png")), None)
    if page:
        QTimer.singleShot(200, lambda: win.open_page(page))
        if scroll:
            QTimer.singleShot(1300, lambda: win.pages[page].scroll.verticalScrollBar().setValue(scroll))
    if shot:
        def grab():
            win.grab().save(shot)
            app.quit()
        QTimer.singleShot(1600 if page else 600, grab)
    app.exec()


if __name__ == "__main__":
    main()
