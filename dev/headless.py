r"""Headless end-to-end test: the real App (model, selection edits, double tap) with a simulated text box in
place of the focused app, so nothing is typed into real windows. Audio comes from TTS wav files.

  .venv\Scripts\python.exe dev\headless.py <dir> step,step,...

Each step is a wav name in <dir>/wav (the hotkey pressed before and after it is spoken), sel:WORD (select the last WORD in the
box), mousesel:WORD (the same with the mouse: the 選字 menu may open while listening), floatclick (the floating
button is clicked), window:N (window N comes to the front; the text box is 4242), settings (the settings window opens in front), focus:box:N / focus:none (what the
focus watcher reads: text box N, or a place where nothing can be typed), click (the user clicks: ends what the app knows about the text), tap (one press of the hotkey), toggle:WAV (tap,
speak, tap), hotkey:SPEC (the hotkey, keys.parse_hotkey; default mouse_middle), rules:default (the default operations),
rule:JSON (add an operation, rules.Rule.from_dict), at:WORD (put the caret right after the last WORD; at: puts it at
the end), say:TEXT (dictate TEXT as if recognized), op:PHRASE (a spoken operation of the
user's config run without audio), clip:TEXT (the box's clipboard; the real one is never read), nocaret (the next
probe cannot read the caret's line), set:NAME=VALUE (change a setting in memory only; apply: as the settings window does after a change), packs:ID+ID (tick term packs, in memory only) or key:BACK (the
user presses Backspace n times: key:BACK*3), key:ENTER (the user presses Enter), pick:N / pickw:WORD (click a row of the 選字 menu), feed:WAV (while
continuous listening is on: WAV and 1s of silence reach the microphone; feed:WAV+WAV joins clips with 0.6s pauses),
logshot:NAME (the 辨識紀錄 tab saved as <dir>/NAME.png), wait:SEC (silence for SEC seconds), tap0 (a tap; the next step starts at once, while queued work
still runs), racemove:WORD (the caret moves after the last WORD, at the end when empty, right
before the next draft update reaches the document). Settings are never saved; hotwords and smart picks live in <dir> (hotwords.test.json,
smart-picks.test.json, emptied at the start), never in the real files.
"""
import json
import shutil
import sys
import time
import wave
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from artvoiceinput import app as appmod, listen, output, rules, selection, session  # noqa: E402

S = sys.argv[1]
HWND = 4242


class Box:
    """A text box with a caret and an optional selection."""

    def __init__(self):
        self.text, self.sel, self.caret = "", None, 0      # sel: (start, end)
        self.clip = ""                                     # what Ctrl+C / Ctrl+X put on the clipboard

    def paste(self, s):
        if self.sel:
            self.delete()
        self.text = self.text[:self.caret] + s + self.text[self.caret:]
        self.caret += len(s)

    def back(self, n):
        n = min(n, self.caret)
        self.text = self.text[:self.caret - n] + self.text[self.caret:]
        self.caret -= n

    def delete(self):
        if self.sel:
            a, b = self.sel
            self.text, self.sel, self.caret = self.text[:a] + self.text[b:], None, a

    def selection(self):
        if not self.sel:
            return None
        a, b = self.sel
        line_start = self.text.rfind("\n", 0, a) + 1
        line_end = self.text.find("\n", b)
        line_end = len(self.text) if line_end < 0 else line_end
        return selection.Selection(self.text[a:b], self.text[line_start:a], self.text[b:line_end], "fake.exe")

    def caret_context(self):
        if self.sel:
            return None
        start = self.text.rfind("\n", 0, self.caret) + 1
        end = self.text.find("\n", self.caret)
        return self.text[start:self.caret], self.text[self.caret:len(self.text) if end < 0 else end]

    def keys(self, *vks):
        """Shift+Enter types a newline; Enter sends the text (the box is emptied); others are printed."""
        if vks == (0x10, 0x0D):
            self.paste("\n")
        elif vks == (0x08,):   # Backspace deletes a selection, as in a real text box
            self.delete() if self.sel else self.back(1)
        elif vks == (0x0D,):
            print(f"      [送出] {self.text!r}")
            self.text, self.caret = "", 0
        elif vks == (0x20,):
            self.paste(" ")
        elif vks in ((0x11, 0x43), (0x11, 0x58)):   # Ctrl+C / Ctrl+X: the box's own clipboard
            if self.sel:
                self.clip = self.text[self.sel[0]:self.sel[1]]
                if vks[1] == 0x58:
                    self.delete()
        elif vks == (0x11, 0x56):   # Ctrl+V
            self.paste(self.clip)
        else:
            print(f"      [按鍵] {[hex(v) for v in vks]}")


