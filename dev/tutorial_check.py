"""Walks the tutorial (ui/tutorial.py) from its first chapter to its end on a copy of the settings, clicking where
the user would (QTest on the pretend desk) and speaking with Tutorial.hear (no microphone, no recognizer), and saves
a screenshot after each step.

    .venv/Scripts/python dev/tutorial_check.py OUT_DIR [--dark] [--miss]

--miss reads the first sentence wrong first (復原 needed), and says one stray command.
"""
import sys
from pathlib import Path

sys.argv.append("--light") if "--dark" not in sys.argv else None
import settings_preview as sp  # noqa: E402  (copies the user's data to a temp folder first)

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from artvoiceinput import config  # noqa: E402
from artvoiceinput.hotwords import Hotwords  # noqa: E402
from artvoiceinput.memory import Memory  # noqa: E402
from artvoiceinput.ui.window import SettingsWindow  # noqa: E402


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)

    def fail(*exc):
        sys.__excepthook__(*exc)
        app.exit(1)
    sys.excepthook = fail
    cfg = config.Config.load()
    cfg.theme = "dark" if "--dark" in sys.argv else "light"
    win = SettingsWindow(cfg, Hotwords(sp.TMP / "hotword-list.json"), Memory(sp.TMP / "smart-picks.json"))
    win.load_values()
    win.show()
    win.start_tutorial(0, replay=True)
    t = win.tutorial
    d = t.desk
    e = d.notepad.edit
    n = [0]

    def shot(name):
        n[0] += 1
        win.grab().save(str(out / f"{n[0]:02d}-{name}.png"))
        print(n[0], name, "|", t.strip.chapter, t.card.text.text()[:40], "| status:", t.card.status.text(),
              "| notepad:", repr(e.text), flush=True)

    def nxt():
        t._event("next")

    def click(widget, pos):
        QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, pos)

    def orb(o):
        click(o, QPoint(o.width() // 2, o.height() // 2))

    def char_pos(box, i):
        r = box.char_rect(i, i + 1)
        return box.mapFrom(d, r.center())

    def select(box, a, b):
        QTest.mousePress(box, Qt.LeftButton, Qt.NoModifier, char_pos(box, a) - QPoint(6, 0))
        box.caret = b   # QTest can't drag with the button held: the end of the drag set as a move would
        box._drag = True
        QTest.mouseRelease(box, Qt.LeftButton, Qt.NoModifier, char_pos(box, b - 1) + QPoint(6, 0))

    miss = "--miss" in sys.argv
    steps = [
        (shot, "intro"), (nxt,), (shot, "intro2"), (nxt,), (shot, "ask-notepad"),
        (lambda: click(d, d.taskbar_rect("notepad").center()),), (shot, "notepad-open"),
        (lambda: click(e, QPoint(200, 60)),), (shot, "bubble"),
        (lambda: orb(d.bubble),), (shot, "listening"), (nxt,), (shot, "listening2"), (nxt,), (shot, "read"),
    ]
    if miss:
        steps += [(lambda: t.hear(("cmd", "結束")),), (shot, "stray-command"),
                  (lambda: t.hear(("text", "今天天氣很好，我們去公司上班。")),), (shot, "miss"),
                  (lambda: t.hear(("text", "隨便說說")),), (shot, "miss-text-again"),
                  (lambda: t.hear(("cmd", "復原")),), (shot, "undone")]
    steps += [
        (lambda: t._partial(t._token, ("text", "今天天氣很好")),), (shot, "partial"),
        (lambda: t.hear(("text", "今天天氣很好，我們去公圓散步。")),), (shot, "read-ok"), (nxt,), (shot, "redecode-line"),
        (nxt,), (shot, "ask-period"), (lambda: t.hear(("cmd", "句號")),), (shot, "committed"), (nxt,), (nxt,),
        (shot, "ask-newline"), (lambda: t.hear(("cmd", "換行")),), (shot, "ask-umbrella"),
        (lambda: t.hear(("text", "記得帶雨傘。")),), (shot, "umbrella"), (lambda: t.hear(("cmd", "復原")),),
        (shot, "undo-done"), (nxt,), (shot, "pick-intro"), (nxt,), ("wait", 1200), (shot, "planted"),
        (lambda: QTest.mouseDClick(e, Qt.LeftButton, Qt.NoModifier, char_pos(e, e.text.rfind("定"))),),
        ("wait", 300), (shot, "picker"),
        (lambda: d.picker.pick("訂"),), (shot, "picked"), (nxt,), (shot, "pick-memory"), (nxt,),
        (shot, "ask-select"), (lambda: select(e, e.text.rfind("一張"), e.text.rfind("一張") + 2),),
        (shot, "selected"), (lambda: t.hear(("text", "兩張。")),), (shot, "replaced"), (nxt,),
        (shot, "described-intro"), (nxt,), (shot, "ask-described"), (lambda: t.hear(("text", "節日的節。")),),
        (shot, "described"), (nxt,), (shot, "send-intro"), (nxt,), ("wait", 700), (shot, "chat"),
        (lambda: t.hear(("text", "我等一下就到。")),), (shot, "chat-draft"), (lambda: t.hear(("cmd", "送出")),),
        ("wait", 1300), (shot, "sent"), (lambda: print("glow", d.glow.level, d.glow.isVisible()),), (nxt,), (shot, "ask-reopen"),
        (lambda: click(d.chat.edit, QPoint(60, 20)),), ("wait", 400), (shot, "chat-bubble"),
        (lambda: orb(d.bubble),), ("wait", 500), (shot, "ask-off"), (lambda: orb(d.float),), (shot, "off"),
        (nxt,), (nxt,), (shot, "last"), (nxt,), ("wait", 500), (shot, "finished"),
    ]

    def run(i=0):
        if i >= len(steps):
            print("done; tutorial visible:", t.isVisible(), flush=True)
            app.quit()
            return
        step = steps[i]
        delay = 450
        if step[0] == "wait":
            delay = step[1]
        elif len(step) == 2:
            step[0](step[1])
        else:
            step[0]()
        QTimer.singleShot(delay, lambda: run(i + 1))
    QTimer.singleShot(800, run)
    app.exec()


if __name__ == "__main__":
    main()
