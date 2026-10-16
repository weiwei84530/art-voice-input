"""VoiceInput: single-process tray app. Listening is turned on and off from the interface (the floating button, the
bubble by the caret, or the focus coming into a text box: on_focus), or by tapping the one hotkey (a mouse button
or keyboard key, the 一般 tab; 2026-10-16, the user's design: nothing else is bound to keys any more).

What an utterance does:
1. Text is selected (UI Automation): the utterance replaces it.
2. Otherwise it is dictated: formatted and pasted.
An utterance that is exactly a custom operation's phrase (換行, 送出 …) runs that operation instead, and a bare
punctuation name (逗號, 句號 …) is typed as the mark (edit.symbol; a setting since 2026-10-11), and 節日的節 types
節 (edit.described, a setting). Dictated text then
goes through the smart picks (memory.py, single characters only); words are left to X-ASR hotword biasing.

Spoken operations are set on the 自訂操作 tab (rules.py): 換行, 送出, 復原 / 撤銷, 刪除 (Backspace) and a few more.
While listening, a short mouse selection opens 選字 by itself. A hold or double tap of the hotkey is given back to
the key or button.

Recording is continuous listening (listen.py; on the continuous-mic branch since 2026-10-14 the one way, the
user's choice: no cutting the recording to say a command). Every pause ends a piece: said alone, an operation's
phrase or a punctuation name commits the draft and runs or types it; otherwise the piece joins the draft, which is
decoded again and typed in place (in place of the text selected when its speech began, if any: the user may select
with the mouse while listening), punctuation included; only its open sentence is decoded again (text up to a mark
the recognizer put in a pause is settled). A commit (by a command, the end of listening, or every pause when
commit_at says so) decodes the open sentence once more; by an operation or the end of listening it keeps the
recognizer's 。？！ or gets 。 (a spoken mark is typed instead). Moving the caret leaves a draft as typed, and speech
not typed yet is decoded again at the new caret. Other gestures work while listening.

The one popup (picker.py) is the 選字 candidate menu; it came back 2026-10-11 after the lean branch removed every
popup and was redesigned 2026-10-16 (tabs by how close the candidates sound, no input box). The second opinion
(SenseVoice + suspects.py) is commented out below.
"""
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QLockFile, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QGuiApplication, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import autostart, candidates, cues, edit, models, packs, paths, recordings, rules, sounds, spelling
from .asr import SAMPLE_RATE, Recognizer
from .config import Config
from .floatbtn import Bubble, FloatButton
from .glow import EdgeGlow
from .highlight import DraftMarks, draft_rects
from .logbook import LogBook, esc
from .hotwords import Hotwords
from .hotkey import Hotkeys
from .keys import MOUSE_TRIGGERS, combo_vks
from .listen import LEAD, Listener
from .memory import Memory, is_latin, situation
from .mute import Muter
from .output import backspace, copy_text, paste_text, press_chord, press_delete, press_key, restore_now
from . import picker as picker_mod
from .picker import Picker
from .reading import reading_key
from .rules import DOUBLE, HOLD, TAP
from .selection import (Context, ContextProbe, focus_info, move_cursor_after, term_watcher,
                        terminal_in_front)
from .session import Session, foreground
from .settings import SettingsDialog
from .textfmt import format_text, to_traditional

log = logging.getLogger("voiceinput")

_SCREEN_TERM_SCORE = 1.5
# Spoken commands (speech operations' phrases, punctuation names) are boosted only when the utterance is short: they
# are said alone, and boosting them in every sentence would turn 還行 into 換行 (the user's choice, 2026-10-11).
# "Short" is judged by the first decode's text (at most the longest command + _COMMAND_SLACK characters), which then
# runs again with the commands: the audio's length was no use, TTS 換行 alone was already 1.7s with its silences.
# With TTS the boost fixed 據點 -> 句點 and 珊姐好 -> 刪節號; alone, 問好 / 分好 became 問號 / 分號.
_COMMAND_SCORE = 5.0
_COMMAND_SLACK = 2
_WORDS = re.compile(r"[㐀-䶿一-鿿]|[A-Za-z0-9]+")   # a Chinese character or an English word counts one
_SEL_LOST = "找不到選取的文字，沒有修改"   # a terminal selection that moved or the cursor could not reach
# from the call to PlaySound until the start sound has left the speakers: measured 0.17s on the user's machine
# (Realtek speakers, Logi C270 microphone, 2026-10-13); the level bars and muting wait the sound's length plus this,
# or Kalimba's tail moved the bars and Woodblock (0.19s) was muted before it was heard
_CUE_LATENCY = 0.25
_STEP_GAP = 0.03           # seconds between the steps of an operation
_DRAFT_MAX = 60            # seconds: a longer draft is committed at a pause (decoding it again gets slow)
_TAP_MAX = 0.6             # seconds: a press no hold operation takes, released sooner, is a tap
_SPACED = re.compile(r"[A-Za-z0-9]")
_PICK_ZH = re.compile(r"[㐀-䶿一-鿿]{1,4}")
_PICK_EN = re.compile(r"[A-Za-z][\w'.+-]*(?: [\w'.+-]+){0,2}")


def _one_command(raw: str, names: list) -> str:
    """A command the boost repeated (結束結束結束, like 點點點 before it) as said once."""
    said = rules.normalize(to_traditional(raw))
    for n in names:
        n = rules.normalize(n)
        if n and len(said) > len(n) and len(said) % len(n) == 0 and said == n * (len(said) // len(n)):
            return n
    return raw


def _pickable(text: str) -> bool:
    """Short enough for the 選字 menu to open by itself: up to 4 Chinese characters or 3 English words."""
    t = text.strip()
    return bool(_PICK_ZH.fullmatch(t) or _PICK_EN.fullmatch(t) and t.isascii())


def _double_click_time() -> float:
    import ctypes
    return ctypes.windll.user32.GetDoubleClickTime() / 1000


def foreground_pid() -> int:
    import ctypes
    import ctypes.wintypes
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.windll.user32.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value


@dataclass
class _Press:
    """One press of a key or mouse button that some operation uses."""
    key: str
    probe: object                     # ContextProbe started at key-down (a double tap reuses the first tap's)
    down_at: float
    dictated: bool                    # the last dictation could still be deleted at key-down (情境「剛輸入完」)
    first: "_Press | None" = None     # the second press of a double tap: its first tap
    up_at: float = 0.0
    gesture: str = ""                 # tap / double / hold, once known
    rule: object = None               # the operation it runs (None: unbound, the gesture goes back to the key)
    decided: bool = False             # rule is known
    held: bool = False                # down for gesture_time or longer
    released: bool = False
    finished: bool = False
    deleted: object = None            # Selection a 刪除 step removed (the dictation goes there)


def make_icon(color: QColor) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(22, 6, 20, 34), 10, 10)          # mic capsule
    pen = QPen(color, 5)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(14, 16, 36, 34), 200 * 16, 140 * 16)     # holder
    p.drawLine(QPointF(32, 50), QPointF(32, 58))
    p.end()
    return QIcon(pm)