box = Box()
for mod in (appmod, output):
    mod.paste_text = box.paste
appmod.backspace = box.back
appmod.press_delete = box.delete
appmod.press_chord = box.keys


def _press_key(vk, n=1):
    """Left moves the caret, Delete deletes after it; others are printed."""
    if vk == 0x25:
        box.caret = max(0, box.caret - n)
    elif vk == 0x2E:
        box.text = box.text[:box.caret] + box.text[box.caret + n:]
    else:
        box.keys(*([vk] * n))


appmod.press_key = _press_key
appmod._clipboard_text = lambda: box.clip   # never the user's real clipboard
appmod.watch_clipboard = lambda: None
appmod.terminal_in_front = lambda: False       # the box is no terminal, whatever window is really in front
appmod.foreground = session.foreground = lambda: HWND
appmod.Hotkeys.start = lambda self: None           # no real hotkey / keyboard hook
appmod.App._watch_mouse = lambda self: None       # the user's real clicks must not end the simulated session


class Listener(appmod.Listener):
    """Continuous listening without the microphone: feed:WAV puts audio where the microphone would."""

    def start(self, device_name="", quick=False):
        import sherpa_onnx
        import threading
        cfg = self._vad_config(listen.SILENCE)
        fast = self._vad_config(listen.QUICK_SILENCE) if quick and self._on_quick is not None else None
        import queue
        self._queue, self._discard = queue.Queue(), False
        self._thread = threading.Thread(target=self._run, daemon=True, args=(
            lambda: sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=40), cfg.silero_vad.window_size,
            self.now, (lambda: sherpa_onnx.VoiceActivityDetector(fast, buffer_size_in_seconds=40)) if fast else None))
        self._thread.start()
        self._stream = True

    def stop(self, discard=False):
        self._discard = discard
        self._stream = None
        self._queue.put(None)
        self._thread.join(5)


appmod.Listener = Listener


no_caret = []   # nocaret: the next probe cannot read the caret's line (as UI Automation fails in some apps)


class Probe:
    def __init__(self, *_):
        caret = None if no_caret and no_caret.pop() else box.caret_context()
        self._ctx = selection.Context(box.selection(), [], caret)

    def result(self, timeout=2.0):
        return self._ctx


appmod.ContextProbe = Probe
_Hotwords, _Memory = appmod.Hotwords, appmod.Memory
for name in ("hotwords.test.json", "smart-picks.test.json"):
    (Path(S) / name).unlink(missing_ok=True)
