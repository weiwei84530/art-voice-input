"""Art VoiceInput: single-process tray app. Listening is turned on and off from the interface (the floating button, the
bubble by a click in a text box: show_float / show_bubble; a click into a text box: auto_listen), or by pressing the one hotkey (any key or
mouse button but the left one, modifiers allowed, the 一般 tab; 2026-10-16/17, the user's design: nothing else is bound
to keys any more, and a press of it is always a tap: no hold or double tap given back to the key).

What an utterance does:
1. Text is selected (UI Automation): the utterance replaces it.
2. Otherwise it is dictated: formatted and pasted.
An utterance that is exactly a custom operation's phrase (換行, 送出 …) runs that operation instead, and a bare
punctuation name (逗號, 句號 …) is typed as the mark (edit.symbol; a setting since 2026-10-11), and 節日的節 types
節 (edit.described, a setting). Dictated text then
goes through the smart picks (memory.py, single characters only); words are left to X-ASR hotword biasing.

Spoken operations are set on the 自訂操作 tab (rules.py): 換行, 送出, 復原 / 撤銷, 刪除 (Backspace) and a few more.
While listening, a short mouse selection opens 選字 by itself.

Recording is continuous listening (listen.py; on the continuous-mic branch since 2026-10-14 the one way, the
user's choice: no cutting the recording to say a command). Every pause ends a piece: said alone, an operation's
phrase or a punctuation name commits the draft and runs or types it; otherwise the piece joins the draft, which is
decoded again and typed in place (in place of the text selected when its speech began, if any: the user may select
with the mouse while listening), punctuation included; only its open sentence is decoded again (text up to a mark
the recognizer put in a pause is settled). A commit (by a command, the end of listening, or a pause once the
draft is long) decodes the open sentence once more; by an operation or the end of listening it keeps the
recognizer's 。？！ or gets 。 (a spoken mark is typed instead). Moving the caret leaves a draft as typed, and speech
not typed yet is decoded again at the new caret.

The one popup (picker.py) is the 選字 candidate menu; it came back 2026-10-11 after the lean branch removed every
popup and was redesigned 2026-10-16 (tabs by how close the candidates sound, no input box). The second opinion
(SenseVoice + suspects.py) is commented out below.
"""
import ctypes
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

import numpy as np
from PySide6.QtCore import QLockFile, QObject, QProcess, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QAction, QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu

from . import (appicon, autostart, candidates, config, cues, edit, models, packs, paths, recordings, rules, sounds,
               spelling, syllables)
from .asr import SAMPLE_RATE, Recognizer
from .config import Config
from .floatbtn import Bubble, FloatButton
from .glow import EdgeGlow, edges_for, style_for
from .orbs import palette
from .highlight import DraftMarks, draft_rects
from .logbook import BANK_HITS, LogBook, bank_of, esc
from .hotwords import Hotwords
from .hotkey import Hotkeys
from .keys import combo_vks, upgrade_hotkey
from .listen import LEAD, Listener
from .memory import Memory, is_latin, situation
from .mute import Muter, recover as recover_mute
from .output import (backspace, copy_text, paste_text, press_chord, press_delete, press_key, restore_now,
                     text_before, watch_clipboard)
from . import picker as picker_mod
from .picker import Picker
from .reading import reading_key
from .selection import (Context, ContextProbe, focus_info, move_cursor_after, term_watcher,
                        terminal_in_front)
from .session import Session, foreground
from .tray import Tray, promote as tray_promote
from .ui.window import SettingsWindow
from .textfmt import format_text, to_traditional

log = logging.getLogger("artvoiceinput")

_SCREEN_TERM_SCORE = 1.5
# Spoken commands (speech operations' phrases, punctuation names) are boosted only when the utterance is short: they
# are said alone, and boosting them in every sentence would turn 還行 into 換行 (the user's choice, 2026-10-11).
# "Short" is judged by the first decode's text (at most the longest command + _COMMAND_SLACK characters), which then
# runs again with the commands: the audio's length was no use, TTS 換行 alone was already 1.7s with its silences.
# With TTS the boost fixed 據點 -> 句點 and 珊姐好 -> 刪節號; alone, 問好 / 分好 became 問號 / 分號.
_COMMAND_SCORE = 5.0
_COMMAND_SLACK = 2
# A piece of at most _FIRST_MAX seconds of speech is decoded first with the commands alone boosted, padded with _PAD
# seconds of silence at both ends (dev/cmdlab, 2026-10-17, the user's recordings of continuous listening: commands
# 96.7% -> 98.7%, 換行 missed 21 -> 8 times, still no text taken for a command). X-ASR writes a command as English
# when the audio does not start and end in silence (換行 -> Hang Hung, 刪除 -> Central): the padding alone fixed 23
# of the 31 misses. Most commands then need one decode instead of up to two.
_FIRST_MAX = 1.2
_PAD = 0.3
_WORDS = re.compile(r"[㐀-䶿一-鿿]|[A-Za-z0-9]+")   # a Chinese character or an English word counts one
_SEL_LOST = "找不到選取的文字，沒有修改"   # a terminal selection that moved or the cursor could not reach
# from the call to PlaySound until the start sound has left the speakers: measured 0.17s on the user's machine
# (Realtek speakers, Logi C270 microphone, 2026-10-13); the level bars and muting wait the sound's length plus this,
# or Kalimba's tail moved the bars and Woodblock (0.19s) was muted before it was heard
_CUE_LATENCY = 0.25
_STEP_GAP = 0.03           # seconds between the steps of an operation
_DRAFT_MAX = 60            # seconds: a longer draft is committed at a pause (decoding it again gets slow)
_SPACED = re.compile(r"[A-Za-z0-9]")
_FUZZY_MIN = 3             # a word only fuzzy-alike is listed in 選字 from this dictionary frequency on
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
    return window_pid(ctypes.windll.user32.GetForegroundWindow())


def window_pid(hwnd) -> int:
    import ctypes.wintypes
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


@dataclass
class _Press:
    """What turned listening on (the hotkey, the floating button, the bubble, the focus), or a spoken operation
    ("listen") whose steps run."""
    key: str
    probe: object                     # ContextProbe started then
    down_at: float
    dictated: bool                    # the last dictation could still be deleted then
    deleted: object = None            # Selection a 刪除 step removed (the dictation goes there)