class App(QObject):
    key_down = Signal(str, float)            # key name, time
    key_up = Signal(str, float)
    main = Signal(object)                    # run a callable on the Qt main thread (keystrokes, clipboard, UI)
    candidates_ready = Signal(object, list)  # Selection, the 選字 menu's tabs
    record = Signal(dict)         # one transcript log entry for the settings window
    status = Signal(str)

    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.cfg = Config.load()
        self.recognizer: Recognizer | None = None
        # self.second: Recognizer | None = None         # second-opinion model (SenseVoice), off for now
        self.worker = ThreadPoolExecutor(max_workers=1)   # serializes model loads and transcription
        self.steps = ThreadPoolExecutor(max_workers=1)    # runs operations' steps in order
        # self.bg = ThreadPoolExecutor(max_workers=1)     # second opinion, second model load
        self._status_text = ""
        self.session = Session()
        self.muter = Muter()
        self._press: _Press | None = None        # the key or button held now
        self._pending: _Press | None = None      # a tap waiting to see whether a second press follows
        self._pending_timer = QTimer(self, singleShot=True, timeout=self._pending_expired)
        self.listener: Listener | None = None    # the microphone (listen.py)
        self._listen_owner: _Press | None = None   # the press whose operation turned listening on
        self._listen_shown = False               # it is known to listen: indicator and start sound
        self._early_pieces: list | None = None   # (Piece, probe) heard before that, handled once it is known
        self._early_lock = threading.Lock()
        self._listen_probe = None                # ContextProbe started when the latest speech began
        self._speech_sample = 0                  # where the latest speech began (with its lead-in)
        self._draft: _Draft | None = None        # text typed while listening, not committed yet
        self._draft_start = 0                    # the sample the draft's audio starts at (the last commit)
        self._quitting = False
        self._marked = None                      # the buffer when the last commit added its sentence-final mark
        self._committed = None                   # (text before it, _Draft, its history step): 復原 may revive it
        self._spans: list = []                   # worker thread: the pieces of the draft's open sentence
        self._ignored: set[str] = set()          # keys pressed while another was held
        self.hotwords = Hotwords()
        self._pack_stamp = None
        self._load_packs()
        self.memory = Memory()
        self._menu = None                        # ("pick", Selection) while the 選字 menu is up
        self._pick_gen = 0                       # mouse presses so far: a selection read late is dropped

        self.icon_idle = make_icon(QColor(235, 235, 235) if self._dark_taskbar() else QColor(40, 40, 40))
        self.icon_rec = make_icon(QColor(255, 69, 58))

        self._busy, self._busy_lock = 0, threading.Lock()   # decoding jobs queued or running
        self.glow = EdgeGlow(lambda: self.listener.level if self._listening else 0.0)
        self.glow.set_style(self.cfg.glow)
        self.glow.set_edges(self.cfg.glow_edges)
        self.float_btn = FloatButton(self.cfg.float_pos)
        self.float_btn.clicked.connect(self._float_clicked)
        self.float_btn.moved.connect(self._float_moved)
        self.bubble = Bubble()
        self.bubble.clicked.connect(lambda: self._listen_now("bubble"))
        self._own_hwnds = {self.float_btn.hwnd(), self.bubble.hwnd()}   # clicks on these are not caret moves
        self._box = None                         # the text box the focus is in (on_focus), its identity
        self._box_quiet = False                  # listening was turned off by hand in it: not on again by itself
        self._box_auto = False                   # listening was turned on by the focus
        self._focus_busy = False
        self._focus_pool = ThreadPoolExecutor(max_workers=1)   # its UI Automation reads (one COM object per thread)
        self._focus_timer = QTimer(self, interval=300, timeout=self._watch_focus)
        self._focus_timer.start()
        self.marks = DraftMarks(self.cfg.highlight_color)   # the draft drawn as if marked
        self._marks_pool = ThreadPoolExecutor(max_workers=1)   # UI Automation reads for it
        self._marks_busy = False
        self._marks_timer = QTimer(self, interval=150, timeout=self._mark_draft)
        self._marks_quiet = 0.0                  # no marks until then: the view is scrolling
        self.picker = Picker()
        self.picker.picked.connect(self.on_menu_pick)
        self.picker.closed.connect(self._forget_menu)
        self._picker_hwnd = int(self.picker.winId())
        self.settings = SettingsDialog(self.cfg, self.hotwords, self.memory)
        self.settings.applied.connect(self.apply_settings)
        self.book = LogBook(self._log_changed)   # the 辨識紀錄 tab, kept for this session only
        self.settings.glow_preview.connect(self._preview_glow)
        self._heard_at = 0.0                     # when speech last began while listening (auto_off_minutes)
        self._idle_timer = QTimer(self, interval=5000, timeout=self._check_idle)
        self._idle_timer.start()

        self.tray = QSystemTrayIcon(self.icon_idle)
        menu = QMenu()
        menu.addAction(QAction("設定…", menu, triggered=self.open_settings))
        menu.addSeparator()
        menu.addAction(QAction("結束", menu, triggered=self.quit))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.open_settings() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()

        self.key_down.connect(self.on_key_down)
        self.key_up.connect(self.on_key_up)
        self.main.connect(lambda fn: fn())
        self.candidates_ready.connect(self.on_candidates)
        self.status.connect(self.on_status)
        self.record.connect(self.on_record)

        self.hotkeys = Hotkeys(self.key_down.emit, self.key_up.emit, self._on_other_key)
        self.hotkeys.set_keys(self._hotkeys())
        self.hotkeys.start()
        self._mouse = self._watch_mouse()
        self.worker.submit(self._load_model_job)
        # self.bg.submit(self._load_second_job)
        candidates.preload()   # the disfluency pass uses the dictionary
        sounds.preload_english()   # 選字's near sounds for English
        if self.cfg.autostart:
            self._set_autostart()   # re-register so the entry follows the app if its folder was moved
        self._update_float()

    @staticmethod
    def _dark_taskbar() -> bool:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 0
        except OSError:
            return True

    def _on_other_key(self, vk: int):
        """Keyboard hook thread: a key the user pressed (injected keys never get here); it closes the 選字 menu."""
        self.session.on_input()
        term_watcher.forget()
        self.main.emit(self.picker.dismiss)
        self.main.emit(self.bubble.hide)   # typing: the bubble is in the way (the user's request, 2026-10-16)
        self.main.emit(self._caret_left)

    def _on_picker(self, pt) -> bool:
        """Mouse hook thread: the point is on the 選字 menu."""
        import ctypes.wintypes
        u32 = ctypes.windll.user32
        u32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
        hwnd = u32.WindowFromPoint(pt)
        return bool(hwnd) and u32.GetAncestor(hwnd, 2) == self._picker_hwnd   # GA_ROOT

    def _on_float(self, pt) -> bool:
        """Mouse hook thread: the point is on the floating button or the bubble."""
        import ctypes.wintypes
        u32 = ctypes.windll.user32
        u32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
        hwnd = u32.WindowFromPoint(pt)
        return bool(hwnd) and u32.GetAncestor(hwnd, 2) in self._own_hwnds   # GA_ROOT

    def _watch_mouse(self):
        """Any click may move the caret, which ends what session.py knows about the text before it. Left button
        drags may select text in a terminal (selection.TermWatcher). Our own clicks (injected) are skipped."""
        from pynput import mouse
        downs = {0x201, 0x204, 0x207, 0x20B}   # left / right / middle / x button down
        clicks = {"down": None, "n": 0, "at": 0.0, "pt": None}   # the left button, for _auto_pick

        def on_event(msg, data):
            if data.flags & 1:   # LLMHF_INJECTED
                return False
            if self.hotkeys.is_bound_mouse(msg, data.mouseData):
                return False   # a button an operation uses is not a click
            if msg in downs:
                if self._on_picker(data.pt) or self._on_float(data.pt):
                    return False   # a click in the 選字 menu or the floating button leaves the caret where it is
                self.main.emit(self.picker.dismiss)   # a click anywhere else closes it
                self.session.on_input()
                self.main.emit(self._caret_left)
                self._pick_gen += 1
                if msg == 0x201:
                    term_watcher.mouse_down(data.pt.x, data.pt.y)
                    clicks["down"] = (data.pt.x, data.pt.y)
                else:
                    term_watcher.forget()
                    clicks["down"] = None
            elif msg in (0x20A, 0x20E):   # the wheel: the view scrolls, the marks would trail behind it
                if self.marks.visible():
                    self.main.emit(self._scrolling)
            elif msg == 0x202:
                term_watcher.mouse_up(data.pt.x, data.pt.y)
                down, clicks["down"] = clicks["down"], None
                if down is not None and self._listening:
                    x, y = data.pt.x, data.pt.y
                    if abs(down[0] - x) + abs(down[1] - y) > 4:
                        clicks["n"] = 0
                        self.main.emit(self._auto_pick)   # a drag
                    else:
                        now, pt = time.monotonic(), clicks["pt"]
                        near = pt is not None and abs(pt[0] - x) + abs(pt[1] - y) <= 4
                        clicks["n"] = clicks["n"] + 1 if near and now - clicks["at"] <= _double_click_time() else 1
                        clicks["at"], clicks["pt"] = now, (x, y)
                        if clicks["n"] >= 2:
                            self.main.emit(self._auto_pick)   # a double (or triple) click
            return False   # never passed on to pynput's (unused) callbacks: keeps the hook cheap
        listener = mouse.Listener(win32_event_filter=on_event)
        listener.daemon = True
        listener.start()
        return listener

    # --- models ---
    def _load_model_job(self):
        key = models.MAIN_MODEL
        try:
            if not models.is_installed(key):
                def progress(done, total):
                    pct = f"{done * 100 // total}%" if total else f"{done >> 20} MB"
                    self.status.emit(f"下載模型中… {pct}")
                models.download(key, progress)
            self.status.emit("載入模型中…")
            self.recognizer = Recognizer(key)
            models.vad_path()   # continuous listening's voice activity detection, ~2MB
            self.status.emit("就緒")
        except Exception as e:
            log.exception("model load failed")
            self.status.emit(f"模型載入失敗：{e}")

    # def _load_second_job(self):
    #     key = models.SECOND_MODEL
    #     try:
    #         if not models.is_installed(key):
    #             models.download(key)
    #         t0 = time.monotonic()
    #         self.second = Recognizer(key)
    #         log.info("%s loaded in %.1fs", key, time.monotonic() - t0)
    #     except Exception:
    #         log.exception("%s failed to load", key)

    # --- gestures: which operation a press runs ---
    def _hotkeys(self) -> set:
        return {self.cfg.hotkey} if self.cfg.hotkey else set()

    def _rules_for(self, key: str, gesture: str) -> list:
        """The hotkey's one operation (2026-10-16, the user's design): a tap turns listening on or off. A hold or a
        double tap has none and is given back to the key."""
        if key != self.cfg.hotkey or gesture != TAP:
            return []
        source = rules.MOUSE if key in MOUSE_TRIGGERS else rules.KEY
        return [rules.Rule(source, key, gesture=TAP, steps=[rules.Step(rules.COMMAND, rules.RECORD)])]

    def _records_on(self, key: str, gestures) -> bool:
        return any(r.record_index() is not None for g in gestures for r in self._rules_for(key, g))

    def on_key_down(self, key: str, t: float):
        if self._press is not None:          # another key is held: this one is ignored
            self._ignored.add(key)
            return
        self._close_menu()
        pending, self._pending = self._pending, None
        self._pending_timer.stop()
        double = pending is not None and pending.key == key and t - pending.up_at < self.cfg.gesture_time
        if pending is not None and not double:
            self._decide(pending, TAP)       # another key came first: the tap is just a tap
        if double:
            press = _Press(key, pending.probe, t, pending.dictated, first=pending)
            if self._listen_owner is pending:
                self._listen_owner = press   # what the double tap does decides whether listening goes on
        else:
            press = _Press(key, ContextProbe(), t, self.session.deletable() is not None)
        self._press = press
        # listening starts now, unseen (no lost first syllable), whenever this press may turn it on
        if not self._listening and self._records_on(key, (DOUBLE, HOLD) if double else (TAP, HOLD)):
            self._start_listen(press)
        if double:
            self._decide(press, DOUBLE)
        QTimer.singleShot(int(self.cfg.gesture_time * 1000), lambda: self._hold_check(press, timer=True))

    def _hold_check(self, press: _Press, timer: bool = False):
        if press.released or press.held:
            return
        if timer and not self.hotkeys.is_down(press.key):
            # released already, the main thread has not handled it yet: a double tap's delete in a terminal kept it
            # busy past 0.3s, the press counted as held, recorded (delete and say it again) and played the end sound
            # (2026-10-13). on_key_up decides from the hook's times.
            return
        press.held = True
        if press.first is None:
            self._decide(press, HOLD)

    def on_key_up(self, key: str, t: float):
        if key in self._ignored:
            self._ignored.discard(key)
            return
        press = self._press
        if press is None or press.key != key:
            return
        self._press = None
        press.released, press.up_at = True, t
        log.info("press %s: %.2fs%s", key, t - press.down_at, " (second of a double tap)" if press.first else "")
        if not press.held and t - press.down_at >= self.cfg.gesture_time:   # the hold timer has not run yet
            self._hold_check(press)
        if press.first is None and not press.held:
            if key == self.cfg.hotkey:           # wait to see whether a second press follows (given back)
                if not self._records_on(key, (TAP,)):
                    self._discard_listen(press)
                self._pending = press
                self._pending_timer.start(int(self.cfg.gesture_time * 1000))
                return
            self._decide(press, TAP)
            return
        if press.decided:
            self._finish(press)

    def _pending_expired(self):
        press, self._pending = self._pending, None
        if press is not None:
            self._decide(press, TAP)

    def _decide(self, press: _Press, gesture: str):
        """Pick the operation for the gesture; waits for the selection probe only when the choice depends on it."""
        press.gesture = gesture
        cands = self._rules_for(press.key, gesture)
        if any(r.when == rules.SELECTION for r in cands):
            self._when_probed(press.probe, lambda ctx: self._apply(
                press, rules.pick(cands, ctx.selection is not None, press.dictated)))
        else:
            self._apply(press, rules.pick(cands, False, press.dictated))

    def _when_probed(self, probe, fn):
        """Run fn(Context) on the main thread once probe has read the focused app."""
        def wait():
            ctx = probe.result()
            self.main.emit(lambda: fn(ctx))
        threading.Thread(target=wait, daemon=True).start()

    def _apply(self, press: _Press, rule):
        """Main thread: start the operation: its steps (those before 錄音 when it records). 錄音 turns listening on;
        while listening, a tap or double tap that records turns it off and a hold leaves it on."""
        press.rule, press.decided = rule, True
        log.info("gesture %s %s: %s", press.key, press.gesture,
                 [f"{st.type}:{st.value}" for st in rule.steps] if rule else "none (given back)")
        i = rule.record_index() if rule else None
        if i is None:
            self._discard_listen(press)
            if rule is not None:
                self._run_steps(press, rule.steps)
        elif self.recognizer is None:
            self._discard_listen(press)
            self._notify(self._status_text or "模型尚未就緒")
            press.finished = True
            return
        elif self._listening and self._listen_owner is not press:
            if press.gesture != HOLD:
                self._stop_listen()
        else:
            if not self._listening:
                self._start_listen(press)
            if self._listening:
                self._show_listen(press)
                self._run_steps(press, rule.steps[:i])
        if press.released:
            self._finish(press)

    def _finish(self, press: _Press):
        """Main thread: the press is released and its operation known."""
        if press.finished:
            return
        if press.rule is None and press.gesture == HOLD and press.up_at - press.down_at < _TAP_MAX:
            # a press a little past gesture_time that no hold operation takes is a tap: the user's taps last
            # 0.11-0.19s against their gesture_time of 0.15s, and turning listening off took three presses
            # (2026-10-14)
            press.decided = False
            self._decide(press, TAP)
            return
        press.finished = True
        if press.rule is None:
            self.hotkeys.replay(press.key, 2 if press.gesture == DOUBLE else 1)
        elif self._listen_owner is press and press.gesture == HOLD:
            self._stop_listen()   # held to listen: released, listening ends

    def _input_done(self):
        """Main thread: a piece ended in nothing, or its text was pasted. Unmute once listening is off."""
        if not self._listening:
            self.muter.restore()

    def _overlay_idle(self):
        """Main thread: a press or piece is done (a terminal edit hid the glow): while listening the glow stays."""
        if self._listening and self._listen_shown:
            self.glow.show(self._pointer_screen())
        else:
            self.glow.hide()

    @staticmethod
    def _pointer_screen():
        return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

    # --- listening (the one way to record since 2026-10-14, continuous-mic branch) ---
    @property
    def _listening(self) -> bool:
        return self.listener is not None and self.listener.active

    def _start_listen(self, press: _Press):
        """The microphone on for the press's operation; unseen until _show_listen (a press may still turn out to be
        another gesture), and pieces wait until then."""
        if self.recognizer is None:
            return
        try:
            if self.listener is None:
                self.listener = Listener(str(models.vad_path()), self._on_listen_speech, self._on_listen_piece)
            self.listener.start(self.cfg.mic)
        except Exception as e:
            log.exception("listen start failed")
            self._notify(f"無法開啟麥克風：{e}")
            return
        self._listen_owner, self._listen_shown = press, False
        self._listen_probe = None
        begin = self.listener.now

        def fresh():   # worker thread, after the last session's pieces and its end (they still need its draft)
            self._spans = []

            def reset():
                self._draft, self._draft_start = None, begin
                self._committed = None
                self.listener.keep(begin)
            self._on_main(reset)
        self.worker.submit(fresh)
        with self._early_lock:
            self._early_pieces = []

    def _show_listen(self, press: _Press):
        """The indicator fades in and the start sound plays together, once the press is known to turn listening on
        (the user's design, 2026-10-13): a hold at gesture_time, a tap at its release or gesture_time later, at
        key-down when the key only has recording taps."""
        if not self._listening or self._listen_owner is not press or self._listen_shown:
            return
        log.info("listen: on (%s %s)", press.key, press.gesture)
        self._listen_shown = True
        self.book.new_session()
        self.tray.setIcon(self.icon_rec)
        self.glow.show(self._pointer_screen())
        cues.play(self.cfg.start_sound, "start")
        wait = cues.duration(self.cfg.start_sound, "start")
        if wait:
            wait += _CUE_LATENCY
            self.listener.still(wait)   # the start sound is not speech; muting waits for its end
        self._heard_at = time.monotonic()
        self._update_float()
        self.bubble.hide()
        self._marks_timer.start()
        if self.cfg.mute_while_recording:
            QTimer.singleShot(int(wait * 1000), lambda: self.muter.mute() if self._listening else None)
        with self._early_lock:
            early, self._early_pieces = self._early_pieces, None
        for piece, probe in early or []:
            self._submit_piece(piece, probe)

    def _check_idle(self):
        """Main thread, every 5s: listening with no speech for auto_off_minutes turns itself off (the user's
        request, 2026-10-15: a microphone left on by mistake), with the end sound and no Enter."""
        minutes = self.cfg.auto_off_minutes
        if minutes and self._listening and self._listen_shown and self._busy == 0 \
                and time.monotonic() - self._heard_at > minutes * 60:
            log.info("listen: off after %d minutes without speech", minutes)
            self._stop_listen()
            self._notify(f"已自動關閉麥克風（{minutes} 分鐘沒有聽到講話）")

    # --- the floating button and leaving text (2026-10-16) ---
    def _update_float(self):
        """Main thread: in on_focus "float" the floating button fades in while listening is off and the focus is
        where text can be typed (the user's request, 2026-10-16: listening is for editing text)."""
        if self.cfg.on_focus == "float" and self._box is not None and not self._listening and not self._quitting:
            self.float_btn.appear()
        else:
            self.float_btn.vanish()

    def _float_clicked(self):
        """Main thread: the floating button turns listening on, as a tap of the key would (the text goes to the
        window that has the focus: the button never takes it)."""
        self._listen_now("button")

    def _listen_now(self, name: str, quiet: bool = False) -> bool:
        """Main thread: listening on without a key (the floating button, the bubble, the focus). quiet: no notice
        when the model is not ready."""
        if self._listening or self._press is not None:
            return False
        if self.recognizer is None:
            if not quiet:
                self._notify(self._status_text or "模型尚未就緒")
            return False
        press = _Press(name, ContextProbe(), time.monotonic(), self.session.deletable() is not None,
                       gesture=TAP, decided=True, released=True, finished=True)
        self._start_listen(press)
        self._show_listen(press)
        return self._listening

    def _float_moved(self, fx: float, fy: float):
        self.cfg.float_pos = [round(fx, 4), round(fy, 4)]
        self.cfg.save()

    def _mark_draft(self):
        """Main thread, every 0.15s while listening: the draft's place read again (it changes as it is retyped, the
        window scrolls) and the boxes drawn there (highlight.py)."""
        d = self._draft
        if d is None or not d.placed or not d.typed or self._moved() \
                or foreground() != self.session.hwnd:
            self.marks.hide()
            return
        # only the open sentence: the settled text before it is not decoded again (the user's expectation,
        # 2026-10-16: the blue marks what may still change)
        text = d.typed[len(d.settled):].lstrip() if d.settled and d.typed.startswith(d.settled) else d.typed
        if not text.strip() or time.monotonic() < self._marks_quiet:
            self.marks.hide()
            return
        if self._marks_busy:
            return
        self._marks_busy = True

        def read():
            rects = draft_rects(text)

            def show():
                self._marks_busy = False
                now = self._draft
                if rects and now is d and now.typed.endswith(text) and not self._moved() and self._listening \
                        and time.monotonic() >= self._marks_quiet:
                    self.marks.show(rects)
                else:
                    self.marks.hide()
            self.main.emit(show)
        self._marks_pool.submit(read)

    def _scrolling(self):
        """Main thread: the wheel turned. The marks hide and come back 0.35s after it stops (following the text as
        it scrolled, they trailed behind by up to 0.15s; the user's choice, 2026-10-16)."""
        self._marks_quiet = time.monotonic() + 0.35
        self.marks.hide()

    def _watch_focus(self):
        """Main thread, every 0.3s when on_focus is set: where the focus is, read on a thread (UI Automation)."""
        if not self.cfg.on_focus or self._focus_busy or self._quitting:
            return
        self._focus_busy = True

        def read():
            info = focus_info()
            self.main.emit(lambda: self._focus_seen(*info))
        self._focus_pool.submit(read)

    def _focus_seen(self, editable, key, rect):
        """Main thread (the user's requests, 2026-10-16). The focus came into a text box (a new one: another control
        or window): "bubble" shows the bubble next to it; "listen" turns listening on, unless it was turned off by
        hand in this box. The focus went where nothing can be typed (a web page's blank part, a button, the
        desktop): the bubble goes, and listening is turned off (when it was in a text box before: listening may be
        turned on by hand anywhere). Unknown places and VoiceInput's own windows change nothing."""
        self._focus_busy = False
        mode = self.cfg.on_focus
        if not mode or editable is None:
            return
        if editable:
            new = key != self._box
            if new:
                self._box, self._box_quiet = key, False
            if mode == "listen" and not self._listening and not self._box_quiet:
                log.info("listen: on, the focus is in a text box")
                if self._listen_now("focus", quiet=True):
                    self._box_auto = True
            elif mode == "bubble" and not self._listening and rect and (new or self.bubble.isVisible()):
                self.bubble.show_by(rect)   # a new box, or following the caret
            elif mode == "float":
                self._update_float()
            return
        was, self._box = self._box, None
        self.bubble.hide()
        self._update_float()
        if mode == "listen" and was is not None and self._listening:
            log.info("listen: off, the focus left the text box")
            self._stop_listen(by_focus=True)

    def _preview_glow(self, style_id: str):
        """A glow style picked in the settings: shown for a moment (unless listening shows it already)."""
        self.glow.set_style(style_id)
        if not self._listening:
            self.glow.show(QGuiApplication.screenAt(self.settings.geometry().center()))
            QTimer.singleShot(2500, lambda: None if self._listening else self.glow.hide())

    def _discard_listen(self, press: _Press):
        """The press that started listening unseen does something else: the microphone off, nothing kept."""
        if self._listening and self._listen_owner is press and not self._listen_shown:
            self.listener.stop(discard=True)
            self._listen_owner = None

    def _stop_listen(self, by_focus: bool = False):
        """Listening off. by_focus: the focus left the text box (on_focus); any other way of turning it off keeps
        the focus from turning it on again in the same box."""
        if not by_focus and self._box is not None:
            self._box_quiet = True
        self._box_auto = False
        owner, self._listen_owner, self._listen_shown = self._listen_owner, None, False
        self.listener.stop()   # speech still going on is handed over as a last piece
        self.book.end_session()
        log.info("listen: off")
        self.tray.setIcon(self.icon_idle)
        self.glow.hide()
        self._marks_timer.stop()
        self.marks.hide()
        self._update_float()
        done = self.cfg.stop_sound and self.cfg.stop_sound_at == "done"
        if not done:
            self.muter.restore()
            if self.cfg.stop_sound:
                cues.play(self.cfg.stop_sound, "stop")
        after = self._after_steps(owner) if owner else []
        end = self.listener.now

        def finished():   # worker thread, after the last piece: the rest of the draft is committed, then the steps
            self._on_main(lambda: None)
            d = self._draft
            spans, self._spans = self._spans, []
            if d is not None:
                spans = [p for p in spans if p.start >= d.anchor]
                # a draft 復原 brought back with nothing said since: the silence after it is not decoded ("So")
                self._commit_job(self._draft_start, d.anchor, d.anchor if d.revived else end, end, d.ctx,
                                 final=True, spans=spans)

            def run():
                if done and not self._listening:
                    self.muter.restore()
                    cues.play(self.cfg.stop_sound, "stop")
                if owner:
                    self._run_steps(owner, list(after))
            self.main.emit(run)
        self._decoding(finished)

    def _on_listen_speech(self):
        """Listener thread: speech began. What is selected now is what a new draft replaces."""
        self._heard_at = time.monotonic()
        self._listen_probe = ContextProbe()
        self._speech_sample = max(0, self.listener.now - int(LEAD * SAMPLE_RATE))

    def _on_listen_piece(self, piece):
        """Listener thread: a piece of speech ended: a command, or more of the draft."""
        probe = self._listen_probe
        with self._early_lock:
            if self._early_pieces is not None:
                self._early_pieces.append((piece, probe))   # the press is not known to listen yet
                return
        self._submit_piece(piece, probe)

    def _submit_piece(self, piece, probe):
        if self.recognizer is not None:
            self._decoding(self._piece_job, piece, probe)

    def _decoding(self, fn, *args):
        """fn on the worker thread, counted as decoding while queued or running (the indicator's spinner)."""
        with self._busy_lock:
            self._busy += 1

        def run():
            try:
                fn(*args)
            finally:
                with self._busy_lock:
                    self._busy -= 1
        self.worker.submit(run)

    # --- the draft: text typed while listening, not committed yet ---
    def _new_draft(self, ctx):
        """Main thread: a draft starts where the caret is, over the selection read when its speech began."""
        self._draft = _Draft(self._draft_start, ctx, ctx.selection, anchor=self._draft_start,
                             shown=self._draft_start)
        return self._draft

    def _show_draft(self, step: bool = False):
        """Main thread: make the document show the draft's text. step: a pause's update, which 復原 takes back on
        its own."""
        d = self._draft
        text = d.final
        if not d.placed:
            if not text:
                return
            if d.sel is not None:
                if d.sel.term is not None:
                    self.glow.hide_now()
                self._close_menu()   # the selection the menu was for is replaced
                pasted = _paste_over(d.sel, text)
                self._overlay_idle()
                if not pasted:
                    self._notify(_SEL_LOST)
                    d.sel = None
                    return
                self.session.replaced_selection(d.sel.before, text, foreground(), d.sel.before + d.sel.text)
            else:
                d.lead = " " if self.session.clean() and _space_between(self.session.buffer[-1:], text) else ""
                paste_text(d.lead + text)
                self.session.dictated(d.lead + text, None, foreground())
            d.placed, d.typed = True, text
            return
        if text == d.typed:
            return
        s = self.session
        if self._moved():
            self._freeze()   # what is typed stays
            return
        new = s.buffer[:len(s.buffer) - len(d.typed)] + text
        n, tail = s.plan_to(new)
        backspace(n)
        if tail:
            paste_text(tail)
        s.retyped(new, step)
        d.typed = text

    def _moved(self) -> bool:
        """Main thread: the user moved the caret away from the draft (clicked, selected, typed)."""
        d, s = self._draft, self.session
        return d is not None and d.placed and not (s.clean() and s.buffer.endswith(d.typed))

    def _caret_left(self):
        """Main thread: the user clicked or typed. A draft the caret left stays as typed now, so the log shows it
        when it happens (the user's request, 2026-10-15: it showed at the next speech); speech after what is typed
        is decoded again at the caret now, as when an update finds the caret moved."""
        if not self._listening or not self._moved():
            return
        at = self._draft.shown
        self._freeze(at)
        self._decoding(self._redo_job, at)

    def _freeze(self, at: int | None = None):
        """Main thread: the caret moved away from the draft. It stays as typed; speech from `at` (default: the
        speech under way) starts a new draft."""
        d = self._draft
        self.marks.hide()
        log.info("draft left as typed: %s", d.typed if d else "")
        if d is not None and d.placed and d.typed:   # never committed: logged as it stands
            self.book.frozen(d.typed)
        self._draft = None
        if at is None:
            at = self._speech_sample if self._speech_sample > self._draft_start else self.listener.now
        self._draft_start = at
        self.listener.keep(at)

    def _refine(self, start: int, anchor: int, settled: str, live: str, after: int, upto: int, ctx,
                info: dict | None = None):
        """Main thread: a pause. The draft's open sentence (its audio from `anchor` to `upto`) was decoded again:
        `settled` is the part up to a ， or 。 that fell in a pause, fixed from now on (the open sentence starts at
        `after`), `live` the rest. Typed in place of what was there."""
        d = self._draft
        if start != self._draft_start or (d is not None and d.anchor != anchor):
            return
        if d is None and not settled and not live:   # a noise: no draft, so the next speech reads its own selection
            return
        if self._moved():
            # the caret moved before this update was typed: what is typed stays, and the speech after it is decoded
            # again where the caret is now (it was lost until 2026-10-15)
            at = d.shown
            self._freeze(at)
            self._decoding(self._redo_job, at)
            return
        if d is None:
            d = self._new_draft(ctx)
        elif not d.placed:   # nothing typed yet: the latest speech's caret and selection
            d.ctx, d.sel = ctx, ctx.selection
        before = d.typed if d.placed else ""
        _go_on(d)
        d.settled = _joined(d.settled, settled)
        d.anchor = after
        d.final = _TRAILING.sub("", _joined(d.settled, live))
        # the recognizer's 。？！ at the end is shown; the next pause turns it into ， when the sentence goes on (the
        # user's request, 2026-10-15; until then drafts had none while speaking)
        end = _SENTENCE_END.search(_joined(d.settled, live))
        if end and d.final and not _inside(d.ctx):
            d.final += end.group()
        self.listener.keep(after)
        self._show_draft(step=True)
        if d.placed and d.typed == d.final:
            d.shown = upto
            self.book.heard(info, before, d.typed, settled)

    def _commit(self, text: str, start: int, anchor: int, at: int, ctx, command=None, final: bool = False):
        """Main thread: the draft's open sentence decoded again joins its settled text and the draft is done; then
        the command it ended with runs. Listening goes on from `at`. final (an operation or the end of listening):
        the recognizer's 。？！ at the end is kept, or 。 added when it gave none (the user's choice, 2026-10-14/15:
        not while speaking, where a pause is not a sentence end, nor before a spoken punctuation mark), unless the
        caret had text on both sides."""
        d = self._draft
        marked = added = logged = False
        before = ""
        if start == self._draft_start and (d is None or d.anchor == anchor):
            if d is None and text:
                d = self._new_draft(ctx)
            elif d is not None and not d.placed:
                d.ctx, d.sel = ctx, ctx.selection
            if d is not None:
                before = d.typed if d.placed else ""
                if text:
                    _go_on(d)
                d.final = _TRAILING.sub("", _joined(d.settled, text))
                end = _SENTENCE_END.search(_joined(d.settled, text))
                # no mark added before an operation that takes back what precedes the caret (_no_mark_first)
                if final and d.final and not _inside(d.ctx) and not (end is None and _no_mark_first(command)):
                    # none from the recognizer (a short sentence often has none): 。 (the user's choice, 2026-10-15),
                    # ？ after 嗎 (the user's request the same day)
                    d.final += end.group() if end else "？" if d.final.endswith("嗎") \
                        else "。" if _CJK_CHAR.search(d.final) else "."
                    marked, added = True, end is None   # added: the recognizer gave none
                self._show_draft()
                logged = bool(d.final) and d.typed == d.final   # else left as typed (logged by _freeze)
                if logged and command is None:
                    self.book.committed(before, d.typed, added, by_stop=final)
            self._draft = None
            self.marks.hide()
            self._draft_start = at
            self.listener.keep(at)
            if d is not None:
                self._marked = self.session.buffer if marked else None
                b = self.session.buffer
                self._committed = (b[:len(b) - len(d.typed)], d, self.session.history[-1]) \
                    if d.placed and d.typed and self.session.clean() and b.endswith(d.typed) \
                    and self.session.history else None
        if command is not None:
            # the selection made before the command was said, unless the text before it went there
            sel = ctx.selection
            if d is not None and d.placed and d.sel is sel:
                sel = None
            drafted = d is not None and logged   # the command ends a sentence's card
            op, typed, entry = command
            self.book.command(entry, op, typed, before if drafted else "", d.typed if drafted else "", added,
                              drafted, sel.text if sel is not None and typed else None)
            self._run_command(command, ctx, sel)
        self._overlay_idle()
        self._input_done()

    def _run_command(self, command, ctx, sel=None):
        """Main thread: an operation spoken alone runs its steps; a punctuation name or a described character is
        typed after the text, or over `sel` (the selection made before it was said: a selected 。 said 冒號 over
        stayed and ： was typed at the caret, 2026-10-15)."""
        op, typed, entry = command
        if op is not None:
            log.info("spoken operation: %s", op.phrase)
            # 刪除, 剪下, 復原 … may take away the text the 選字 menu is for (the user's request, 2026-10-16: it
            # stayed after 刪除)
            self._close_menu()
            seen = Context(sel, ctx.terms, ctx.caret)
            self._run_steps(_Press("listen", _Known(seen), time.monotonic(), False), op.steps)
        else:
            log.info("typed: %s", typed)
            s = self.session
            if sel is not None:
                self._close_menu()
                if sel.term is not None:
                    self.glow.hide_now()
                pasted = _paste_over(sel, typed)
                self._overlay_idle()
                if pasted:
                    s.replaced_selection(sel.before, typed, foreground(), sel.before + sel.text)
                else:
                    self._notify(_SEL_LOST)
            elif typed in edit.SYMBOLS.values() and self._marked is not None and s.clean() \
                    and s.buffer == self._marked:
                # the mark a commit added (after 換行 or the like) gives way to the one said now: not 。。
                s.changed(s.buffer[:-1] + typed)
                backspace(1)
                paste_text(typed)
            else:
                self._type_text(typed)
            self._marked = None

    # --- recognition (worker thread) ---
    def _decode(self, audio, ctx, commands: bool = False) -> str:
        """The recognizer's text for audio, biased by hotwords and on-screen terms. commands: a short result is
        decoded again with spoken commands boosted (they are said alone; boosting them in every sentence would
        turn 還行 into 換行)."""
        words = self._bias_words(ctx)
        raw = self.recognizer.recognize(audio, words)
        names = self._command_words() if commands else []
        said = rules.normalize(to_traditional(raw))
        if any(said == rules.normalize(n) for n in names):
            return raw   # already a command: boosted again, 結束 after a sentence came out as 結束結束結束 (2026-10-16)
        if names and self._short(raw, names):
            # commands only: the hotwords, packs and on-screen terms competed with them (the user's 換行 came out as
            # "One home." with them, 換行 without; on their short recordings 363/374 commands vs 362, no new false
            # hits among 211 short texts, 2026-10-15)
            again = self.recognizer.recognize(audio, _bias([(w, _COMMAND_SCORE) for w in names]))
            again = _one_command(again, names)
            if again != raw:
                log.info("asr with commands boosted: %s -> %s", raw, again)
            raw = again
        return raw

    def _bias_words(self, ctx) -> list:
        """Hotwords and on-screen terms, as the recognizer takes them."""
        self._load_packs()
        return _bias(self.hotwords.bias() + [(t, _SCREEN_TERM_SCORE) for t in ctx.terms])

    @staticmethod
    def _short(raw: str, names: list) -> bool:
        """Short enough to be a command said alone, counting a Chinese character or an English word as one: by
        letters, the user's 換行 heard as "Hangan" (6) was too long to be decoded again with commands boosted, and
        typed as text (2026-10-14)."""
        return len(_WORDS.findall(raw)) <= max(map(len, names)) + _COMMAND_SLACK

    def _command(self, formatted: str, ctx, steps: list, raw: str = ""):
        """(operation, text to type) when the utterance is a command said alone: an operation's phrase, a
        punctuation name, a described character, or letters spelled over a selected English word (raw: the
        recognizer's text, which writes them as "B L I P."); (None, None) otherwise."""
        op = rules.pick(rules.candidates(self.cfg.rules, rules.SPEECH, formatted), ctx.selection is not None,
                        self.session.deletable() is not None)
        typed = None
        if op is None and ctx.selection is not None and raw:
            spelt = edit.spelled(ctx.selection.text, raw)
            if spelt:   # that word, spelled, in the selection's case (lost on this branch until 2026-10-16)
                steps.append(("拼字", formatted, spelt[0]))
                self.main.emit(lambda: self._learn_spelled(spelt[1], spelt[2]))
                return None, spelt[0]
        if op is None and self.cfg.punctuation_names:
            typed = edit.symbol(formatted)
            if typed:
                steps.append(("標點名稱", formatted, typed))
        if op is None and not typed and self.cfg.describe_char:
            typed = edit.described(formatted)
            if typed:
                steps.append(("指定字", formatted, typed))
        return op, typed

    def _text_of(self, raw: str, ctx, steps: list, keep_end: bool = False) -> str:
        """Dictated text from the recognizer's: formatted without sentence-final punctuation (the user says 句號;
        keep_end: a sentence settled inside the draft keeps its ， or 。), English spelled as known terms, smart
        picks."""
        formatted = format_text(raw, not keep_end, steps)
        known = spelling.table(self._known_terms(ctx.terms), self.hotwords.aliases())
        before = formatted
        formatted, spelled = spelling.fix(formatted, known)
        if spelled:
            log.info("spelling: %s", ", ".join(f"{a} -> {b}" for a, b in spelled))
            steps.append(("英文拼寫", before, formatted))
        prefix = ctx.selection.before if ctx.selection else (ctx.caret[0] if ctx.caret else "")
        text = self.memory.apply(formatted, prefix, self.hotwords.levels())
        if text != formatted:
            steps.append(("選字記憶", formatted, text))
        return text

    def _piece_job(self, piece, probe):
        """A piece of speech ended. Said alone, a command commits the draft before it and runs; otherwise the
        draft's open sentence is decoded again up to here (committed when the setting says every pause)."""
        try:
            # what earlier pieces asked of the main thread is done; a draft the user moved away from stays as it
            # is, and this piece starts a new one (over the selection made meanwhile)
            state = {}

            def check():
                if self._moved():
                    self._freeze(piece.lo)
                d = self._draft
                state.update(drafted=d is not None and not d.revived, alone=d is None or not d.final or d.revived, start=self._draft_start,
                             anchor=d.anchor if d is not None else self._draft_start)
            self._on_main(check)
            if "anchor" not in state:   # the main thread did not answer in time
                log.warning("piece dropped: the main thread is busy")
                return
            ctx = probe.result() if probe is not None else Context()
            start, anchor = state["start"], state["anchor"]
            self._spans = [p for p in self._spans if p.start >= anchor] + [piece]
            audio = self.listener.audio(piece.lo, piece.hi)
            t0 = time.monotonic()
            raw = self._decode(audio, ctx, commands=True)
            t_asr = time.monotonic() - t0
            log.info("piece %.2fs: %s", t_asr, raw)
            steps = []
            formatted = format_text(raw, True, steps)
            entry = {"time": time.strftime("%H:%M:%S"), "asr": to_traditional(raw), "asr_s": t_asr, "steps": steps}
            op, typed = self._command(formatted, ctx, steps, raw)
            names = self._command_words()
            if op is None and not typed and state["alone"] and names and self._short(raw, names) \
                    and piece.lo > anchor:
                # decoded with the draft's audio before it (as a commit would), a short piece may turn out to be a
                # command it missed alone: the user's 換行 came out as Hangan, then as 換行 in the draft, and was
                # typed as text at the next command (2026-10-14)
                whole, _ = self._speech(anchor, piece.hi, self._spans)
                again = self._decode(whole, ctx, commands=True)
                more = format_text(again, True)
                op, typed = self._command(more, ctx, steps, again)
                if op is not None or typed:
                    log.info("piece with the draft before it: %s -> %s", raw, again)
                    raw, formatted, audio = again, more, whole
            if op is not None or typed:
                spans, self._spans = [p for p in self._spans if p is not piece], []
                self._keep(audio, asr=raw, fmt=formatted, result=typed or "",
                           op=op.phrase if op else None)
                entry.update(kind="操作", main=op.phrase) if op else entry.update(kind="輸入", main=typed, copy=typed)
                # nothing said since the last commit: the audio before the command is not decoded (a breath
                # between 句號 and 送出 was typed as "Shh", 2026-10-14)
                end = piece.start if state["drafted"] else anchor
                self._commit_job(start, anchor, end, piece.hi, ctx, (op, typed, entry), final=not typed,
                                 spans=spans)
            elif self.cfg.commit_at == "pause" or piece.hi - anchor > _DRAFT_MAX * SAMPLE_RATE:
                spans, self._spans = self._spans, []
                self._commit_job(start, anchor, piece.hi, piece.hi, ctx, spans=spans)
            else:
                self._refine_job(start, anchor, piece, ctx, short=bool(names) and self._short(raw, names),
                                 info={"heard": formatted, "entry": entry})
        except Exception:
            log.exception("piece failed")

    def _refine_job(self, start: int, anchor: int, piece, ctx, short: bool = False, info: dict | None = None):
        """The draft's open sentence (audio from `anchor`) decoded again up to this pause. Text up to the last ，
        or 。 the recognizer put in an earlier pause is settled: it is not decoded again, so a pause costs one
        sentence, not the whole draft (the user's request, 2026-10-14: a commit of a long draft took 3.25s).
        short: the piece is short enough to be a command."""
        t0 = time.monotonic()
        audio, index = self._speech(anchor, piece.hi, self._spans)
        words = self._bias_words(ctx)
        names = self._command_words() if short else []
        # a short piece is decoded with the speech before it and commands boosted first: plain, the user's 換行 at
        # the end was often left out, then turned up inside the sentence at the next pause (2026-10-15)
        for bias in ([_bias([(w, _COMMAND_SCORE) for w in names] + words)] if names else []) + [words]:
            text, tokens, times = self.recognizer.recognize_timed(audio, bias)
            if self._ran_tail(text, tokens, times, index, piece, ctx, start, anchor, t0, info):
                return
        settled, live, after = "", text, anchor
        # a blank token (between English letters) is no mark: "" in _MARKS is True, and counting it settled a whole
        # sentence that was then typed again (2026-10-15)
        marks = [i for i, tok in enumerate(tokens[:-1]) if tok.strip() and tok.strip() in _MARKS]
        for k in range(len(marks) - 1, -1, -1):
            at = _sample_at(index, int(times[marks[k]] * SAMPLE_RATE))
            gap = next((nxt for prev, nxt in zip(self._spans, self._spans[1:])
                        if prev.end - _MARK_SLACK <= at <= nxt.start + _MARK_SLACK), None)
            spots = [i for i, ch in enumerate(text) if ch in _MARKS]
            if gap is not None and k < len(spots):
                cut = spots[k] + 1
                settled, live, after = text[:cut], text[cut:], gap.lo
                self._spans = [p for p in self._spans if p.start >= after]
                break
        settled = self._text_of(settled, ctx, [], keep_end=True) if settled else ""
        live = self._text_of(live, ctx, [], keep_end=True)
        log.info("draft %.2fs: %s | %s", time.monotonic() - t0, settled, live)
        info = dict(info or {}, redo_s=time.monotonic() - t0)
        self.main.emit(lambda: self._refine(start, anchor, settled, live, after, piece.hi, ctx, info))

    def _ran_tail(self, text, tokens, times, index, piece, ctx, start, anchor, t0, info=None) -> bool:
        """The last piece, decoded after the speech before it, may be a command it was not alone: the user's 換行
        came out as "Hang Hung," alone and 送出 as "Contral.", as themselves after it, and were typed as text
        (2026-10-15). Then the speech before it is committed and the command runs (True)."""
        head, tail = _split_at(text, tokens, times, index, piece.start - _MARK_SLACK)
        if not tail:
            return False
        steps = []
        said = format_text(tail, True, steps)
        op, typed = self._command(said, ctx, steps)
        if op is not None or typed:
            log.info("piece with the speech before it: %s | %s", head, said)
            entry = {"time": time.strftime("%H:%M:%S"), "asr": to_traditional(tail),
                     "asr_s": time.monotonic() - t0, "steps": steps, "alone": (info or {}).get("heard")}
            entry.update(kind="操作", main=op.phrase) if op else entry.update(kind="輸入", main=typed, copy=typed)
            self._spans = []
            head = self._text_of(head, ctx, []) if head.strip() else ""
            command = (op, typed, entry)
            self.main.emit(lambda: self._commit(head, start, anchor, piece.hi, ctx, command, not typed))
            return True
        return False

    def _redo_job(self, at: int):
        """A pause's update came after the caret moved: the speech since sample `at` (after what is typed) is
        decoded again as a new draft at the caret and selection now."""
        state = {}
        self._on_main(lambda: state.update(go=self._draft is None and self._draft_start == at))
        spans = [p for p in self._spans if p.hi > at]
        if not state.get("go") or not spans:   # a later piece got there first
            return
        self._spans = spans
        self._refine_job(at, at, spans[-1], ContextProbe().result(), info={"redo": True})

    def _speech(self, anchor: int, end: int, spans: list):
        """The open sentence's audio [anchor, end) with the silence between its pieces (spans) cut down to their own
        lead-in and tail, and an index of (offset in it, sample) for each stretch kept. The user thinks between
        sentences: with 15s pauses kept a draft passed the 30s beyond which the recognizer gives no timestamps,
        so nothing was settled and each pause decoded it all again, 2-3s (2026-10-15)."""
        stretches = []
        for p in spans:
            lo, hi = max(p.lo, anchor), min(p.hi, end)
            if hi <= lo:
                continue
            if stretches and lo <= stretches[-1][1]:
                stretches[-1][1] = max(stretches[-1][1], hi)
            else:
                stretches.append([lo, hi])
        if not stretches:
            return self.listener.audio(anchor, end), [(0, anchor)]
        # with only the pieces' own 0.75s between them the recognizer's marks there were a coin toss: the user's
        # 難道這樣沒有問題嗎 [3.7s] 還是說… came out without its ？ in 7 of 10 tries, 0 of 10 with 0.5s more kept
        # (2026-10-15)
        for a, b in zip(stretches, stretches[1:]):
            a[1] = min(a[1] + _GAP_KEEP, b[0])
        merged = [stretches[0]]
        for lo, hi in stretches[1:]:
            if lo <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        stretches = merged
        parts, index, n = [], [], 0
        for lo, hi in stretches:
            a = self.listener.audio(lo, hi)
            parts.append(a)
            index.append((n, lo))
            n += a.size
        return np.concatenate(parts), index

    def _commit_job(self, start: int, anchor: int, end: int, at: int, ctx, command=None, final: bool = False,
                    spans: list = ()):
        """The draft's open sentence, audio [anchor, end), decoded again; the main thread puts the draft's text in
        its place (final: with its sentence-final mark)."""
        audio, _ = self._speech(anchor, end, spans)
        steps, text, raw = [], "", ""
        t0 = time.monotonic()
        if audio.size >= SAMPLE_RATE * 0.2:
            raw = self._decode(audio, ctx)
            text = self._text_of(raw, ctx, steps, keep_end=final)
        if text:
            log.info("commit %.2fs: %s", time.monotonic() - t0, text)
            self._keep(audio, asr=raw, fmt=text, result=text, op=None)
        self.main.emit(lambda: self._commit(text, start, anchor, at, ctx, command, final))

    # --- steps ---
    def _run_steps(self, press: _Press, steps: list, done=None):
        """Run steps in order on the steps thread (錄音 is not a step to run: the press records)."""
        steps = [s for s in steps if not (s.type == rules.COMMAND and s.value == rules.RECORD)]
        if not steps:
            if done:
                done()
            return
        self.steps.submit(self._steps_job, press, steps, done)

    def _steps_job(self, press: _Press, steps: list, done):
        try:
            for n, step in enumerate(steps):
                if n:
                    time.sleep(_STEP_GAP)
                # a spoken operation with text selected in a terminal acts on the selection, not at the cursor
                # (the user's request, 2026-10-16: in Claude Code a mouse selection leaves the cursor where it was,
                # and 刪除 deleted there)
                sel = press.probe.result().selection if press.key == "listen" and press.deleted is None else None
                if sel is not None and sel.term is not None and (
                        step.type == rules.KEYS and step.value in ("Backspace", "Delete") or step.type == rules.TEXT):
                    if step.type == rules.TEXT:
                        self._on_main(lambda t=step.value: self._replace_selection(press, sel, t))
                    else:
                        self._on_main(lambda: self._delete_selection(press, press.probe.result()))
                    continue
                if step.type == rules.WRAP:
                    self._on_main(lambda v=step.value: self._wrap(press, v, sel if press.key == "listen" else None))
                    continue
                if step.type == rules.COMMAND and step.value in rules.EDIT_COMMANDS:
                    self._on_main(lambda c=step.value: self._edit_command(press, c, sel))
                    continue
                if step.type == rules.WAIT:
                    time.sleep(max(0, int(step.value or 0)) / 1000)
                elif step.type == rules.KEYS:
                    vks = combo_vks(step.value)
                    if vks:
                        press_chord(*vks)
                        if step.value == "Shift+Enter":   # a new line, which 復原 can take back
                            self._on_main(lambda: self.session.dictated("\n", None, foreground()))
                        elif step.value == "Backspace":   # one character less, which 復原 can type again
                            self._on_main(self._backspaced)
                        else:
                            self.session.on_input()     # the caret may have moved
                elif step.type == rules.TEXT:
                    self._on_main(lambda t=step.value: self._type_text(t))
                elif step.type == rules.COMMAND and step.value == rules.UNDO:
                    self._on_main(self.undo)
                elif step.type == rules.COMMAND and step.value == rules.STOP:
                    self._on_main(lambda: self._stop_listen() if self._listening else None)
        except Exception:
            log.exception("steps failed")
        finally:
            if done:
                done()

    def _on_main(self, fn):
        """Steps thread: run fn on the main thread and wait for it."""
        ev = threading.Event()

        def run():
            try:
                fn()
            finally:
                ev.set()
        self.main.emit(run)
        for _ in range(100):   # 10s; not when quitting: the main loop is gone and Python waits for this thread
            if ev.wait(0.1) or self._quitting:
                return

    def _backspaced(self):
        """Main thread: a Backspace step deleted the character before the caret."""
        s = self.session
        if s.clean():
            s.changed(s.buffer[:-1])
        else:
            s.on_input()

    def _wrap(self, press: _Press, value, sel):
        """Main thread: 左右輸入文字 (2026-10-16, the user's request): left and right typed around the selection, or
        around the caret, which stays between them; 復原 takes it back as one change."""
        left, right = (list(value) + ["", ""])[:2] if isinstance(value, (list, tuple)) else (str(value or ""), "")
        if not left and not right:
            return
        if sel is not None:
            self._replace_selection(press, sel, left + sel.text + right)
            return
        paste_text(left + right)
        if right:
            press_key(0x25, len(right))   # Left: back between them
        self.session.wrapped(left, right, foreground())

    def _replace_selection(self, press: _Press, sel, text: str):
        """Main thread: text typed over a terminal selection."""
        if sel.term is not None:
            self.glow.hide_now()
        pasted = _paste_over(sel, text)
        self._overlay_idle()
        if not pasted:
            self._notify(_SEL_LOST)
            return
        press.deleted = sel
        self.session.replaced_selection(sel.before, text, foreground(), sel.before + sel.text)

    def _edit_command(self, press: _Press, command: str, sel):
        """Main thread: 全選 / 複製 / 剪下 / 貼上 (2026-10-16). In an ordinary app their keys (Ctrl+A / C / X / V). In a
        terminal, where Ctrl+C clears Claude Code's input and a mouse selection is not the cursor's: 複製 puts the
        selection we read on the clipboard, 剪下 also deletes it, 貼上 replaces it with the clipboard's text (or
        presses Ctrl+V with nothing selected), and 全選 cannot be done. The clipboard a paste borrowed is put back
        first."""
        term = sel.term is not None if sel is not None else terminal_in_front()
        restore_now()
        if not term:
            press_chord(0x11, {rules.SELECT_ALL: 0x41, rules.COPY: 0x43, rules.CUT: 0x58, rules.PASTE: 0x56}[command])
            if command != rules.COPY:
                self.session.on_input()   # the text or the caret changed in ways we do not follow
            return
        if command == rules.SELECT_ALL:
            self._notify("終端機裡無法全選")
            return
        if command == rules.PASTE and sel is None:
            press_chord(0x11, 0x56)
            self.session.on_input()
            return
        if sel is None:
            self._notify("沒有選取的文字")
            return
        if command in (rules.COPY, rules.CUT):
            copy_text(sel.text)
            log.info("copied %r", sel.text)
        if command == rules.CUT:
            self._delete_selection(press, press.probe.result())
        elif command == rules.PASTE:
            text = QGuiApplication.clipboard().text()
            if text:
                self._replace_selection(press, sel, text)

    def _type_text(self, text: str):
        if text:
            paste_text(text)
            self.session.dictated(text, None, foreground())

    def _delete_selection(self, press: _Press, ctx):
        """刪除選取的文字: the text selected when the (first) press went down."""
        sel = ctx.selection if press.deleted is None else None
        if sel is None:
            log.info("delete selection: nothing selected")
            return
        log.info("delete %r on %s", sel.text, sel.app)
        if sel.term is not None:
            self.glow.hide_now()
        deleted = _delete_selection(sel)
        if sel.term is not None:
            self._overlay_idle()
        if not deleted:
            self._notify(_SEL_LOST)
            return
        press.deleted = sel
        self.session.replaced_selection(sel.before, "", foreground(), sel.before + sel.text)
        self.record.emit({"time": time.strftime("%H:%M:%S"), "kind": "刪除", "main": sel.text})

    def undo(self):
        """Main thread, 復原 (and 刪除剛輸入的文字): take back VoiceInput's last change while it is still right before
        the caret: all of them while the caret has not moved, one each time; a draft's are its pauses' updates. After one,
        what is left of the draft (or of the draft the last commit typed) is a draft again, its text fixed (decoded
        again, the audio taken back would come back): speech goes on after it, and a command or the end of
        listening gives it its sentence end (the user's choice, 2026-10-15: 細節 was left without its 。 after
        換行 misheard and taken back)."""
        s = self.session
        step = s.deletable()
        if step is None:
            log.info("undo: nothing to take back")
            # a tray notice, so 復原 doing nothing is not a mystery (the user's request, 2026-10-15)
            moved = s.dirty or s.hwnd != foreground()
            self._notify("無法復原：游標移動、點擊或打字之後就不能再復原了" if moved and s.history else
                         "沒有可以復原的了")
            return
        d = self._draft
        if d is not None and d.placed and step.after.endswith(d.typed):
            source = (step.after[:len(step.after) - len(d.typed)], d)
        elif self._committed is not None and (step is self._committed[2] or len(s.history) > 1
                                              and s.history[-2] is self._committed[2]):
            # the commit's own change, or the one right after it (its 換行): not a later, unrelated one (a selection
            # replaced elsewhere brought an old sentence back as a draft; comparing texts matched by chance)
            source = self._committed[:2]
        else:
            source = None
        n, tail = s.plan_to(step.before)
        log.info("undo: %d backspaces + %r", n, tail)
        if self.cfg.save_recordings:
            recordings.note("delete_last")
        backspace(n)
        if tail:
            paste_text(tail)
        if step.tail:   # the right half of 左右輸入文字, after the caret
            press_key(0x2E, step.tail)
        s.deleted_last(step)
        self._committed = None
        rest = ""
        if source is not None and source[1] is d:   # the draft's change was taken back
            self._draft = None
            self._draft_start = self.listener.now if self._listening else 0
            if self._listening:
                self.listener.keep(self._draft_start)
        if source is not None and self._listening and self._draft is None:
            before, old = source
            rest = step.before[len(before):] if step.before.startswith(before) else ""
            if rest:
                now = self.listener.now
                self._draft = _Draft(now, old.ctx, anchor=now, settled=rest, final=rest, typed=rest, placed=True,
                                     shown=now, revived=True)
                self._draft_start = now
                self.listener.keep(now)
                self._marked = None
                log.info("undo: a draft again: %s", rest)
        p = len(os.path.commonprefix([step.before, step.after]))
        self.book.undo(step.after[p:], step.before[p:], rest if self._draft is not None else "")

    @staticmethod
    def _after_steps(press: _Press) -> list:
        """The steps after 錄音 in the press's operation: run once its text is pasted."""
        rule = press.rule
        i = rule.record_index() if rule else None
        return rule.steps[i + 1:] if i is not None else []

    def _learn_spelled(self, old: str, new: str):
        """A word spelled over a selection counts like a 選字 pick: priority, and old as a misheard spelling."""
        log.info("spelled: %s -> %s", old, new)
        if self.cfg.save_recordings:
            recordings.note("spelled", before=old, after=new)
        self.hotwords.picked(old, new)
        self.settings.refresh_hotwords()
        self._suggest_pack(new)

    def _load_packs(self):
        """The ticked packs' words, read again when a pack file was edited (checked before each decode)."""
        stamp = packs.stamp()
        if stamp != self._pack_stamp:
            self._pack_stamp = stamp
            self.hotwords.set_packs(packs.words_for(self.cfg.packs), packs.PCT)

    def _suggest_pack(self, word: str):
        """A word picked, typed or spelled that an unticked term pack lists: a notice suggests the pack, once per
        pack (the user's request, 2026-10-13; remembered in config.pack_hints)."""
        word = word.strip()
        for pack in packs.available():
            if pack.id in self.cfg.packs or pack.id in self.cfg.pack_hints:
                continue
            if any(w == word or (is_latin(word) and w.casefold() == word.casefold()) for w in pack.words):
                log.info("pack hint: %s in %s", word, pack.id)
                self.cfg.pack_hints.append(pack.id)
                self.cfg.save()
                self.tray.showMessage("VoiceInput", f"「{word}」收錄在詞包「{pack.name}」。到設定的詞庫頁勾選它，"
                                      "同類的詞會更容易辨識。", self.icon_idle, 8000)
                return

    def _keep(self, audio, **info):
        """Development only (the user will remove it before release): save the utterance (recordings.py)."""
        if self.cfg.save_recordings and audio is not None and audio.size:
            recordings.save(audio, SAMPLE_RATE, **info)

    def _command_words(self) -> list[str]:
        """What may be said alone as a command: speech operations' phrases, and punctuation names when they are on.
        Not a word of one repeated character: boosted, 點點點 came out as 點點點點點點點點點."""
        words = [r.phrase.strip() for r in self.cfg.rules
                 if r.enabled and r.source == rules.SPEECH and not rules.problems(r, self.cfg.rules)]
        if self.cfg.punctuation_names:
            words += list(edit.SYMBOLS)
        return [w for w in words if w and len(set(w)) > 1]

    # --- dictation ---
    # Second opinion, off for now: SenseVoice re-decodes each dictation and suspects.find() lists words it heard
    # as a likelier word. The menu that offered them was removed with the other popups. To turn it back on, also
    # restore `from . import suspects`, `from .textfmt import ends_with_punct`, self.second / self.bg in __init__ and
    # _load_second_job.
    # def _second_text(self, u) -> str | None:
    #     """The second model's formatted transcript of a dictation (cached on it)."""
    #     if u.second is None and self.second is not None and u.audio is not None:
    #         t0 = time.monotonic()
    #         u.second = format_text(self.second.recognize(u.audio), not ends_with_punct(u.text))
    #         log.info("second opinion %.2fs: %s", time.monotonic() - t0, u.second)
    #     return u.second
    #
    # def _suspect_job(self, u):
    #     try:
    #         found = suspects.find(u.text, self._second_text(u))
    #         if found:
    #             log.info("suspects: %s", [(f.word, f.options) for f in found])
    #     except Exception:
    #         log.exception("suspect check failed")

    def _notify(self, text: str):
        self.tray.showMessage("VoiceInput", text, self.icon_idle, 4000)

    # --- popups: 選字 and the hotword notice ---
    def _close_menu(self):
        if self.picker.isVisible():
            self.picker.hide()
        self._menu = None

    def _auto_pick(self):
        """Main thread: while listening, a mouse drag or double click that selects a short word opens the 選字
        menu by itself (the user's request, 2026-10-16: no key needed): up to 4 Chinese characters or 3 English
        words; a longer selection is left for speech to replace. Mouse selections only: a keyboard selection may be
        editing."""
        gen = self._pick_gen

        def probed(ctx):
            sel = ctx.selection
            if gen != self._pick_gen or not self._listening or self._press is not None or self._menu is not None:
                return
            if sel is None or not _pickable(sel.text) or foreground_pid() == os.getpid():
                return
            log.info("auto pick: %r", sel.text)
            self._open_candidates(sel, ctx.terms)
        # the app updates its selection after the button comes up
        QTimer.singleShot(80, lambda: gen == self._pick_gen and self._when_probed(ContextProbe(), probed))

    def _open_candidates(self, sel, terms=()):
        """選字: the candidate menu for the selection, under it. terms: English terms on screen."""
        if sel is None or not sel.text.strip():
            log.info("pick: nothing selected")
            return
        log.info("candidates for %r on %s", sel.text, sel.app)
        self._menu = ("pick", sel)
        self.picker.show_loading(sel.text.strip(), sel.rect)
        threading.Thread(target=lambda: self.candidates_ready.emit(sel, self._menu_tabs(sel, terms)), daemon=True).start()

    def _menu_tabs(self, sel, terms=()) -> list[tuple[str, list[str]]]:
        """The menu's tabs for the selection, by how close they sound (the user's design, 2026-10-16); empty ones
        left out. Chinese: 同音 (the same reading with tones), 不同聲調, 模糊音 (candidates.ranked); a single
        character's smart pick here and earlier picks first in their tab, hotwords first among a word's. English:
        近音字 (common English words and known terms that sound like one word, sounds.near), 詞庫 (known terms:
        the user's list, ticked packs, terms on screen), 大小寫 (ways of writing it, the most picked style first,
        hotwords among them first)."""
        text = sel.text.strip()
        tabs = []
        try:
            if is_latin(text):
                known = self._known_terms(terms)
                if len(text.split()) == 1:
                    tabs.append(("近音字", sounds.near(text, known, picker_mod.WORDS[0] * picker_mod.WORDS[1])))
                tabs.append(("詞庫", sounds.alike(text, known, limit=10)))
                forms = self.memory.ordered_variants(text)
                weights = self.hotwords.weights_for(forms)
                forms.sort(key=lambda w: -weights.get(w, 0))   # stable: the rest keep their order
                tabs.append(("大小寫", forms))
            else:
                found = candidates.ranked(text)
                if len(text) == 1:
                    key = reading_key(text)
                    line = sel.before + sel.text + sel.after
                    start = len(sel.before) + sel.text.index(text)
                    left, right = situation(line, start, start + 1)
                    first = [self.memory.lookup(key, left, right, single=True)] + self.memory.values(key)
                    order = lambda w: (-found[w][1] < candidates.COMMON, found[w][1])
                else:
                    key = reading_key(text)
                    for h in self.hotwords.items:
                        if h.word != text and h.word not in found and reading_key(h.word) == key:
                            found[h.word] = (0, 0)
                    first = []
                    weights = self.hotwords.weights_for(found)
                    order = lambda w: (-weights.get(w, 0), -found[w][1] < candidates.COMMON, found[w][1])
                for rank, name in enumerate(("同音", "不同聲調", "模糊音")):
                    words = sorted((w for w in found if found[w][0] == rank), key=order)
                    mine = [w for w in first if w and (found.get(w, (0,))[0] == rank)]
                    tabs.append((name, mine + words))
        except Exception:
            log.exception("candidates failed")
            tabs = []
        out = []
        for name, words in tabs:
            seen = []
            for w in words:
                if w and w != text and w not in seen:
                    seen.append(w)
            if seen:
                out.append((name, seen))
        return out

    def _known_terms(self, terms) -> list[str]:
        """English terms 選字 may offer for a misheard word: the user's list (highest 優先度 first), the ticked term
        packs, then the terms on screen."""
        listed = sorted((h for h in self.hotwords.items if is_latin(h.word)), key=lambda h: -h.pct)
        return [h.word for h in listed] + [w for w in self.hotwords.pack_pct if is_latin(w)] + list(terms)

    def on_candidates(self, sel, tabs: list):
        if self._menu and self._menu[0] == "pick" and self._menu[1] is sel and self.picker.isVisible():
            self.picker.show_candidates(sel.text.strip(), tabs)

    def _forget_menu(self):
        self._menu = None

    def on_menu_pick(self, word: str):
        menu = self._menu
        self._menu = None
        if menu and menu[0] == "pick" and word:
            self._apply_pick(menu[1], word)

    def _apply_pick(self, sel, word: str):
        """A pick replaces the selection. A single character is learned with its context (smart picks); a word
        gains hotword weight and the word it replaced loses some."""
        text = sel.text.strip()
        lead = sel.text.index(text)
        log.info("menu pick: %s -> %s", text, word)
        if sel.term is not None:
            self.glow.hide_now()
        pasted = _paste_over(sel, sel.text[:lead] + word + sel.text[lead + len(text):])
        if sel.term is not None:
            self._overlay_idle()
        if not pasted:
            self._notify(_SEL_LOST)
            return
        line = sel.before + sel.text + sel.after
        start = len(sel.before) + lead
        self.memory.record(line, start, start + len(text), word)
        if self.cfg.save_recordings:
            recordings.note("pick", before=text, after=word, line=line)
        self.hotwords.picked(text, word)
        self._suggest_pack(word)
        self.settings.refresh_hotwords()
        self.session.replaced_selection(sel.before, word, foreground())
        self.record.emit({"time": time.strftime("%H:%M:%S"), "kind": "選字", "main": f"{text} → {word}", "copy": word,
                          "steps": []})

    # --- settings / status ---
    def on_status(self, text: str):
        self._status_text = text
        log.info("status: %s", text)
        self.tray.setToolTip(f"VoiceInput — {text}")
        self.settings.set_status(text)

    def on_record(self, entry: dict):
        """Something done on its own (a 選字 pick, a selection deleted …): a card of one step."""
        main = entry.get("main") or ""
        self.book.single(entry.get("kind", "輸入"), main, esc(main) or "（無）", entry=entry)

    def _log_changed(self):
        if self.settings.isVisible():
            self.settings.set_log(self.book.sessions)

    def open_settings(self):
        self.settings.load_values()
        self.settings.set_log(self.book.sessions)
        self.settings.set_status(self._status_text)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def apply_settings(self):
        self.hotkeys.set_keys(self._hotkeys())
        if self.glow.style_id != self.cfg.glow or self.glow.edges != self.cfg.glow_edges:
            self.glow.set_style(self.cfg.glow)
            self.glow.set_edges(self.cfg.glow_edges)
            if self._listening and self._listen_shown and self.cfg.glow:
                self.glow.show(self._pointer_screen())
        self.marks.set_color(self.cfg.highlight_color)
        self._update_float()
        if self.cfg.on_focus != "bubble":
            self.bubble.hide()
        self._set_autostart()

    def _set_autostart(self):
        try:
            autostart.set_enabled(self.cfg.autostart)
        except Exception as e:
            log.exception("autostart failed")
            self.settings.set_status(f"開機啟動設定失敗：{e}")

    def quit(self):
        self._quitting = True
        if self._listening:
            self.listener.stop(discard=True)
        self.worker.shutdown(wait=False, cancel_futures=True)
        self.steps.shutdown(wait=False, cancel_futures=True)
        self.muter.restore()
        self.hotkeys.stop()
        if self._mouse:
            self._mouse.stop()
        self.tray.hide()
        self.float_btn.vanish()
        self.qapp.quit()