appmod.Hotwords = lambda: _Hotwords(Path(S) / "hotwords.test.json")
appmod.Memory = lambda: _Memory(Path(S) / "smart-picks.test.json")
appmod.recordings.DIR = Path(S) / "recordings"   # set:save_recordings=1 saves here, never in the real folder
appmod.recordings.INDEX = appmod.recordings.DIR / "index.jsonl"
qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
appmod.EdgeGlow.show = lambda self, screen=None: None   # no glow on the user's screen
appmod.DraftMarks.show = lambda self, rects: None   # nor marks over their own app's text
appmod.FloatButton.appear = lambda self: print("      [浮動按鈕 顯示]")   # nor the floating button
appmod.FloatButton.vanish = lambda self: print("      [浮動按鈕 隱藏]")
appmod.FloatButton.burst = lambda self: print("      [浮動按鈕 放大淡出]")
appmod.FloatButton.come_back = lambda self: print("      [浮動按鈕 縮回淡入]")
appmod.FloatButton.jump = lambda self: print("      [浮動按鈕 彈一下]")
appmod.Bubble.burst = lambda self: (print("      [語音氣泡 放大淡出]"), self.hide())
appmod.focus_info = lambda: (None, None)   # the real focus is the user's: focus: steps say what it is
_show_at, _come_back = appmod.Bubble.show_at, appmod.Bubble.come_back_here
appmod.Bubble.show_at = lambda self, pt: (print(f"      [語音氣泡 在 {pt}]"), _show_at(self, pt))
appmod.Bubble.come_back_here = lambda self: (print("      [語音氣泡 縮回淡入]"), _come_back(self))
A = appmod.App(qapp)
A.tray.hide()
A.tray.showMessage = lambda title, text, *a: print(f"      [通知] {title}: {text}")


class Muter:
    """Stands in for the speaker mute (never mutes the real speakers): prints what it would do."""
    active = False

    def mute(self):
        if not self.active:
            self.active = True
            print("      [靜音]")

    def restore(self):
        if self.active:
            self.active = False
            print("      [解除靜音]")


A.muter = Muter()
A.cfg.save = lambda: None   # settings are never saved (the pack hint saves config.json)
appmod.cues.play = lambda cue, kind: print(f"      [音效] {kind}: {cue or '（無）'}")   # printed, not played


def pump(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)


def feed(audio):
    """What the microphone hears while listening: audio and 1s of silence."""
    audio = np.concatenate([audio, np.zeros(16000, np.float32)])
    seen = box.text
    for i in range(0, len(audio), 480):
        A.listener._queue.put(audio[i:i + 480])
        if i % 4800 == 0:
            pump(0.1)   # real time: 0.3s of audio every 0.1s
            if box.text != seen:
                seen = box.text
                print(f"      [{i / 16000:4.1f}s] {seen!r}")


def load(name):
    w = wave.open(f"{S}/wav/{name}.wav")
    return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


KEY = A.cfg.hotkey = "mouse_middle"
A.hotkeys.set_hotkey(KEY)


def _steps(arg: str) -> list[str]:
    """Split on commas outside the braces of rule:JSON."""
    out, depth, cur = [], 0, ""
    for c in arg:
        depth += (c in "{[") - (c in "}]")
        if c == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += c
    return out + [cur]


def menu() -> str:
    if not A.picker.isVisible():
        return ""
    return f"   氣泡：{A.picker.tabs}"


def _last_row() -> str:
    rows = [r for g in A.book.sessions for r in g["rows"]]
    return rows[-1]["heard"] if rows else ""


def user_input():
    """A key or click of the user's, as the hooks report it."""
    A.session.on_input()
    A.main.emit(A._caret_left)


def tap():
    A.hotkey_tap.emit()            # what the hook reports


t0 = time.monotonic()
while time.monotonic() - t0 < 120 and not A.recognizer:
    pump(0.3)
