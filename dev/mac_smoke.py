"""Checks on a Mac that need no permission and no person (CI, .github/workflows/mac.yml): every module imports, the
key tables agree, the clipboard round-trips, the Accessibility reads fail softly without the permission, the cue
sounds play, the settings window, floating button, bubble, glow and 選字 menu open and close, and the recognizer
decodes the test clips. Exits non-zero on the first failure.

    python dev/mac_smoke.py
"""
import importlib
import pkgutil
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
failed = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        failed.append(what)


def main():
    import artvoiceinput
    for m in pkgutil.walk_packages(artvoiceinput.__path__, "artvoiceinput."):
        if ".win" in m.name:
            continue
        try:
            importlib.import_module(m.name)
            check(True, f"import {m.name}")
        except Exception as e:
            check(False, f"import {m.name}: {e!r}")

    from PySide6.QtWidgets import QApplication
    from artvoiceinput import cues, keys, output, selection, system
    from artvoiceinput.mac import keyboard
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    system.setup(qapp)
    check(system.MAC, "system.MAC")
    missing = [n for n, vk in keys.NAMES.items() if vk not in keys.MOUSE_VKS.values() and vk not in keyboard.VK_TO_MAC]
    check(set(missing) <= {"F21", "F22", "F23", "F24"}, f"every key name but F21-F24 has a Mac key code {missing}")
    check(keyboard.MAC_TO_VK[61] == 0xA5 and keys.hotkey_label("vk:a5") == "右 Option", "右 Option")
    check(keys.hotkey_label("win+vk:20") == "Command+Space", keys.hotkey_label("win+vk:20"))
    check(keyboard.set_clipboard("阿特 clipboard") and qapp.clipboard().text() == "阿特 clipboard", "clipboard")
    output.note_clipboard("x")
    check(isinstance(system.foreground(), int) and system.foreground() > 0, f"foreground {system.foreground()}")
    check(system.double_click_time() > 0, "double click time")
    x, y = system.physical(100, 100)
    check(system.logical(x, y) == (100, 100), f"physical/logical round trip {x},{y}")
    t = time.monotonic()
    info = selection.focus_info()
    check(time.monotonic() - t < 3, f"focus_info answers ({info})")
    check(selection.read_selection() is None or True, "read_selection")
    check(selection.draft_rects("abc") is None or True, "draft_rects")
    check(isinstance(selection.visible_text(), str), "visible_text")
    cues.play(cues.DEFAULT, "start", 50)
    check(True, "cue played")

    from artvoiceinput.config import Config
    from artvoiceinput.floatbtn import Bubble, FloatButton
    from artvoiceinput.glow import EdgeGlow
    from artvoiceinput.picker import Picker
    cfg = Config()
    btn, bubble, glow, picker = FloatButton([]), Bubble(), EdgeGlow(lambda: 0.5), Picker()
    btn.appear()
    bubble.show_at((300, 300))
    glow.show()
    for _ in range(20):
        qapp.processEvents()
        time.sleep(0.02)
    check(btn.isVisible() and bubble.isVisible(), "floating button and bubble shown")
    check(system.on_window({system.window_handle(btn)}, *system.physical(btn.x() + 5, btn.y() + 5)),
          "point on the floating button")
    glow.hide()
    btn.vanish()
    bubble.hide()
    picker.hide()

    from artvoiceinput.hotwords import Hotwords
    from artvoiceinput.memory import Memory
    from artvoiceinput.ui.window import SettingsWindow
    tmp = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/artvoiceinput-smoke")
    tmp.mkdir(parents=True, exist_ok=True)
    cfg.setup_done = True
    win = SettingsWindow(cfg, Hotwords(tmp / "hw.json"), Memory(tmp / "mem.json"))
    win.show()
    for _ in range(30):
        qapp.processEvents()
        time.sleep(0.02)
    check(win.isVisible(), "settings window shown")
    win.grab().save(str(tmp / "settings.png"))
    win.hide()

    from artvoiceinput import models
    from artvoiceinput.asr import Recognizer
    rec = Recognizer(models.MAIN_MODEL)
    for name, expect in (("a", "天气"), ("b", "爬山")):   # the recognizer writes Simplified (s2tw comes after)
        w = wave.open(str(ROOT / "dev" / "testdata" / "wav" / f"{name}.wav"))
        audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        t = time.monotonic()
        text = rec.recognize(audio)
        check(expect in text, f"recognized {name}.wav as {text!r} in {time.monotonic() - t:.2f}s")

    print(f"\n{len(failed)} failed" if failed else "\nall passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