_CJK_CHAR = re.compile(r"[㐀-䶿一-鿿]")
_TRAILING = re.compile(r"[\s，。、！？；：,.!?;:…]+$")


def _inside(ctx) -> bool:
    """The text goes between text on its line: the caret's, or a selection's (that one got a 。 until 2026-10-15)."""
    sel = ctx.selection
    sides = (sel.before, sel.after) if sel is not None else ctx.caret
    return sides is not None and all(t.strip() for t in sides)


def _no_mark_first(command) -> bool:
    """An operation that takes back what is before the caret: Backspace (刪除) would delete a mark the commit added
    and seem to do nothing (2026-10-15); 復原 (撤銷) showed the 。 for a moment before taking back the last update
    (2026-10-16)."""
    op = command[0] if command is not None else None
    if op is None or not op.steps:
        return False
    st = op.steps[0]
    return (st.type, st.value) in ((rules.KEYS, "Backspace"), (rules.COMMAND, rules.UNDO))


def _go_on(d) -> None:
    """A draft 復原 brought back gets a mark before the speech that goes on after it (its text is not decoded with
    that speech, which would have put one in the pause): ， (？ after 嗎)."""
    if d.revived:
        d.revived = False
        if d.settled and d.settled[-1] not in _MARKS + "、：；…":
            d.settled += "？" if d.settled.endswith("嗎") else "，" if _CJK_CHAR.search(d.settled[-1]) else ","