pump(2)
try:
    for step in _steps(sys.argv[2]):
        if step.startswith("focus:") or step.startswith("click:"):
            # focus:box:N (the focus in text box N), focus:none (where nothing is typed); click:box:N / click:none
            # the same after a left click there (the bubble shows by it)
            what = step[6:]
            if step.startswith("click:"):
                A._clicked((150, 110))
            if what == "none":
                A._focus_seen(False, (1, ()), time.monotonic())
            else:
                A._focus_seen(True, (HWND, (int(what.split(":")[1]),)), time.monotonic())
            pump(1.0)
            print(f"[焦點 {what}] 聽寫中：{A._listening}  氣泡：{A.bubble.isVisible()}")
            continue
        if step.startswith("window:"):   # window:N puts window N in front (the text box is 4242)
            hwnd = int(step[7:])
            appmod.foreground = session.foreground = lambda: hwnd
            pump(1.5)
            print(f"[切換視窗 {hwnd}] 聽寫中：{A._listening}")
            continue
        if step == "settings":   # the settings window opens in front (the focus in it)
            A.settings.show()
            hwnd = int(A.settings.winId())
            appmod.foreground = session.foreground = lambda: hwnd
            pump(1.5)
            print(f"[設定視窗在前面] 聽寫中：{A._listening}")
            continue
        if step == "floatclick":   # the floating button is clicked
            A._float_clicked()
            pump(0.5)
            print(f"[點浮動按鈕] 聽寫中：{A._listening}")
            continue
        if step.startswith("mousesel:"):   # the user selects the last WORD with the mouse (a drag)
            w = step[9:]
            i = box.text.rfind(w)
            box.sel, box.caret = (i, i + len(w)), i + len(w)
            user_input()
            A._pick_gen += 1
            A._auto_pick()
            pump(1.0)
            print(f"[滑鼠選取 {w}]{menu()}")
            continue
        if step.startswith("sel:"):
            w = step[4:]
            i = box.text.rfind(w)
            box.sel, box.caret = (i, i + len(w)), i + len(w)
            user_input()
            print(f"[選取 {w}]")
            continue
        if step == "tap" or step.startswith("toggle:"):
            tap()
            if step.startswith("toggle:"):
                pump(0.2)
                if A._listening:
                    feed(load(step[7:]))
                    pump(2.0)
                tap()
            pump(2.5 if step.startswith("toggle:") else 1.0)
            print(f"[{step}] → 文字框：{box.text[:box.caret] + '|' + box.text[box.caret:]!r}{menu()}")
            continue
        if step.startswith("wait:"):   # nothing happens for SEC seconds (the microphone hears silence)
            end = time.monotonic() + float(step[5:])
            while time.monotonic() < end:
                if A._listening:
                    A.listener._queue.put(np.zeros(4800, np.float32))
                pump(0.3)
            print(f"[{step}] 聽寫中：{A._listening}")
            continue
        if step == "tap0":   # a tap, and the next step right when it is known to be one (queued work still runs)
            tap(), pump(0.05)
            print(f"[tap0] 聽寫中：{A._listening}")
            continue
        if step.startswith("racemove:"):   # the caret moves (to after WORD) right before the next draft update
            w, refine = step[9:], A._refine

            def moved_first(*args, w=w, refine=refine):
                A._refine = refine
                box.sel = None
                box.caret = box.text.rfind(w) + len(w) if w else len(box.text)
                user_input()
                print(f"      [游標移到 {w!r} 後面] {box.text[:box.caret] + '|' + box.text[box.caret:]!r}")
                refine(*args)
            A._refine = moved_first
            continue
        if step.startswith("hotkey:"):
            KEY = A.cfg.hotkey = step[7:]
            A.hotkeys.set_hotkey(KEY)
            print(f"[按鍵 {KEY}]")
            continue
        if step == "rules:default":
            A.cfg.rules = rules.defaults()
            print("[預設操作]")
            continue
        if step.startswith("rule:"):
            A.cfg.rules.append(rules.Rule.from_dict(json.loads(step[5:])))
            print(f"[新增操作] {A.cfg.rules[-1]}  {rules.problems(A.cfg.rules[-1], A.cfg.rules) or ''}")
            continue
        if step.startswith("set:"):
            name, value = step[4:].split("=")
            setattr(A.cfg, name, type(getattr(A.cfg, name))(int(value) if value.isdigit() else value))
            print(f"[設定 {name} = {getattr(A.cfg, name)!r}]（只改記憶體，不存檔）")
            continue
        if step == "apply":   # what the settings window does after a change
            A.apply_settings()
            pump(8.0)
            print("[套用設定]")
            continue
        if step.startswith("packs:"):
            ids = [i for i in step[6:].split("+") if i]
            A.hotwords.set_packs(appmod.packs.words_for(ids), appmod.packs.PCT)
            print(f"[詞包 {ids}]（只改記憶體，不存檔）")
            continue
        if step.startswith("say:"):
            A._type_text(step[4:])
            pump(0.5)
            print(f"[說 {step[4:]}（跳過辨識）] → 文字框：{box.text[:box.caret] + '|' + box.text[box.caret:]!r}")
            continue
        if step.startswith("op:"):   # a spoken operation said, without its audio
            rule = next(r for r in A.cfg.rules if r.source == rules.SPEECH and r.phrase == step[3:])
            ctx = Probe().result()
            A._run_command((rule, None, {}), ctx, ctx.selection)
            pump(1.0)
            print(f"[說 {step[3:]}] → 文字框：{box.text[:box.caret] + '|' + box.text[box.caret:]!r}")
            continue
        if step == "nocaret":
            no_caret.append(True)
            continue
        if step.startswith("clip:"):
            box.clip = step[5:]
            continue
        if step.startswith("at:"):
            w = step[3:]
            box.sel = None
            box.caret = box.text.rfind(w) + len(w) if w else len(box.text)
            user_input()
            print(f"[游標移到] → 文字框：{box.text[:box.caret] + '|' + box.text[box.caret:]!r}")
            continue
        if step.startswith(("pick:", "pickw:")):
            shown = A.picker.isVisible()
            if shown:
                rows = A.picker.candidates
                i = int(step[5:]) - 1 if step.startswith("pick:") else rows.index(step[6:]) if step[6:] in rows else -1
                if 0 <= i < len(rows):
                    A.picker.pick(rows[i])
            pump(0.5)
            print(f"[{step}] {'' if shown else '（沒有氣泡）'} → 文字框：{box.text[:box.caret] + '|' + box.text[box.caret:]!r}"
                  f"  熱詞：{A.hotwords.bias()}")
            continue
        if step.startswith("feed:"):
            if not A._listening:
                print(f"[{step}]（沒有在聽寫）")
                continue
            parts = []
            for name in step[5:].split("+"):
                parts += [load(name), np.zeros(int(0.6 * 16000), np.float32)]
            feed(np.concatenate(parts[:-1]))
            pump(3.0)
            print(f"[{step}] → 文字框：{box.text[:box.caret] + '|' + box.text[box.caret:]!r}{menu()}")
            continue
        if step == "click":
            user_input()
            print("[點滑鼠]")
            continue
        if step.startswith("logshot:"):   # logshot:NAME, or logshot:NAME:all (a tall window)
            name, _, every = step[8:].partition(":")
            if every:
                A.settings.resize(A.settings.width(), 1500)   # tall enough to see them
            step = "logshot:" + name
            A.settings.set_log(A.book.sessions)
            A.settings.tabs.setCurrentIndex(2)   # 辨識紀錄
            A.settings.show()
            pump(0.3)
            A.settings.grab().save(f"{S}/{step[8:]}.png")
            print(f"[辨識紀錄截圖 {S}/{step[8:]}.png]")
            continue
        if step == "key:ENTER":   # the user presses Enter (sends: the box empties)
            A._on_other_key(0x0D)
            box.text, box.caret, box.sel = "", 0, None
            pump(1.0)
            print(f"[按 Enter] 聽寫中：{A._listening}")
            continue
        if step.startswith("key:BACK"):
            n = int(step.split("*")[1]) if "*" in step else 1
            box.back(n)
            for _ in range(n):
                user_input()
            print(f"[按 Backspace ×{n}]")
            continue
        tap()
        pump(0.2)
        if A._listening:
            feed(load(step))
        tap()
        pump(2.5)
        shown = box.text[:box.caret] + "|" + box.text[box.caret:]
        print(f"[{step}] {_last_row()!r:32} → 文字框：{shown!r}{menu()}")
finally:
    A.quit()
    shutil.rmtree(Path(S) / "__pycache__", ignore_errors=True)