class App(QObject):
    hotkey_tap = Signal()                    # the hotkey was pressed (hook thread)
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
        watch_clipboard()   # its last texts: 貼上 in a terminal that copied the selection as it was made
        self.muter = Muter()
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
        # worker thread: the last pause's decode of the open sentence, (start, anchor, its last piece, raw text): a
        # commit right after it reuses the text instead of decoding the same audio again (dev/cmdlab, 2026-10-17:
        # 0.24s median before a command, the same text in 91% of the user's commits)
        self._live = None
        self._quick_done = None                  # worker thread: the end (hi) of a quick piece run as a command
        # the pieces of a draft 復原 brought back as it was, for the worker to take up (_take_restored)
        self._restored_spans, self._restore_lock = None, threading.Lock()
        self.hotwords = Hotwords()
        self._pack_stamp = None
        self._pack_of: dict[str, str] = {}      # ticked packs' words -> the pack's name
        self._load_packs()
        self.memory = Memory()
        self._menu = None                        # ("pick", Selection) while the 選字 menu is up
        self._pick_gen = 0                       # mouse presses so far: a selection read late is dropped

        self._busy, self._busy_lock = 0, threading.Lock()   # decoding jobs queued or running
        self.glow = EdgeGlow(lambda: self.listener.level if self._listening else 0.0)
        self.glow.set_style(style_for(self.cfg.glow, self.cfg.glow_edits))
        self.glow.set_edges(edges_for(self.cfg.glow, self.cfg.glow_edits))
        self.glow.set_motion(self.cfg.glow_motion)
        self.glow.set_lite(self.cfg.orb_lite)
        self._preview_end = QTimer(self, singleShot=True,
                                   timeout=lambda: None if self._listening else self.glow.hide())
        self.float_btn = FloatButton(self.cfg.float_pos)
        self.float_btn.clicked.connect(self._float_clicked)
        self.float_btn.moved.connect(self._float_moved)
        self.bubble = Bubble()
        self.bubble.clicked.connect(lambda: self._listen_now("bubble"))
        self._own_hwnds = {self.float_btn.hwnd(), self.bubble.hwnd()}
        self._apply_look()   # clicks on these are not caret moves
        self._box = None                         # the text box the focus is in, its identity
        self._click = None                       # (point, time) of a click the bubble may show by
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
        self.settings = SettingsWindow(self.cfg, self.hotwords, self.memory)
        self.settings.applied.connect(self.apply_settings)
        self.picker.use_theme(self.settings.theme)   # light or dark with the settings window
        self.book = LogBook(self._log_changed)   # the 辨識紀錄 page, kept for this session only
        self.settings.clear_log.connect(self._clear_log)
        self.settings.glow_preview.connect(self._preview_glow)
        self.settings.wizard_heard.connect(self._wizard_heard)
        self.settings.restart.connect(self.restart)
        self._heard_at = 0.0                     # when speech last began while listening (auto_off_minutes)
        self._idle_timer = QTimer(self, interval=5000, timeout=self._check_idle)
        self._idle_timer.start()

        menu = QMenu()
        menu.addAction(QAction("設定…", menu, triggered=self.open_settings))
        menu.addSeparator()
        menu.addAction(QAction("結束", menu, triggered=self.quit))
        self._tray = Tray(menu, self)   # left click: listening on / off; the menu on the right button
        self._tray.set_lite(self.cfg.orb_lite)
        self._tray.clicked.connect(self._tray_clicked)
        self.tray = self._tray.icon
        self._toast = ""   # what the last tray notice leads to when clicked ("packs")
        self.tray.messageClicked.connect(self._toast_clicked)
        self._tray.show()
        self._typing_hwnd = 0   # the last foreground window outside the taskbar (_tray_clicked gives it back)
        self._fg_hook = self._watch_foreground()
        self._pin_tries = 0
        self._pinned = None     # what the tray icon was last set to (None: left to Windows)
        if self.cfg.tray_pinned:
            self._pin_tray()

        self.hotkey_tap.connect(self._on_hotkey)
        self.main.connect(lambda fn: fn())
        self.candidates_ready.connect(self.on_candidates)
        self.status.connect(self.on_status)
        self.record.connect(self.on_record)

        self.cfg.hotkey = upgrade_hotkey(self.cfg.hotkey)
        self.hotkeys = Hotkeys(self.hotkey_tap.emit, self._on_other_key)
        self.hotkeys.set_hotkey(self.cfg.hotkey)
        self.settings.capture_hotkey.connect(self._capture_hotkey)
        self.hotkeys.start()
        self._mouse = self._watch_mouse()
        self.worker.submit(self._load_model_job)
        # self.bg.submit(self._load_second_job)
        candidates.preload()   # the disfluency pass uses the dictionary
        sounds.preload_english()   # 選字's near sounds for English
        syllables.preload()   # one character said alone that came out as English (App._as_chinese)
        if self.cfg.autostart:
            self._set_autostart()   # re-register so the entry follows the app if its folder was moved
        self._update_float()

    def _on_other_key(self, vk: int):
        """Keyboard hook thread: a key the user pressed (injected keys never get here); it closes the 選字 menu.
        Enter (or Ctrl+Enter, not Shift or Alt) sends: with 送出後關閉麥克風 listening turns off."""
        if vk == 0x0D and self._listening and self.cfg.stop_on_enter and not _held(0x10) and not _held(0x12) \
                and not _ours(foreground()):
            log.info("listen: off, Enter pressed")
            self.main.emit(lambda: self._stop_listen() if self._listening else None)
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
                if self.cfg.show_bubble:
                    self.main.emit(self.bubble.hide)   # the user's request, 2026-10-16
            elif msg == 0x202:
                term_watcher.mouse_up(data.pt.x, data.pt.y)
                down, clicks["down"] = clicks["down"], None
                if down is not None and abs(down[0] - data.pt.x) + abs(down[1] - data.pt.y) <= 4:
                    pt = (data.pt.x, data.pt.y)
                    self.main.emit(lambda: self._clicked(pt))
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

    # --- the hotkey ---
    def _on_hotkey(self):
        """Main thread: the hotkey turns listening on or off."""
        self._close_menu()
        log.info("hotkey")
        if self._paused:
            return
        if self._listening:
            self._stop_listen()
        else:
            self._listen_now("hotkey")

    def _capture_hotkey(self, on: bool):
        """The settings' 麥克風快捷鍵 button: the next press is the new hotkey (on), or capturing is cancelled."""
        if not on:
            self.hotkeys.cancel_capture()
            return
        self.hotkeys.capture(lambda spec: self.main.emit(lambda: self.settings.hotkey_captured(spec)))

    def _when_probed(self, probe, fn):
        """Run fn(Context) on the main thread once probe has read the focused app."""
        def wait():
            ctx = probe.result()
            self.main.emit(lambda: fn(ctx))
        threading.Thread(target=wait, daemon=True).start()

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
    def _paused(self) -> bool:
        """Until the setup wizard is finished nothing listens or shows (the user's request, 2026-10-21): no hotkey,
        floating button, bubble or listening on a click, also with the wizard closed half way."""
        return not self.cfg.setup_done

    @property
    def _listening(self) -> bool:
        return self.listener is not None and self.listener.active

    def _start_listen(self, press: _Press):
        """The microphone on; pieces wait until _show_listen."""
        if self.recognizer is None:
            return
        try:
            if self.listener is None:
                self.listener = Listener(str(models.vad_path()), self._on_listen_speech, self._on_listen_piece,
                                         self._on_listen_quick)
            self.listener.start(self.cfg.mic, quick=True)
        except Exception as e:
            log.exception("listen start failed")
            self._notify(f"無法開啟麥克風：{e}")
            return
        self._listen_owner, self._listen_shown = press, False
        self._listen_probe = None
        begin = self.listener.now

        def fresh():   # worker thread, after the last session's pieces and its end (they still need its draft)
            self._spans = []
            self._live = self._quick_done = None

            def reset():
                self._draft, self._draft_start = None, begin
                self._committed = None
                self.listener.keep(begin)
                self.listener.hold(None)
            self._on_main(reset)
        self.worker.submit(fresh)
        with self._early_lock:
            self._early_pieces = []

    def _show_listen(self, press: _Press):
        """The glow fades in and the start sound plays together (the user's design, 2026-10-13)."""
        if not self._listening or self._listen_owner is not press or self._listen_shown:
            return
        log.info("listen: on (%s)", press.key)
        self._listen_shown = True
        self.book.new_session()
        self._tray.set_listening(True)
        self.settings.set_listening(True)
        self.glow.show(self._pointer_screen())
        cues.play(self.cfg.start_sound, "start", self.cfg.cue_volume)
        wait = cues.duration(self.cfg.start_sound, "start")
        if wait:
            wait += _CUE_LATENCY
            self.listener.still(wait)   # the start sound is not speech; muting waits for its end
        self._heard_at = time.monotonic()
        self._update_float("start")
        self.bubble.burst()   # grows and fades out with the glow fading in; back only at the next click
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
    def _update_float(self, event: str = ""):
        """Main thread: with show_float the floating button fades in while the focus is where text can be typed
        (the user's request, 2026-10-16: listening is for editing text), anywhere with float_text_only off. When
        listening starts ("start") it grows and fades out with the glow, and comes back as the glow goes ("stop"),
        unless float_keep keeps it on screen."""
        b = self.float_btn
        if not self.cfg.show_float or self._quitting or self._paused:
            show = False
        else:
            show = (self._box is not None or not self.cfg.float_text_only) \
                and (not self._listening or self.cfg.float_keep)
        b.setToolTip("關閉麥克風" if self._listening else "開啟麥克風")
        b.set_active(self._listening and show)
        if show:
            if event == "stop" and (not b.isVisible() or b.leaving):
                b.come_back()
            else:
                b.appear()
        elif event == "start":
            b.burst()
        else:
            b.vanish()

    def _tray_clicked(self):
        """Main thread: a left click on the tray icon turns listening on or off (2026-10-21, the user's design; the menu
        is on the right button). Clicking the taskbar made it the foreground window: the one typed into before gets
        the focus back, so the text goes there. While the setup wizard is not finished it opens the wizard."""
        self._close_menu()
        if self._paused:
            self.open_settings()
            return
        if self._listening:
            self._stop_listen()
            return
        if self._typing_hwnd and _taskbar(foreground()):
            ctypes.windll.user32.SetForegroundWindow(self._typing_hwnd)
        self._listen_now("tray")

    def _watch_foreground(self):
        """The last foreground window that is not the taskbar or ours (a WinEvent hook, called on this thread)."""
        proto = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_long,
                                   ctypes.c_long, ctypes.c_uint32, ctypes.c_uint32)

        def changed(_hook, _event, hwnd, *_):
            if hwnd and not _taskbar(hwnd) and window_pid(hwnd) != os.getpid():
                self._typing_hwnd = hwnd
        callback = proto(changed)
        hook = ctypes.windll.user32.SetWinEventHook(0x0003, 0x0003, None, callback, 0, 0, 0)   # EVENT_SYSTEM_FOREGROUND
        return hook, callback   # the callback must outlive the hook

    def _pin_tray(self):
        """系統's 在工作列顯示圖示: Explorer lists a new icon a moment after it first shows, so tried again a few
        times. Off at launch writes nothing (a choice made in Windows' own settings stays)."""
        if tray_promote(self.cfg.tray_pinned):
            self._pinned = self.cfg.tray_pinned
            log.info("tray icon %s", "on the taskbar" if self.cfg.tray_pinned else "in the overflow")
        elif self._pin_tries < 5:
            self._pin_tries += 1
            QTimer.singleShot(2000 * self._pin_tries, self._pin_tray)

    def _float_clicked(self):
        """Main thread: the floating button turns listening on, as a tap of the key would (the text goes to the
        window that has the focus: the button never takes it); kept on screen while listening (float_keep), it
        turns listening off (it is smaller and plays faster while listening)."""
        if self._listening:
            self._stop_listen()
            return
        self._listen_now("button")

    def _listen_now(self, name: str, quiet: bool = False) -> bool:
        """Main thread: listening on without a key (the floating button, the bubble, the focus). quiet: no notice
        when the model is not ready."""
        if self._listening or self._paused:
            return False
        if self.recognizer is None:
            if not quiet:
                self._notify(self._status_text or "模型尚未就緒")
            return False
        press = _Press(name, ContextProbe(), time.monotonic(), self.session.deletable() is not None)
        self._start_listen(press)
        self._show_listen(press)
        return self._listening

    def _apply_look(self):
        """The floating button's and the bubble's look, in the glow's colors (彩虹 when there is no glow)."""
        colors = palette(style_for(self.cfg.glow, self.cfg.glow_edits))
        for w in (self.float_btn, self.bubble):
            w.set_look(self.cfg.button_look, colors, self.cfg.orb_lite, self.cfg.button_scale)

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
        """Main thread, every 0.3s with a button by text boxes, auto_listen or auto_off: where the focus is, read on a
        thread (UI Automation)."""
        if not (self.cfg.show_bubble or self.cfg.show_float or self.cfg.auto_listen or self.cfg.auto_off) \
                or self._focus_busy or self._quitting:
            return
        self._focus_busy = True
        settings = int(self.settings.winId()) if self.settings.isVisible() else 0

        def read():
            started = time.monotonic()   # a click before this is where the focus read is
            info = focus_info()
            if info[0] is None and settings and foreground() == settings:
                # our settings window in front counts as a place where nothing can be typed (2026-10-20, the
                # user's request: with listening still on the user believes the text box still takes it); the
                # floating button, bubble and 選字 menu never take the foreground and still change nothing
                info = (False, None)
            self.main.emit(lambda: self._focus_seen(*info, started))
        self._focus_pool.submit(read)

    def _clicked(self, pt):
        """Main thread: a left click (not a drag) outside our windows. With the bubble or auto_listen, the focus is
        read soon after (where the click put it): in a text box the bubble shows by the click (2026-10-16, the user's
        design), or listening comes on (2026-10-20, the user's design)."""
        if not (self.cfg.show_bubble or self.cfg.auto_listen) or self._listening or self._paused:
            return
        self._click = (pt, time.monotonic())
        QTimer.singleShot(120, self._watch_focus)

    def _focus_seen(self, editable, key, started: float = 0.0):
        """Main thread (the user's requests, 2026-10-16 and 20). The focus is in a text box: a click that has just put it
        there shows the bubble by the click, or with auto_listen turns listening on (keyboard focus does neither);
        the floating button shows. The focus went where nothing can be typed (a web page's blank part, a button, the
        desktop): the bubble goes, and with auto_off listening is turned off (when it was in a text box before:
        listening may be turned on by hand anywhere); the settings window in front counts as such a place. Unknown
        places and Art VoiceInput's other windows change nothing."""
        self._focus_busy = False
        if self._paused:
            return
        bubble, floating, auto = self.cfg.show_bubble, self.cfg.show_float, self.cfg.auto_listen
        if not (bubble or floating or auto or self.cfg.auto_off) or editable is None:
            return
        click = None
        if self._click is not None and self._click[1] <= started:   # a read begun before it says nothing of it
            click, self._click = self._click, None
        if editable:
            self._box = key
            clicked = click is not None and time.monotonic() - click[1] < 1.5
            if auto and not self._listening and clicked:
                log.info("listen: on, clicked into a text box")
                if self._listen_now("focus", quiet=True):
                    self._box_auto = True
            if bubble and not self._listening and clicked:
                self.bubble.show_at(click[0])
            if floating:
                self._update_float()
            return
        was, self._box = self._box, None
        self.bubble.fade_out()   # the user's request, 2026-10-16
        self._update_float()
        if self.cfg.auto_off and was is not None and self._listening:
            log.info("listen: off, the focus left the text box (自動關閉麥克風)")
            self._stop_listen(by_focus=True)

    def _preview_glow(self, style_id: str):
        """A glow style picked, changed or previewed in the settings: shown for a moment (unless listening shows it
        already); a change while it shows restarts the moment."""
        self.glow.set_style(style_for(style_id, self.cfg.glow_edits))
        self.glow.set_edges(edges_for(self.cfg.glow, self.cfg.glow_edits))
        self.glow.set_motion(self.cfg.glow_motion)
        if not self._listening:
            self.glow.show(QGuiApplication.screenAt(self.settings.geometry().center()))
            self._preview_end.start(3000)

    def _stop_listen(self, by_focus: bool = False):
        """Listening off. by_focus: the focus left the text box (auto_off)."""
        self._box_auto = False
        self._listen_owner, self._listen_shown = None, False
        self.listener.stop()   # speech still going on is handed over as a last piece
        self.book.end_session()
        log.info("listen: off")
        self._tray.set_listening(False)
        self.settings.set_listening(False)
        self.glow.hide()
        self._marks_timer.stop()
        self.marks.hide()
        self._update_float("stop")
        # the bubble doesn't come back: it shows again at the next click into a text box (the user's request,
        # 2026-10-20)
        # the end sound marks the microphone going off, nothing about the text (the user's choice, 2026-10-16: the
        # 文字輸入完成時 option was removed)
        self.muter.restore()
        if self.cfg.stop_sound:
            cues.play(self.cfg.stop_sound, "stop", self.cfg.cue_volume)
        end = self.listener.now

        def finished():   # worker thread, after the last piece: the rest of the draft is committed, then the steps
            self._on_main(lambda: None)
            self._take_restored()
            d = self._draft
            spans, self._spans = self._spans, []
            if d is not None:
                spans = [p for p in spans if p.start >= d.anchor]
                # a draft 復原 brought back with nothing said since: the silence after it is not decoded ("So")
                quiet = d.revived or (d.restored and not spans)
                self._commit_job(self._draft_start, d.anchor, d.anchor if quiet else end, end, d.ctx,
                                 final=True, spans=spans)
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

    def _on_listen_quick(self, piece):
        """Listener thread: short speech after a pause stopped for listen.QUICK_SILENCE (always, 2026-10-20): a
        command runs now, before the piece ends (_piece_job, quick)."""
        with self._early_lock:
            if self._early_pieces is not None:   # the press is not known to listen yet
                return
        if self.recognizer is not None:
            self._decoding(self._piece_job, piece, self._listen_probe, True)

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
        self.listener.hold(None)   # the caret moved: 復原 can no longer bring a draft back
        log.info("draft left as typed: %s", d.typed if d else "")
        if d is not None and d.placed and d.typed:   # never committed: logged as it stands
            self.book.frozen(d.typed)
        self._draft = None
        if at is None:
            at = self._speech_sample if self._speech_sample > self._draft_start else self.listener.now
        self._draft_start = at
        self.listener.keep(at)

    def _refine(self, start: int, anchor: int, settled: str, live: str, after: int, upto: int, ctx,
                info: dict | None = None, prior: list | None = None):
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
        # the draft as it was, for 復原 to bring back with its open sentence still open (the user's request,
        # 2026-10-16): prior holds that sentence's pieces before this update's
        snap = replace(d) if d is not None and d.placed and prior is not None else None
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
        last = self.session.history[-1] if self.session.history else None
        self._show_draft(step=True)
        if snap is not None and self.session.history and self.session.history[-1] is not last:
            self.session.history[-1].restore = (snap, list(prior))
            self.listener.hold(snap.anchor)
        if d.placed and d.typed == d.final:
            d.shown = upto
            self.book.heard(info, before, d.typed, settled)

    def _commit(self, text: str, start: int, anchor: int, at: int, ctx, command=None, final: bool = False,
                spans: list = ()):
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
                pre = replace(d)   # as it was: 復原 of the change after the commit brings it back so
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
                self._committed = (b[:len(b) - len(d.typed)], d, self.session.history[-1], pre, list(spans)) \
                    if d.placed and d.typed and self.session.clean() and b.endswith(d.typed) \
                    and self.session.history else None
                if self._committed is not None and pre.placed:
                    self.listener.hold(pre.anchor)
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
        alike = _alike(raw, names)
        if alike:   # before the boost: it made the user's 金嘆號 (驚嘆號) 金看號
            log.info("asr sounds like a command: %s -> %s", raw, alike)
            return alike
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

    def _command_first(self, audio, piece) -> str:
        """A piece of little speech (_FIRST_MAX) decoded with the spoken commands alone boosted, padded with
        silence: the recognizer's text when that is exactly a command, else "" (the piece is decoded as usual)."""
        names = self._command_words()
        if not names or piece.end - piece.start > _FIRST_MAX * SAMPLE_RATE:
            return ""
        pad = np.zeros(int(_PAD * SAMPLE_RATE), np.float32)
        raw = self.recognizer.recognize(np.concatenate([pad, audio, pad]),
                                        _bias([(w, _COMMAND_SCORE) for w in names]))
        raw = _one_command(raw, names)
        said = rules.normalize(to_traditional(raw))
        if any(said == rules.normalize(n) for n in names):
            return raw
        alike = _alike(raw, names)
        if alike:
            log.info("asr sounds like a command: %s -> %s", raw, alike)
        return alike

    def _bias_words(self, ctx) -> list:
        """Hotwords and on-screen terms, as the recognizer takes them. Not a command's phrase: a word picked in 選字
        is a hotword too, and the user's 括號 at 200% turned their 逗號 and 換行 said alone into 括號 (2026-10-16, 5
        of their recordings; commands are boosted all together, and only for a short piece)."""
        self._load_packs()
        commands = {rules.normalize(w) for w in self._command_words()}
        words = [(w, s) for w, s in self.hotwords.bias() if rules.normalize(w) not in commands]
        return _bias(words + [(t, _SCREEN_TERM_SCORE) for t in ctx.terms])

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
        chinese = self._as_chinese(formatted, ctx)
        if chinese:
            steps.append(("英文轉中文", formatted, chinese))
            formatted = chinese
        prefix = ctx.selection.before if ctx.selection else (ctx.caret[0] if ctx.caret else "")
        text = self.memory.apply(formatted, prefix, self.hotwords.levels())
        if text != formatted:
            steps.append(("選字記憶", formatted, text))
        hits = self._bank_hits(text)
        if hits:
            steps.append((BANK_HITS, "、".join(hits), None))
        return text

    def _as_chinese(self, text: str, ctx) -> str:
        """One character said alone comes out of X-ASR as an English syllable (2026-10-21, the user's report: 啊 to
        replace a selected 阿 came out as Ah, 的 added in a sentence as The): the utterance, one English word of 2-6
        letters, not all capitals (AI, API) and no known term, becomes the likeliest character
        (syllables.chinese_for) when it replaces one selected Chinese character (never that character again) or
        goes next to Chinese at the caret. "" when not."""
        word = text.strip()
        if not re.fullmatch(r"[A-Za-z]{2,%d}" % syllables.MAX_LETTERS, word) or word.isupper():
            return ""
        if word.casefold() in {t.casefold() for t in self._known_terms(ctx.terms)}:
            return ""
        sel = ctx.selection
        if sel is not None:
            if not _is_cjk(sel.text.strip()) or len(sel.text.strip()) != 1:
                return ""
            before, after, exclude = sel.before, sel.after, sel.text.strip()
        elif ctx.caret:
            before, after, exclude = ctx.caret[0], ctx.caret[1], ""
        else:
            return ""
        left, right = before.rstrip(" ")[-1:], after.lstrip(" ")[:1]
        left, right = (left if _is_cjk(left) else ""), (right if _is_cjk(right) else "")
        if sel is None and not (left or right):
            return ""
        found = syllables.chinese_for(word, left, right, limit=1, exclude=exclude)
        if found:
            log.info("english as chinese: %s -> %s (%s|%s)", word, found[0], left, right)
        return found[0] if found else ""

    def _bank_hits(self, text: str) -> list[str]:
        """Words of the 詞庫 the recognizer was pulled toward or away from that are in the text: "Claude Code
        +50%（AI 工具與模型）" (the 辨識紀錄's 詞庫 mark, 2026-10-17, the user's request: the biasing may or may not
        have made them, but the sentence went through it)."""
        out = []
        for word, pct in self.hotwords.levels().items():
            if word.isascii():
                found = re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", text, re.IGNORECASE)
            else:
                found = word in text
            if found:
                where = "詞庫列表" if self.hotwords.find(word) is not None else self._pack_of.get(word, "詞包")
                out.append(f"{word} {pct - 100:+d}%（{where}）")
        return out

    def _piece_job(self, piece, probe, quick: bool = False):
        """A piece of speech ended. Said alone, a command commits the draft before it and runs; otherwise the
        draft's open sentence is decoded again up to here (committed when the setting says every pause).
        quick: a quick piece (_on_listen_quick): only a command _quick_ok allows runs, anything else waits for the
        piece."""
        try:
            done = self._quick_done
            if not quick and done is not None:
                # the piece the quick one was cut from: dropped when its speech ends within the quick piece's audio
                # (the VAD ends a piece where the silence began, whatever silence it waits for: the same sample, give
                # or take a window), else only what follows is this piece
                self._quick_done = None
                if piece.end <= done:
                    log.info("piece already run at the short pause")
                    return
                if piece.start < done:
                    piece = replace(piece, lo=done, start=done)
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
            self._take_restored()
            audio = self.listener.audio(piece.lo, piece.hi)
            t0 = time.monotonic()
            raw = self._command_first(audio, piece)
            if quick:
                steps = []
                op, typed = self._command(format_text(raw, True, steps), ctx, steps, raw) if raw else (None, None)
                if not _quick_ok(op, typed):
                    return   # the piece decides
                self._quick_done = piece.hi
                log.info("quick piece: %s", raw)
            self._spans = [p for p in self._spans if p.start >= anchor] + [piece]
            raw = raw or self._decode(audio, ctx, commands=True)
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
            elif piece.hi - anchor > _DRAFT_MAX * SAMPLE_RATE:
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
        prior = [p for p in self._spans if p is not piece]   # the open sentence before this piece (復原)
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
        self._live = (start, after, piece, live)
        steps = []   # for the 辨識紀錄's 詞庫 mark
        settled = self._text_of(settled, ctx, steps, keep_end=True) if settled else ""
        live = self._text_of(live, ctx, steps, keep_end=True)
        log.info("draft %.2fs: %s | %s", time.monotonic() - t0, settled, live)
        info = dict(info or {}, redo_s=time.monotonic() - t0, bank=bank_of({"steps": steps}))
        self.main.emit(lambda: self._refine(start, anchor, settled, live, after, piece.hi, ctx, info, prior))

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
        self._take_restored()
        spans = [p for p in self._spans if p.hi > at]
        if not state.get("go") or not spans:   # a later piece got there first
            return
        self._spans = spans
        self._refine_job(at, at, spans[-1], ContextProbe().result(), info={"redo": True})

    def _take_restored(self):
        """Worker thread: a draft 復原 brought back as it was: its open sentence's pieces are the draft's again."""
        with self._restore_lock:
            spans, self._restored_spans = self._restored_spans, None
        if spans is not None:
            self._spans = spans

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
        live, self._live = self._live, None
        # the last pause decoded this same audio (its last piece is the open sentence's last): its text is used
        # (spans would differ after 復原 took that update back)
        if live is not None and live[:2] == (start, anchor) and spans and spans[-1] is live[2] and end > anchor:
            raw = live[3]
            log.info("commit reuses the last pause's text")
            text = self._text_of(raw, ctx, steps, keep_end=final) if raw.strip() else ""
        elif audio.size >= SAMPLE_RATE * 0.2:
            raw = self._decode(audio, ctx)
            text = self._text_of(raw, ctx, steps, keep_end=final)
        if text:
            log.info("commit %.2fs: %s", time.monotonic() - t0, text)
            self._keep(audio, asr=raw, fmt=text, result=text, op=None)
        self.main.emit(lambda: self._commit(text, start, anchor, at, ctx, command, final, spans))

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
        stop = False
        try:
            for n, step in enumerate(steps):
                if n:
                    time.sleep(_STEP_GAP)
                # a spoken operation with text selected acts on the selection (the user's request, 2026-10-16: in
                # Claude Code a mouse selection leaves the cursor where it was, and 刪除 deleted there), recorded so
                # that 復原 brings it back (the user's request the same day: the mouse selection had ended what 復原
                # could take back)
                sel = press.probe.result().selection if press.key == "listen" and press.deleted is None else None
                if sel is not None and (
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
                        if step.value in ("Shift+Enter", "Space"):   # a new line or a space, which 復原 takes back
                            ch = "\n" if step.value == "Shift+Enter" else " "
                            if sel is not None and sel.term is None:
                                # typed over the selection: 復原 brings it back (recorded as typed at the caret, it
                                # took back the space alone and the selected text stayed lost; 2026-10-17, a review)
                                self._on_main(lambda c=ch, s=sel: self._typed_over(press, s, c))
                            else:
                                self._on_main(lambda c=ch: self.session.dictated(c, None, foreground()))
                        elif step.value == "Backspace":   # one character less, which 復原 can type again
                            self._on_main(lambda: self._backspaced(press))
                        else:
                            self.session.on_input()     # the caret may have moved
                            # 送出 said, with 送出後關閉麥克風: listening off once the steps are done
                            stop = stop or (step.value in ("Enter", "Ctrl+Enter") and press.key == "listen"
                                            and self.cfg.stop_on_enter)
                elif step.type == rules.TEXT:
                    self._on_main(lambda t=step.value: self._type_text(t))
                elif step.type == rules.COMMAND and step.value == rules.UNDO:
                    self._on_main(lambda: self.undo(press.probe.result() if press.key == "listen" else None))
                elif step.type == rules.COMMAND and step.value == rules.STOP:
                    self._on_main(lambda: self._stop_listen() if self._listening else None)
            if stop:
                log.info("listen: off, sent")
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

    def _backspaced(self, press: _Press):
        """Main thread: a Backspace step deleted the character before the caret. After the caret moved, the line
        before it as read when the command was said tells which (2026-10-17, the user's request: 復原 after it)."""
        s = self.session
        if not s.clean():
            caret = press.probe.result().caret if press.key == "listen" else None
            if not caret or not caret[0]:
                s.on_input()
                return
            s.known(caret[0], foreground())
        s.changed(s.buffer[:-1])

    def _typed_over(self, press: _Press, sel, text: str):
        """Main thread: a key or Ctrl+X / Ctrl+V of an ordinary app replaced the selection with text."""
        press.deleted = sel
        self.session.replaced_selection(sel.before, text, foreground(), sel.before + sel.text)

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
        """Main thread: text typed over a selection."""
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
            text = _plain(_clipboard_text()) if command == rules.PASTE else ""
            press_chord(0x11, {rules.SELECT_ALL: 0x41, rules.COPY: 0x43, rules.CUT: 0x58, rules.PASTE: 0x56}[command])
            # 剪下 / 貼上 are changes 復原 takes back (2026-10-17, the user's request) when what they did is known
            if command == rules.CUT and sel is not None:
                self._typed_over(press, sel, "")
            elif command == rules.PASTE and text and sel is not None:
                self._typed_over(press, sel, text)
            elif command == rules.PASTE and text:
                self.session.dictated(text, None, foreground())
            elif command != rules.COPY:
                self.session.on_input()   # the text or the caret changed in ways we do not follow
            return
        if command == rules.SELECT_ALL:
            self._notify("終端機裡無法全選")
            return
        if command == rules.PASTE and sel is None:
            text = _plain(_clipboard_text())
            press_chord(0x11, 0x56)
            if text:
                self.session.dictated(text, None, foreground())
            else:
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
            text = _clipboard_text()
            if text == sel.text:
                # the terminal copied the selection itself as it was made (Claude Code does): what was copied before
                text = text_before(text) or text
                log.info("paste: the clipboard held the selection, pasting the text before it")
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

    def undo(self, ctx=None):
        """Main thread, 復原 (and 刪除剛輸入的文字): take back Art VoiceInput's last change while it is still right before
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
        if step.read and not _still_reads(s.buffer, ctx):
            # what it would type back was read from the screen after the caret moved, and the screen does not show
            # that now (or cannot be read): rather nothing than the wrong text (2026-10-17, the user's request)
            log.info("undo: the text before the caret is not what was read, not taken back")
            self._notify("無法確定游標前的文字，這次不復原（避免打回錯的字）")
            return
        d = self._draft
        restore = step.restore   # the draft as it was before this update, its open sentence still open
        if d is not None and d.placed and step.after.endswith(d.typed):
            source = (step.after[:len(step.after) - len(d.typed)], d)
        elif self._committed is not None and (step is self._committed[2] or len(s.history) > 1
                                              and s.history[-2] is self._committed[2]):
            # the commit's own change, or the one right after it (its 換行): not a later, unrelated one (a selection
            # replaced elsewhere brought an old sentence back as a draft; comparing texts matched by chance)
            source = self._committed[:2]
            if step is not self._committed[2]:   # the change after the commit: the draft as it was committed
                restore = self._committed[3:5]
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
            if rest and restore is not None and restore[0].anchor >= self.listener.kept_from():
                # as it was (the user's request, 2026-10-16): its open sentence is marked and decoded again with
                # what is said next; the speech taken back is not among its pieces
                snap, spans = restore
                self._draft = replace(snap, typed=rest, final=rest, placed=True, revived=False, restored=True)
                self._draft_start = snap.start
                self.listener.keep(snap.anchor)
                with self._restore_lock:
                    self._restored_spans = list(spans)
                self._marked = None
                log.info("undo: the draft as it was: %s | %s", snap.settled, rest[len(snap.settled):])
            elif rest:   # its audio is gone (or nothing was kept): a draft with its text fixed
                now = self.listener.now
                self._draft = _Draft(now, old.ctx, anchor=now, settled=rest, final=rest, typed=rest, placed=True,
                                     shown=now, revived=True)
                self._draft_start = now
                self.listener.keep(now)
                self._marked = None
                log.info("undo: a draft again: %s", rest)
        p = len(os.path.commonprefix([step.before, step.after]))
        self.book.undo(step.after[p:], step.before[p:], rest if self._draft is not None else "")

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
            self._pack_of = {w: p.name for p in packs.available() if p.id in self.cfg.packs for w in p.words}

    def _suggest_pack(self, word: str):
        """A word picked, typed or spelled that an unticked term pack lists: a notice suggests the pack, every time
        (the user's requests: 2026-10-13, once per pack; 2026-10-17, each time)."""
        word = word.strip()
        for pack in packs.available():
            if pack.id in self.cfg.packs:
                continue
            if any(w == word or (is_latin(word) and w.casefold() == word.casefold()) for w in pack.words):
                log.info("pack hint: %s in %s", word, pack.id)
                text = f"「{word}」收錄在詞包「{pack.name}」，勾選它，同類的詞會更容易辨識。"
                # also a row in 辨識紀錄, and both open the 詞包 section when clicked (the user's request,
                # 2026-10-21: the notice went away before it could be acted on)
                self.main.emit(lambda: self.book.hint(text, "packs"))
                self._toast = "packs"
                self.tray.showMessage("Art VoiceInput", f"「{word}」收錄在詞包「{pack.name}」。到設定的詞庫頁勾選它，"
                                      "同類的詞會更容易辨識。", self._tray.idle, 8000)
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
        self._toast = ""
        self.tray.showMessage("Art VoiceInput", text, self._tray.idle, 4000)

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
            if gen != self._pick_gen or not self._listening or self._menu is not None:
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
                # Chinese X-ASR wrote as English (How the -> 好的; 2026-10-21, the user's request): first next to
                # Chinese
                before, after = sel.before.rstrip(" "), sel.after.lstrip(" ")
                left, right = before[-1:] if _is_cjk(before[-1:]) else "", after[:1] if _is_cjk(after[:1]) else ""
                zh = syllables.chinese_words(text, left, right, picker_mod.WORDS[0] * picker_mod.WORDS[1])
                if zh and (left or right):
                    tabs.append(("中文", zh))
                if len(text.split()) == 1:
                    tabs.append(("近音字", sounds.near(text, known, picker_mod.WORDS[0] * picker_mod.WORDS[1])))
                tabs.append(("詞庫", sounds.alike(text, known, limit=10)))
                forms = self.memory.ordered_variants(text)
                weights = self.hotwords.weights_for(forms)
                forms.sort(key=lambda w: -weights.get(w, 0))   # stable: the rest keep their order
                tabs.append(("大小寫", forms))
                if zh and not (left or right):
                    tabs.append(("中文", zh))
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
                    # the user's words, also those the dictionary lacks (光暈), in the tab of how close they sound
                    for h in self.hotwords.items:
                        if h.word != text and h.word not in found:
                            rank = candidates.rank_of(text, h.word)
                            if rank is not None:
                                found[h.word] = (rank, 0)
                    first = []
                    weights = self.hotwords.weights_for(found)
                    order = lambda w: (-weights.get(w, 0), -found[w][1] < candidates.COMMON, found[w][1])
                    # rare words only by fuzzy sound (官癮, 灌嬰 next to 光陰: the user's complaint, 2026-10-16)
                    found = {w: v for w, v in found.items()
                             if v[0] < 2 or -v[1] >= _FUZZY_MIN or w in weights}
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
            if word == menu[1].text.strip():   # the word that is there now (the menu's first): kept as it is
                log.info("menu pick: kept %s", word)
                return
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
        before = sel.before
        if is_latin(text) and _is_cjk(word):   # 我 How the 意思 -> 我好的意思: the spaces to Chinese go too
            if sel.after[:1] == " " and _is_cjk(sel.after.lstrip(" ")[:1]) and not sel.text.endswith(" "):
                press_key(0x2E, 1)   # Delete: the space after
            if before.endswith(" ") and _is_cjk(before.rstrip(" ")[-1:]) and not sel.text.startswith(" "):
                press_key(0x25, len(word))   # Left past the word, Backspace, Right: the space before
                press_key(0x08, 1)
                press_key(0x27, len(word))
                before = before[:-1]
        line = sel.before + sel.text + sel.after
        start = len(sel.before) + lead
        self.memory.record(line, start, start + len(text), word)
        if self.cfg.save_recordings:
            recordings.note("pick", before=text, after=word, line=line)
        self.hotwords.picked(text, word)
        self._suggest_pack(word)
        self.settings.refresh_hotwords()
        self.session.replaced_selection(before, word, foreground())
        self.record.emit({"time": time.strftime("%H:%M:%S"), "kind": "選字", "main": f"{text} → {word}", "copy": word,
                          "steps": []})

    # --- settings / status ---
    def on_status(self, text: str):
        self._status_text = text
        log.info("status: %s", text)
        self.tray.setToolTip(f"Art VoiceInput — {text}")
        self.settings.set_status(text)

    def on_record(self, entry: dict):
        """Something done on its own (a 選字 pick, a selection deleted …): a card of one step."""
        main = entry.get("main") or ""
        self.book.single(entry.get("kind", "輸入"), main, esc(main) or "（無）", entry=entry)

    def _log_changed(self):
        if self.settings.isVisible():
            self.settings.set_log(self.book.sessions)

    def _clear_log(self):
        self.book.sessions.clear()
        self.settings.set_log(self.book.sessions)

    def _wizard_heard(self, audio):
        """The setup wizard's 你剛剛說: what was said, decoded on the worker (None while the model isn't ready)."""
        if self.recognizer is None:
            self.settings.wizard_said(None)
            return

        def run():
            try:
                text = format_text(self.recognizer.recognize(audio))
            except Exception:
                log.exception("wizard decode failed")
                text = ""
            log.info("wizard heard: %s", text)
            self.main.emit(lambda: self.settings.wizard_said(text))
        self.worker.submit(run)

    def _toast_clicked(self):
        if self._toast == "packs":
            self.open_settings()
            self.settings.show_packs()

    def open_settings(self, home: bool = False):
        """home: shown on its home also when it is already open on a page (launched again)."""
        if home and self.settings.isVisible():
            self.settings.show_home_now()
            if self.settings.isMinimized():
                self.settings.showNormal()
        self.settings.load_values()
        self.settings.set_log(self.book.sessions)
        self.settings.set_status(self._status_text)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def apply_settings(self):
        self.hotkeys.set_hotkey(self.cfg.hotkey)
        self._pack_stamp = None   # packs ticked may have changed (an import, 還原預設)
        self._load_packs()
        style = style_for(self.cfg.glow, self.cfg.glow_edits)
        if self.glow.style != style or self.glow.edges != edges_for(self.cfg.glow, self.cfg.glow_edits)                 or self.glow.motion != self.cfg.glow_motion:
            self.glow.set_style(style)
            self.glow.set_edges(edges_for(self.cfg.glow, self.cfg.glow_edits))
            self.glow.set_motion(self.cfg.glow_motion)
            if self._listening and self._listen_shown and self.cfg.glow:
                self.glow.show(self._pointer_screen())
        self.glow.set_lite(self.cfg.orb_lite)
        self.marks.set_color(self.cfg.highlight_color)
        self._apply_look()
        if self._paused and self._listening:   # the setup wizard opened (清空並重新設定)
            self._stop_listen()
        self._update_float()
        self._tray.set_lite(self.cfg.orb_lite)
        if self.cfg.tray_pinned != self._pinned:
            self._pin_tries = 0
            self._pin_tray()
        if not self.cfg.show_bubble or self._paused:
            self.bubble.hide()
        self._set_autostart()

    def _set_autostart(self):
        try:
            autostart.set_enabled(self.cfg.autostart, config.DEBUG)
        except Exception as e:
            log.exception("autostart failed")
            self.settings.set_status(f"開機啟動設定失敗：{e}")

    def restart(self):
        """清空並重新設定: a new Art VoiceInput is started the way this one was, and this one quits; the new one waits
        for the lock (RESTARTED)."""
        log.info("restart")
        self.settings.hide()
        args = [a for a in sys.argv[1:] if a != RESTARTED] + [RESTARTED]
        QProcess.startDetached(sys.executable, [os.path.abspath(sys.argv[0])] + args, os.getcwd())
        self.quit()

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
        self._tray.hide()
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


def _clipboard_text() -> str:
    return QGuiApplication.clipboard().text()


def _still_reads(buffer: str, ctx) -> bool:
    """Whether the line before the caret, read when 復原 was said (ctx.caret), ends with the buffer's last line."""
    caret = ctx.caret if ctx is not None else None
    return bool(caret) and caret[0].endswith(buffer.split("\n")[-1])


def _plain(text: str) -> str:
    """Clipboard text a paste types as it is, so 復原 can take it back with Backspace: one line, not long. "" for
    anything else (Claude Code turns a pasted block into [Pasted text], an editor may indent new lines)."""
    return text if text and "\n" not in text and "\r" not in text and len(text) <= 300 else ""


def _quick_ok(op, typed) -> bool:
    """A command a quick piece may run: any (2026-10-17, the user's request; it was only those typing text or a new
    line for a few hours). Quick pieces are the default since 2026-10-20 (the user's decision)."""
    return op is not None or bool(typed)


def _alike(raw: str, names: list) -> str:
    """The command a short decode sounds like (candidates.sounds_alike: no tones, the fuzzy pairs, any reading of
    a 多音字; the user's 驚嘆號 came out as 金嘆號, 換一行 as 換一航), "" when none or several. dev/cmdlab: on the
    user's 571 labeled text pieces no false trigger."""
    said = rules.normalize(to_traditional(raw))
    if not said or len(said) > 4:
        return ""
    hits = [n for n in names if candidates.sounds_alike(rules.normalize(n), said)]
    # spellings of one punctuation name (驚嘆號 / 驚歎號) are one command
    return hits[0] if len({edit.SYMBOLS.get(n, n) for n in hits}) == 1 else ""


def _held(vk: int) -> bool:
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _ours(hwnd: int) -> bool:
    """The window is Art VoiceInput's own (its settings): an Enter there sends nothing."""
    import ctypes
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


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
    revived: bool = False      # brought back by 復原 with its text fixed: what is said next goes on after a mark
    restored: bool = False     # brought back by 復原 as it was: its open sentence's pieces were handed back


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


def _sound(word: str) -> str:
    return reading_key(word)


def _bias(words: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Biasing words without a Chinese word another one starts with: with 剪貼 and 剪貼簿 both listed, X-ASR wrote 剪貼布
    (the short one is matched first and takes the boost; dev experiment 2026-10-11). English keeps both: dropping
    Gemini for Gemini CLI left Gemini unboosted (the user's recordings, 2026-10-13: 14/14 at 3 with both or alone,
    10/14 with Gemini CLI alone). The first of duplicates wins.
    A lowered word (negative score) sharing a start with another word is left out, so it never costs that one its
    boost or its place (城市 lowered next to 城市規劃). So is a lowered word sounding like a raised one that starts with
    the same character: with 自訂 +5 and 自定 at any score X-ASR kept writing 自定, as with no biasing (TTS,
    2026-10-21, the user's report; 自訂 alone or beside 自動 -3, and 程式 beside 城市 -3, were fine)."""
    keys = [w.casefold() for w, _ in words]
    raised = {(w[0], _sound(w)) for w, s in words if s > 0 and _CJK_CHAR.match(w)}
    words = [(w, s) for (w, s), k in zip(words, keys)
             if s >= 0 or not (any(o != k and (o.startswith(k) or k.startswith(o)) for o in keys)
                               or _CJK_CHAR.match(w) and (w[0], _sound(w)) in raised)]
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


def _is_cjk(text: str) -> bool:
    return bool(text) and bool(re.match(r"[㐀-䶿一-鿿]", text))


def _taskbar(hwnd: int) -> bool:
    """The taskbar, its tray overflow or the Start menu (where a click on the tray icon puts the foreground)."""
    cls = ctypes.create_unicode_buffer(64)
    ctypes.windll.user32.GetClassNameW(hwnd, cls, 64)
    return cls.value in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
                         "TopLevelWindowForOverflowXamlIsland", "Windows.UI.Core.CoreWindow")


def _paste_over(sel, text: str) -> bool:
    """Replace the selected text: a paste replaces a selection, except in a terminal."""
    if sel.term is not None and not _delete_selection(sel):
        return False
    paste_text(text)
    return True


RESTARTED = "--restarted"   # started by App.restart
# where a second launch asks the running Art VoiceInput to show its settings (a named pipe, one per user)
PIPE = f"ArtVoiceInput-{os.environ.get('USERNAME', '')}"


def _show_running():
    """Launched again by the user while running: the running one shows its settings window's home. It may take the
    foreground: this process has it now."""
    ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
    sock = QLocalSocket()
    sock.connectToServer(PIPE)
    if sock.waitForConnected(1000):
        sock.write(b"show")
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()


def main():
    paths.migrate_legacy()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(paths.LOG_PATH, encoding="utf-8"),
                  logging.StreamHandler()],
    )
    # an exception in a Qt event handler or slot is only printed, and pythonw prints nowhere: logged instead
    sys.excepthook = lambda kind, value, tb: log.error("uncaught", exc_info=(kind, value, tb))
    packs.install()
    config.DEBUG = "--debug" in sys.argv[1:]
    log.info("launched%s", " in debug mode" if config.DEBUG else "")
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(appicon.icon())   # the settings window on the taskbar and in Alt+Tab

    lock = QLockFile(str(paths.LOCK_PATH))
    if not lock.tryLock(10000 if RESTARTED in sys.argv else 100):   # restarted: the old one is still closing
        log.info("already running")
        if autostart.FLAG not in sys.argv:
            _show_running()
        return 0

    recover_mute()   # killed while listening last time: the speakers come back (not in App: tests build one)
    app = App(qapp)  # noqa: F841 (keep reference alive)
    server = QLocalServer()
    QLocalServer.removeServer(PIPE)

    def launched_again():
        server.nextPendingConnection().deleteLater()
        log.info("launched again: settings shown")
        app.open_settings(home=True)
    server.newConnection.connect(launched_again)
    server.listen(PIPE)
    # started by the user: the settings window's home (2026-10-21, the user's request); at login (autostart.FLAG)
    # only the tray icon, unless the setup wizard is not finished (first launch, 清空並重新設定 last time)
    if not app.cfg.setup_done or autostart.FLAG not in sys.argv:
        app.open_settings()
    return qapp.exec()