def _split_at(text: str, tokens: list, times: list, index: list, at: int) -> tuple[str, str]:
    """The recognizer's text split before the first token emitted at sample `at` or later (times in App._speech's
    audio, index its map): (before, from there on); ("", "") when no token is that late."""
    i = next((k for k, t in enumerate(times) if _sample_at(index, int(t * SAMPLE_RATE)) >= at), None)
    if i is None:
        return "", ""
    n = sum(len(re.sub(r"[\s▁]", "", t)) for t in tokens[i:])
    cut = len(text)
    while cut > 0 and n > 0:
        cut -= 1
        n -= not text[cut].isspace()
    while cut < len(text) and (text[cut].isspace() or text[cut] in _MARKS):   # the sentence's own mark
        cut += 1
    return text[:cut], text[cut:]


def _sample_at(index: list, offset: int) -> int:
    """The sample an offset into App._speech's audio was recorded at."""
    for n, lo in reversed(index):
        if offset >= n:
            return lo + offset - n
    return index[0][1]


_SENTENCE_END = re.compile(r"[。？！.?!]$")
_MARKS = "，。？！；"          # punctuation that may close a settled part of a draft
_MARK_SLACK = int(0.2 * SAMPLE_RATE)   # samples a mark may lie outside the pause it closes
_GAP_KEEP = int(0.5 * SAMPLE_RATE)     # more of a pause kept between pieces than their own tail and lead-in


@dataclass
class _Draft:
    """Text typed while listening, not committed yet (main thread)."""
    start: int                 # the sample its audio starts at
    ctx: object                # Context read when its speech began
    sel: object = None         # the Selection its text replaces
    anchor: int = 0            # the sample its open sentence starts at (audio before it is settled)
    settled: str = ""          # text up to a ， or 。 the recognizer put in a pause: not decoded again
    final: str = ""            # what it shows: settled + the open sentence decoded up to the last pause
    typed: str = ""            # what the document shows now (after lead)
    lead: str = ""             # a space typed before it
    placed: bool = False
    shown: int = 0             # the sample its typed text was decoded up to
    revived: bool = False      # brought back by 復原: what is said next goes on after a mark


class _Known:
    """A ContextProbe whose result is known."""

    def __init__(self, ctx):
        self._ctx = ctx

    def result(self, timeout: float = 2.0):
        return self._ctx


def _space_between(a: str, b: str) -> bool:
    """format_text's space between English and Chinese, or between English words."""
    if not a or not b:
        return False
    x, y = a[-1], b[0]
    return bool((_SPACED.match(x) and (_SPACED.match(y) or _CJK_CHAR.match(y))) or (_CJK_CHAR.match(x) and _SPACED.match(y)))


def _joined(a: str, b: str) -> str:
    return a + (" " if _space_between(a, b) else "") + b


def _bias(words: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Biasing words without a Chinese word another one starts with: with 剪貼 and 剪貼簿 both listed, X-ASR wrote 剪貼布
    (the short one is matched first and takes the boost; dev experiment 2026-10-11). English keeps both: dropping
    Gemini for Gemini CLI left Gemini unboosted (the user's recordings, 2026-10-13: 14/14 at 3 with both or alone,
    10/14 with Gemini CLI alone). The first of duplicates wins.
    A lowered word (negative score) sharing a start with another word is left out, so it never costs that one its
    boost or its place (城市 lowered next to 城市規劃)."""
    keys = [w.casefold() for w, _ in words]
    words = [(w, s) for (w, s), k in zip(words, keys)
             if s >= 0 or not any(o != k and (o.startswith(k) or k.startswith(o)) for o in keys)]
    seen = {w.casefold() for w, _ in words}
    out, kept = [], set()
    for w, score in words:
        k = w.casefold()
        if k in kept or (_CJK_CHAR.search(k) and any(o != k and o.startswith(k) for o in seen)):
            continue
        kept.add(k)
        out.append((w, score))
    return out


def _delete_selection(sel) -> bool:
    """Delete the selected text. In a terminal arrow keys move the cursor right after it first
    (selection.move_cursor_after), then Backspace removes it. False when that failed and nothing changed."""
    if sel.term is None:
        press_delete()
        return True
    term_watcher.forget()
    if not move_cursor_after(sel):
        return False
    backspace(len(sel.text), gap=0.02)
    return True


def _paste_over(sel, text: str) -> bool:
    """Replace the selected text: a paste replaces a selection, except in a terminal."""
    if sel.term is not None and not _delete_selection(sel):
        return False
    paste_text(text)
    return True


def main():
    paths.migrate_legacy()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(paths.LOG_PATH, encoding="utf-8"),
                  logging.StreamHandler()],
    )
    packs.install()
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)

    lock = QLockFile(str(paths.LOCK_PATH))
    if not lock.tryLock(100):
        log.info("already running")
        return 0

    app = App(qapp)  # noqa: F841 (keep reference alive)
    return qapp.exec()
