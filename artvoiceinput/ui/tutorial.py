"""The tutorial (2026-10-24, the user's design; AGENTS.md "Tutorial"): over the settings window after the setup
wizard's 開始教學, or from 系統's 重看教學. A pretend Windows 11 desktop (`desk.Desk`) and a guide (`sprite`) that talks
in a card the user clicks on, like a visual novel, and waits where the user has to click something or read a
sentence aloud. It teaches the way of working of the setup in use (`wizard.mode_of`, 2026-10-24): 標準 a click into a
text box and the bubble, the floating button while listening, 送出 turning the microphone off; 簡單 the floating
button always there, on and off; 自動 a click into a text box turns it on, a click outside off; 簡約 nothing on screen,
the hotkey (右 Alt) or the tray icon. The rest is the same for all: the draft marked yellow, commands said alone, the
選字 menu.

It works without the app's core: its own microphone (`Ear`, a level probe like the wizard's) and its own matching
of what was said; only the decoding is handed out (`decode`: audio, the commands to try first, a callback; the app
lends its recognizer, `App._tutorial_decode`). Nothing said here is kept: no 辨識紀錄, 選字記憶 or 詞庫.

A reading less than 80% alike (characters or their sounds) is typed as heard and must be taken back with 復原
before going on; after 3 misses 跳過這步 shows. A click that isn't what the guide waits for gives what it waits for
(the red words) or 繼續 a little wiggle (`_nudge`).

念三句 (the user's design, 2026-10-24): a warm-up sentence; a second that settles the first (its yellow goes) and is
shown with a mishearing the tutorial plants (視力 as 勢力: the recognizer may well hear it right); a third that goes
on the same sentence, after which the planted 勢力 turns into 視力 with a red flash, as a pause's re-decode does. Each chapter starts from a known scene (`_scene`), so a tutorial
closed midway comes back at that chapter (`Config.tutorial_at`)."""
import re
import time
from difflib import SequenceMatcher
from html import escape

from pypinyin import lazy_pinyin
from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from .. import appicon, audio, keys
from . import theme
from .desk import BAR, AppWindow, Desk
from .kit import T, crossfade
from .sprite import SIDE, Card, Sprite
from .wizard import PRESETS, TextLink, mode_of

_SAME = object()             # click(): the ring round what `at` gives
TOP = 36                     # the strip over the desk: progress, 略過教學, the window's buttons
ALIKE = 0.8                  # a reading this alike passes
MISSES = 3                   # misses before 跳過這步 shows
OFF = {"float", "alt", "tray"}   # what turns the microphone off in the last chapter (and on, by the setup)
_ALT_VKS = (0x12, 0xA4, 0xA5)
_MASK = 0xE8                     # hotkey.py sends it before an Alt alone is let go (no menu): not another key
_COUNT = {1: "一", 2: "兩", 3: "三", 4: "四", 5: "五", 10: "十"}
# the commands taught; all are tried first on a short utterance, as the app does
COMMANDS = ["句號", "逗號", "問號", "換行", "下一行", "復原", "送出", "結束", "刪除"]
# 節日的節 names its chapter by its example ("詞的字" read abstract; the user's choice, 2026-10-24)
CHAPTERS = ["打開記事本", "開麥克風", "念三句", "定稿", "換行與復原", "選字", "選取重講", "節日的節", "送出", "關麥克風"]
FIRST = "今天天氣很好，我們去公園散步"
SECOND = "爺爺的視力很好"
MISHEARD = ("視力", "勢力")        # planted in SECOND until THIRD is said
THIRD = "連對面的招牌都看得清楚"
LINE1 = FIRST + "。" + SECOND + "，" + THIRD + "。"
CUT = "今天天氣很好，"              # selected and deleted in 選取重講: the rest still reads well
PLANTED = "請幫我定一張車票。"
# the 選字 menu for 定 (同音 / 不同聲調 / 模糊音, as candidates.ranked gives them, fixed so it never depends on the
# dictionary)
PICK_TABS = [("同音", ["訂", "錠", "碇", "腚"]), ("不同聲調", ["丁", "頂", "釘", "叮", "鼎", "盯", "町", "酊"]),
             ("模糊音", ["進", "近", "盡", "勁", "晉", "浸"])]
# the 選字 menu that opens by itself over 一張 in 選取重講 (candidates.ranked's, fixed): the user is told to let it be
RESELECT_TABS = [("同音", ["一章"]), ("不同聲調", ["議長", "一長", "一丈", "倚仗", "姨丈", "一掌", "依仗", "儀仗"]),
                 ("模糊音", ["一戰", "一站", "一盞", "驛站", "藝展", "翼展"])]
_PUNCT = re.compile(r"[\s，。、？！；：,.?!;:「」『』（）()…—-]")
_END = re.compile(r"[。？！.?!]+$")


def _bare(s: str) -> str:
    return _PUNCT.sub("", s)


def alike(said: str, want: str) -> float:
    """How alike two readings are, 0..1: characters, or their sounds (toneless pinyin) when that is closer."""
    a, b = _bare(said), _bare(want)
    if not a or not b:
        return 0.0
    chars = SequenceMatcher(None, a, b).ratio()
    sounds = SequenceMatcher(None, lazy_pinyin(a), lazy_pinyin(b)).ratio()
    return max(chars, sounds)


def described(said: str) -> str | None:
    """The character of <word>的<character> when the word holds it or one sounding like it (節日的節 -> 節), as
    edit.described but without the dictionary (the tutorial must not wait for it to load)."""
    m = re.fullmatch(r"(.{1,4})的(.)", _bare(said))
    if not m:
        return None
    word, ch = m.groups()
    if ch in word:
        return ch
    sound = lazy_pinyin(ch)[0]
    return next((c for c in reversed(word) if lazy_pinyin(c)[0] == sound), None)


def marked(said: str, want: str) -> str:
    """said as rich text, what differs from want in red and underlined."""
    out = []
    for op, i1, i2, _j1, _j2 in SequenceMatcher(None, said, want).get_opcodes():
        part = escape(said[i1:i2])
        if op in ("replace", "insert") and _bare(said[i1:i2]):
            out.append(f'<span style="color:{T("acct").name()}; text-decoration: underline;">{part}</span>')
        else:
            out.append(part)
    return "".join(out)


class Ear(QObject):
    """The microphone for the tutorial: speech by its level (like the wizard's 你剛剛說), a pause within it
    (`paused`, the audio so far: the draft is decoded again) and its end (`ended`, with whether it was short enough
    to be a command)."""
    level = Signal(float)
    paused = Signal(object)
    ended = Signal(object, bool)
    SPEECH = 0.3       # a level this high is speech
    PAUSE = 0.35       # quiet this long is a pause
    END = 0.9          # quiet this long ends what was said
    MAX = 12.0
    LEAD = 0.4         # audio kept before speech began
    SHORT = 1.5        # speech no longer than this may be a command
    KEEP = 20.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.probe = audio.LevelProbe(keep=self.KEEP)
        self._timer = QTimer(self, interval=50, timeout=self._tick)
        self._start = None
        self._loud = 0.0
        self._paused = False

    def start(self, device: str = ""):
        """Raises what sounddevice raises when the device can't be opened."""
        self._start = None
        self.probe.start(device)
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.probe.stop()
        self._start = None
        self.level.emit(0.0)

    @property
    def running(self) -> bool:
        return self.probe.running

    def _tick(self):
        level = self.probe.read()
        self.level.emit(level)
        now = time.monotonic()
        if level > self.SPEECH:
            if self._start is None:
                self._start = now
            self._loud = now
            self._paused = False
            if now - self._start < self.MAX:
                return
        elif self._start is None:
            return
        start = self._start
        quiet = now - self._loud
        if quiet >= self.END or now - start >= self.MAX:
            self._start = None
            if self._loud - start >= 0.15:
                self.ended.emit(self.probe.recent(now - start + self.LEAD), self._loud - start <= self.SHORT)
        elif quiet >= self.PAUSE and not self._paused:
            self._paused = True
            self.paused.emit(self.probe.recent(now - start + self.LEAD))


class Strip(QWidget):
    """The strip over the desk: the icon, 教學, the chapters as segments with the current one's name."""

    def __init__(self, parent):
        super().__init__(parent)
        self.chapter = 0

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), T("tile"))
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1), T("line"))
        p.save()
        p.translate(14, 9)
        appicon.paint(p, 18)
        p.restore()
        p.setPen(T("ink"))
        p.setFont(theme.font(13, 700))
        p.drawText(QRectF(40, 0, 40, self.height()), Qt.AlignLeft | Qt.AlignVCenter, "教學")
        x = 84
        p.setPen(Qt.NoPen)
        for i in range(len(CHAPTERS)):
            w = 26 if i == self.chapter else 14
            p.setBrush(T("acc") if i <= self.chapter else T("line"))
            if i < self.chapter:
                p.setBrush(T("acc", 0.45))
            p.drawRoundedRect(QRectF(x, self.height() / 2 - 2.5, w, 5), 2.5, 2.5)
            x += w + 4
        p.setPen(T("ink"))
        p.setFont(theme.font(12.5, 600, num=True))
        p.drawText(QRectF(x + 8, 0, 200, self.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{self.chapter + 1}／{len(CHAPTERS)}  {CHAPTERS[self.chapter]}")


class Tutorial(QWidget):
    """Over the whole settings window. `start(chapter)`; `finished` when done or skipped (True: done)."""
    finished = Signal(bool)
    chapter_started = Signal(int)

    def __init__(self, win, decode=None):
        super().__init__(win)
        self.win = win
        self.decode = decode          # (audio, commands, done(result)): result None (no recognizer yet),
        #                               ("cmd", name) or ("text", formatted text)
        self.setGeometry(win.rect())
        self.strip = Strip(self)
        self.strip.setGeometry(0, 0, self.width(), TOP)
        self.skip_link = TextLink("略過教學")
        self.skip_link.setParent(self)
        self.skip_link.move(self.width() - 92 - 16 - self.skip_link.width(), (TOP - self.skip_link.height()) // 2)
        self.skip_link.clicked.connect(self._ask_skip)
        self.desk = Desk(self, win.theme)
        self.desk.setGeometry(0, TOP, self.width(), self.height() - TOP)
        self.sprite = Sprite(self.desk)
        self.card = Card(self.desk)
        self.card.next_clicked.connect(lambda: self._event("next"))
        self.card.back_clicked.connect(self._back)
        self.card.skip_clicked.connect(lambda: self._event("skip"))
        d = self.desk
        d.clicked_app.connect(lambda kind: self._event(kind if kind == "tray" else "app:" + kind))
        d.stray.connect(lambda: self._event("stray"))
        d.notepad.edit.pressed.connect(lambda pt: self._pressed("notepad", pt))
        d.chat.edit.pressed.connect(lambda pt: self._pressed("chat", pt))
        d.notepad.edit.selected.connect(lambda: self._event("selected:notepad"))
        d.bubble.clicked.connect(lambda: self._event("bubble"))
        d.float.clicked.connect(lambda: self._event("float"))
        d.picker.picked.connect(lambda w: self._event("picked", w))
        d.picker.closed.connect(lambda: self._event("picker_closed"))
        self.ear = Ear(self)
        self.ear.level.connect(self.card.level.set)
        self.ear.paused.connect(self._heard_pause)
        self.ear.ended.connect(self._heard_end)
        self.mic = False
        self.mic_error = ""
        self.replay = False
        self.mode = mode_of(win.cfg)      # std / simple / auto / minimal (wizard.PRESETS)
        spec = win.cfg.hotkey if self.mode == "minimal" and win.cfg.hotkey else PRESETS["minimal"]["hotkey"]
        self.key_name = keys.hotkey_label(spec)
        self._key_vk = keys.parse_hotkey(spec)[2]
        self._key_alone = False           # the hotkey went down with nothing else pressed since
        self.setFocusPolicy(Qt.StrongFocus)
        self._gen = None
        self._want = None
        self._chapter = 0
        self._lines: list[str] = []   # what the guide said, for ‹ 上一句
        self._review = -1             # a past line shown (its index), -1 none
        self._hint = ""
        self._token = 0               # the utterance being decoded; older results are dropped
        self._done_token = -1         # its final result came back
        self._sp = None               # the speech step's state (_Speech)

    # --- running ---
    def start(self, chapter: int = 0, replay: bool = False):
        self.replay = replay
        self.setFocus()
        self._chapter = max(0, min(chapter, len(CHAPTERS) - 1))
        self._scene(self._chapter)
        self._lines, self._review = [], -1
        self._gen = self._run(self._chapter)
        self._resume(None)

    def _run(self, first: int):
        steps = [self.ch_open, self.ch_mic, self.ch_read, self.ch_commit, self.ch_undo, self.ch_pick,
                 self.ch_reselect, self.ch_described, self.ch_send, self.ch_off]
        for i in range(first, len(steps)):
            self._chapter = i
            self.strip.chapter = i
            self.strip.update()
            self.chapter_started.emit(i)
            yield from steps[i]()
        self._finish(True)

    def _resume(self, value):
        try:
            self._want = self._gen.send(value)
        except StopIteration:
            self._want = None
            return
        self._hint = ""
        if not self._want.get("keep"):
            self._render()

    def _event(self, name: str, data=None):
        """Something happened on the desk or the card; the step waiting for it goes on."""
        want = self._want
        if want is None:
            return
        if name == "next" and self._review >= 0:
            self._review = -1
            self._render()
            return
        if name in OFF and name not in want.get("what", ()):
            if self.mic:
                self._say_hint("關麥克風最後一章再練習，先照我說的做。")
            elif name != "float":
                self._nudge()
            return
        if want["kind"] == "speech" and want.get("sel") and name.startswith("text:") \
                and self._sp.box.selected_text not in want["sel"]:
            self._resume(("lost", None))   # a click dropped the selection: select it again
            return
        if want["kind"] == "speech" and name == "picked":
            self._say_hint("這次不用選字，直接念出來就好。")
            return
        if self._stray(name, want):
            self._nudge()
            return
        if want["kind"] == "next" and name == "next":
            self._resume(None)
        elif want["kind"] == "click" and name in want["what"]:
            check = want.get("check")
            ok = check(name, data) if check else True
            if ok is True:
                self._resume((name, data))
            elif ok:
                self._say_hint(ok)
        elif want["kind"] == "speech":
            if name == "skip":
                self._resume(("skip", None))
            elif name in want.get("what", ()):
                self._resume((name, None))
        elif want["kind"] == "click" and name == "skip" and want.get("skip"):
            self._resume(("skip", None))

    def _stray(self, name: str, want) -> bool:
        """A click on the desk that isn't what the guide waits for (a press in a text box while a selection there is
        awaited is the selection's start)."""
        if want.get("keep") or self._review >= 0 or name in want.get("what", ()):
            return False
        if name == "stray":
            return True
        if not name.startswith(("text:", "app:", "bubble")):
            return False
        if want["kind"] != "click":
            return True
        what = want["what"]
        return name not in what and "selected:" + name.partition(":")[2] not in what

    def _nudge(self):
        """The card says what to do: what it waits for (the red words) or 繼續 wiggles (the user's design,
        2026-10-24; the whole card and the guide shaking was too much)."""
        self.card.nudge()

    def keyPressEvent(self, e):
        if e.nativeVirtualKey() == _MASK:
            return
        self._key_alone = not e.isAutoRepeat() and self._is_hotkey(e)

    def keyReleaseEvent(self, e):
        if e.nativeVirtualKey() == _MASK:
            return
        if self._key_alone and not e.isAutoRepeat() and self._is_hotkey(e):
            self._event("alt")
        self._key_alone = False

    def _is_hotkey(self, e) -> bool:
        """The 簡約 setup's key (a modifier alone, as the app takes it; 右 Alt by default)."""
        if self._key_vk in _ALT_VKS:
            return e.key() in (Qt.Key_Alt, Qt.Key_AltGr)
        return self._key_vk is not None and e.nativeVirtualKey() == self._key_vk

    def _say_hint(self, text: str):
        self._hint = text
        self._render()
        self.sprite.shake()

    # --- the scene a chapter starts from (resuming there) ---
    def _scene(self, i: int):
        d = self.desk
        e, c = d.notepad.edit, d.chat.edit
        if i >= 1:
            d.notepad.show()
            d.running.add("notepad")
        rest = LINE1[len(CUT):]
        texts = {2: "", 3: LINE1[:-1], 4: LINE1, 5: LINE1 + "\n", 6: LINE1 + "\n請幫我訂一張車票。",
                 7: rest + "\n請幫我訂兩張車票。", 8: rest + "\n請幫我訂兩張車票。\n節",
                 9: rest + "\n請幫我訂兩張車票。\n節"}
        if i in texts:
            e.set_text(texts[i])
            if i == 3:
                e.draft = (len(FIRST) + 1, len(e.text))
        e.set_focus(2 <= i < 8)
        if i >= 9:
            d.chat.show()
            d.chat.raise_()
            d.running.add("chat")
            d.chat.say(True, "我等一下就到。")
            d.chat.say(False, "好，等你喔！")
        if self.mode == "simple" and not d.float.isVisible():
            d.float.fade_in(220)
        self.set_mic(2 <= i < 9 or (i == 9 and self.mode != "std"))
        self._place(None)

    # --- the microphone, the glow, the floating button ---
    def set_mic(self, on: bool):
        d = self.desk
        if on == self.mic:
            return
        self.mic = on
        d.listening = on
        if self.mode != "minimal":   # 簡約: no glow, the tray icon alone
            d.glow.turn(on)
        if on:
            if d.bubble.isVisible():
                d.bubble.burst()
            if self.mode in ("std", "simple"):
                d.float.set_active(True)
                if not d.float.isVisible():
                    d.float.fade_in(220)
                d.float.raise_()
            self.mic_error = ""
            try:
                self.ear.start(self.win.cfg.mic)
            except Exception:
                self.ear.stop()
                self.mic_error = "麥克風打不開"
        else:
            self.ear.stop()
            if self.mode == "std":
                d.float.fade_out(220)
            d.float.set_active(False)
        self._token += 1
        d.update()

    def show_bubble(self, pt: QPoint):
        b = self.desk.bubble
        b.move(pt.x() + 10 - b.margin, pt.y() - b.bsize // 2 - b.margin)
        if b.isVisible():
            b.hide()
        b.fade_in(160)
        b.raise_()

    def _pressed(self, which: str, pt: QPoint):
        """A click in a text box: the focus there, the 選字 menu closed, the bubble by it when not listening."""
        d = self.desk
        box = d.notepad.edit if which == "notepad" else d.chat.edit
        other = d.chat.edit if which == "notepad" else d.notepad.edit
        other.set_focus(False)
        box.set_focus(True)
        win = d.notepad if which == "notepad" else d.chat
        win.raise_()
        d.glow.raise_()
        d.float.raise_()
        d.ring.raise_()
        self.sprite.raise_()
        self.card.raise_()
        d.picker.dismiss()
        if not self.mic and self._chapter >= 1:
            if self.mode == "std":
                QTimer.singleShot(120, lambda: self.show_bubble(pt))
            elif self.mode == "auto":   # 自動: a click into a text box turns listening on
                self.set_mic(True)
        self._event("text:" + which, pt)

    def mousePressEvent(self, e):
        self.desk.picker.dismiss()
        self.setFocus()

    # --- the guide ---
    def _render(self):
        want = self._want
        if want is None:
            return
        card = self.card
        if self._review >= 0:
            card.show_line(self._lines[self._review], back=self._review > 0, next_text="回到現在")
        else:
            text = want.get("text", "")
            status, listening, skip, alt = want.get("status", ""), False, False, ""
            quote, heard = want.get("quote", ""), ""
            if want["kind"] == "speech":
                sp = self._sp
                listening = True
                status = "正在聽…"
                alt = want.get("alt", "")
                if sp.miss:
                    heard = f'<span style="color:{T("muted").name()}">你剛剛說的是：</span><br>' \
                            + marked(sp.heard, want.get("quote") or "")
                    text = sp.miss_text
                    status, listening, alt = "說「復原」", False, ""
                if self.mic_error:
                    status, listening, alt = self.mic_error, False, ""
                elif sp.no_model:
                    status, listening, alt = "辨識模型還在準備", False, ""
                skip = sp.misses >= MISSES or bool(self.mic_error) or sp.no_model
            elif want["kind"] == "click":
                skip = bool(want.get("skip"))
            if self._hint:
                text = self._hint
            card.show_line(text, quote=quote, heard=heard, status=status, listening=listening, skip=skip,
                           back=bool(self._lines) and len(self._lines) > 1,
                           next_text=want.get("next_text", "繼續"), alt=alt)
            self.sprite.set_face(want.get("face") or ("listen" if want["kind"] == "speech" else "idle"))
        self._place(want.get("at"), want.get("ring"), want.get("avoid"))

    def _back(self):
        if not self._lines:
            return
        self._review = len(self._lines) - 2 if self._review < 0 else max(0, self._review - 1)
        self._render()

    def _place(self, at, ring=None, avoid=None):
        """The guide beside `at` (a QRect on the desk, or a function giving one), its card beside it, neither over
        it nor over `avoid` (the text the user reads; with no `at`, the open windows); `ring` outlined."""
        d = self.desk
        at = at() if callable(at) else at
        ring = ring() if callable(ring) else ring
        avoid = avoid() if callable(avoid) else avoid
        read = avoid
        if isinstance(ring, tuple):
            d.ring.point_at(ring[0], round_=ring[1])
        else:
            d.ring.point_at(ring)
        self.card.raise_()
        self.sprite.raise_()
        area = QRect(0, 0, d.width(), d.height() - BAR)
        cw, ch = self.card.width(), self.card.height()
        avoid = [r for r in (at, ring[0] if isinstance(ring, tuple) else ring, avoid) if r is not None]
        if at is None:
            s = AppWindow.SHADOW
            avoid += [w.geometry().adjusted(s, s, -s, -s) for w in (d.notepad, d.chat) if w.isVisible()]
        if d.bubble.isVisible() and not d.bubble.leaving:
            avoid.append(d.bubble.geometry().adjusted(d.bubble.margin, d.bubble.margin, -d.bubble.margin,
                                                      -d.bubble.margin))
        if d.picker.isVisible():
            avoid.append(d.picker.geometry())
        if at is None:
            spots = [QPoint(24, area.height() - SIDE - 24),
                     QPoint(area.width() - SIDE - cw - 40, area.height() - SIDE - 30),
                     QPoint(area.width() - SIDE - cw - 40, 24)]
        else:
            t = at.adjusted(-8, -8, 8, 8)
            cy = t.center().y() - SIDE // 2
            spots = [QPoint(t.right() + 4, cy), QPoint(t.left() - SIDE - 4, cy),
                     QPoint(t.left(), t.bottom() + 4), QPoint(t.left(), t.top() - SIDE - 4),
                     QPoint(t.right() - SIDE - cw, t.bottom() + 4), QPoint(t.right() - SIDE - cw, t.top() - SIDE - 4)]
            if read is not None:   # just under the text being read, near the target, before the far corner
                spots += [QPoint(t.left(), read.bottom() + 8), QPoint(t.right() - SIDE - cw, read.bottom() + 8)]
        best = None
        for s in spots:
            for card_right in (True, False):
                sx = min(max(s.x(), 0), area.width() - SIDE)
                sy = min(max(s.y(), 0), area.height() - SIDE)
                cx = sx + SIDE - 6 if card_right else sx - cw + 6
                cyy = min(max(sy - 4, 4), area.height() - ch - 4)
                if cx < 4 or cx + cw > area.width() - 4:
                    continue
                box = QRect(min(sx, cx), min(sy, cyy), SIDE + cw, max(SIDE, ch))
                if any(box.intersects(r) for r in avoid):
                    continue
                best = (sx, sy, cx, cyy, card_right)
                break
            if best:
                break
        if best is None:   # nowhere clear: the bottom right
            sx, sy = area.width() - SIDE - cw - 16, area.height() - SIDE - 10
            best = (sx, sy, sx + SIDE - 6, min(sy - 4, area.height() - ch - 4), True)
        sx, sy, cx, cyy, card_right = best
        self.sprite.go(QPoint(sx, sy))
        self.card.side = "left" if card_right else "right"
        self.card.tail_y = sy + SIDE // 2 - 6 - cyy
        self.card.move(cx, cyy)
        self.card.show()
        self.card.update()
        self.sprite.show()
        self.sprite.look_at(at.center() if at is not None else None, QPoint(sx, sy))

    # --- what a chapter waits for ---
    def say(self, text: str, face: str = "idle", at=None, ring=None, next_text: str = "繼續", avoid=None):
        self._lines.append(text)
        return (yield dict(kind="next", text=text, face=face, at=at, ring=ring, next_text=next_text, avoid=avoid))

    def click(self, what, text: str, at=None, ring=_SAME, check=None, status: str = "", face: str = "idle",
              avoid=None):
        self._lines.append(text)
        return (yield dict(kind="click", what=set(what) if not isinstance(what, str) else {what}, text=text, at=at,
                           ring=at if ring is _SAME else ring, check=check, status=status, face=face, avoid=avoid))

    def wait(self, ms: int):
        """A moment for an animation; the guide stays as it is."""
        QTimer.singleShot(ms, lambda: self._event("timer"))
        return (yield dict(kind="click", what={"timer"}, keep=True))

    def listen(self, box, text: str, target: str = "", commands=(), char: str = "", what=(), ring=None,
               quote: str | None = None, join: bool = False, plant=None, alt: str = "", sel=()):
        """Speech into box: a reading of target, a command of commands, or a described character (char). join: it
        goes on the draft before it (one sentence, the draft's closing mark becomes ，); plant: (heard right, shown)
        swapped in what is typed; what: clicks or keys that also do (shown after 正在聽… as alt: "float" the
        button drawn, else words); sel: the selections it needs (a click losing it returns ("lost", None), what
        was typed taken back). Returns ("ok", text), ("cmd", name), (one of what, None) or ("skip", None)."""
        self._lines.append(text)
        self._sp = _Speech(box, target, set(commands), char, join=join, plant=plant)
        return (yield dict(kind="speech", text=text, quote=target if quote is None else quote,
                           at=lambda: _box_rect(self.desk, box), ring=ring, what=set(what), alt=alt,
                           sel=tuple(sel)))

    # --- what was said ---
    def _heard_pause(self, audio_):
        sp, want = self._sp, self._want
        if not want or want["kind"] != "speech" or sp.miss or not sp.target or self.decode is None:
            return   # a described character shows only itself, never the words said for it (as the app does)
        token = self._token
        self.decode(audio_, [], lambda result: self._partial(token, result))

    def _partial(self, token, result):
        if token != self._token or token == self._done_token or not result or result[0] != "text":
            return
        sp, want = self._sp, self._want
        if want and want["kind"] == "speech" and not sp.miss and result[1]:
            self.desk.picker.dismiss()
            sp.type(result[1])

    def _heard_end(self, audio_, short: bool):
        want = self._want
        if not want or want["kind"] != "speech":
            return
        token = self._token
        if self.decode is None:
            self._sp.no_model = True
            self._render()
            return
        self.decode(audio_, COMMANDS if short else [], lambda result: self._final(token, result))
        self._token += 1

    def _final(self, token, result):
        if token + 1 != self._token:
            return
        self._done_token = token
        self.hear(result)

    def hear(self, result):
        """What was said (decoded): None while there is no recognizer, ("cmd", name) or ("text", text). Also how
        dev/tutorial_check.py speaks."""
        want, sp = self._want, self._sp
        if not want or want["kind"] != "speech":
            return
        self._hint = ""
        if result is None:
            sp.no_model = True
            self._render()
            return
        sp.no_model = False
        kind, said = result
        self.desk.picker.dismiss()
        if kind == "cmd":
            if said == "復原" and (sp.miss or sp.typed):
                if "復原" in sp.commands and not sp.miss:
                    self._resume(("cmd", said))
                    return
                sp.undo()
                self._hint = "收回來了，再試一次。"
                self._render()
                self.sprite.bounce()
                return
            if sp.miss:
                self._say_hint("先說「復原」，把剛剛那句收回來。")
            elif said in sp.commands:
                self._resume(("cmd", said))
            else:
                self._say_hint(f"這裡先不用說「{said}」。" + want["text"])
            return
        if not _bare(said):
            return
        if sp.miss:
            self._say_hint("先說「復原」，把剛剛那句收回來。")
            return
        if sp.char:
            ch = described(said)
            if ch == sp.char:
                sp.settle(ch)
                self._resume(("ok", ch))
                return
            sp.type(said)
            self._miss()
            return
        sp.type(said)
        if sp.target:
            draft = sp.draft_text()
            if alike(draft, sp.target) >= ALIKE:
                self._resume(("ok", draft))
                return
            done = _bare(draft)
            want_ = _bare(sp.target)
            if len(done) < 0.6 * len(want_) and alike(draft, sp.target[:len(draft)]) >= ALIKE:
                sp.go_on()   # half way: the rest comes next
                return
        self._miss()

    def _miss(self):
        sp = self._sp
        sp.miss = True
        sp.misses += 1
        sp.heard = sp.draft_text()
        sp.miss_text = "咦，好像不太一樣。說「復原」，把這句收回來。" if sp.misses < MISSES else \
            "還是不太一樣。說「復原」再試一次，或先跳過這步。"
        self._render()
        self.sprite.set_face("oops")
        self.sprite.shake()

    # --- chapters ---
    def ch_open(self):
        d = self.desk
        yield from self.say("嗨，我是阿特！接下來大約三分鐘，我陪你練習用說的打字。", "happy")
        yield from self.say("這是練習用的桌面，怎麼點、怎麼說，都不會動到你的電腦。")
        yield from self.click("app:notepad", "先打開記事本：點一下工作列上的記事本。",
                              at=lambda: d.taskbar_rect("notepad"), status="等你點記事本")
        d.open_app(d.notepad, "notepad")

    def ch_mic(self):
        d = self.desk
        e = d.notepad.edit
        mode, key = self.mode, self.key_name
        yield from self.click("text:notepad", "點一下記事本的空白處，就像平常要打字那樣。",
                              at=lambda: d.notepad.geometry(), ring=lambda: _box_rect(d, e), status="等你點記事本")
        if mode == "std":
            yield from self.wait(200)
            yield from self.click("bubble", "旁邊冒出一顆小氣泡。點它，麥克風就會打開。",
                                  at=lambda: _orb_rect(d.bubble), ring=lambda: (_orb_rect(d.bubble), True),
                                  status="等你點氣泡", avoid=e.used_rect)
        elif mode == "simple":
            yield from self.click("float", "右邊這顆是浮動按鈕，一直都在。點它，麥克風就會打開。",
                                  at=lambda: _orb_rect(d.float), ring=lambda: (_orb_rect(d.float), True),
                                  status="等你點浮動按鈕")
        elif mode == "minimal":
            yield from self.click(("alt", "tray"), f"按一下鍵盤上的{key}，或點工作列上的阿特圖示，麥克風就會打開。",
                                  at=lambda: d.tray_rect(), ring=lambda: d.tray_rect().adjusted(-3, -3, 3, 3),
                                  status=f"等你按{key} 或點圖示")
        self.set_mic(True)   # 自動: on already, by the click
        yield from self.wait(260)
        self.sprite.bounce()
        if mode == "std":
            yield from self.say("麥克風打開了！畫面邊緣亮起紅光，右邊這顆是浮動按鈕。", "happy",
                                at=lambda: _orb_rect(d.float))
            yield from self.say("在其他程式裡也一樣：點進輸入框，再點小氣泡，就能開始說話。")
        elif mode == "simple":
            yield from self.say("麥克風打開了！畫面邊緣亮起紅光，浮動按鈕縮小、轉得更快，表示我正在聽。", "happy",
                                at=lambda: _orb_rect(d.float))
            yield from self.say("在其他程式裡也一樣：點進輸入框，再點浮動按鈕，就能開始說話。")
        elif mode == "auto":
            yield from self.say("麥克風自己打開了！點進輸入框就會開始聽，畫面邊緣的紅光表示我正在聽。", "happy")
            yield from self.say("在其他程式裡也一樣：點進輸入框，就能直接說話。")
        else:
            yield from self.say("麥克風打開了！簡約模式畫面上什麼都不會多，只有工作列的阿特圖示會轉圈。", "happy",
                                at=lambda: d.tray_rect())
            yield from self.say(f"在其他程式裡也一樣：按{key}，或點右下角的阿特圖示，就能開始說話。")

    def ch_read(self):
        e = self.desk.notepad.edit
        result = yield from self.listen(e, "先暖暖身：照著念這句話，念完停一下。", target=FIRST)
        if result[0] == "skip":
            self._sp.settle(FIRST, draft=True)
        a, b = e.draft or (0, len(e.text))
        e.replace(a, b, _END.sub("", e.text[a:b]) + "。", draft=True)   # the recognizer's 。 ends the draft
        self.sprite.bounce()
        yield from self.say("念好了！黃底的字叫「未定稿」，代表我還在聽，隨時可能修正。", "proud",
                            at=lambda: e.char_rect(*(e.draft or (0, 1))), avoid=e.used_rect)
        result = yield from self.listen(e, "接著念第二句。念的時候看看上一句：黃底會消失，它定稿了。", target=SECOND,
                                        plant=MISHEARD)
        sp = self._sp
        shown = SECOND.replace(*MISHEARD)
        if result[0] == "skip":
            sp.settle(shown + "。", draft=True)
        else:   # as said, with the planted mishearing
            e.replace(sp.own, sp.end, shown + "。", draft=True)

        def wrong():
            at = e.text.rfind(MISHEARD[1])
            return e.char_rect(at, at + len(MISHEARD[1]))
        yield from self.say("上一句定稿了。咦，「視力」被聽成了「勢力」？先別急著改，繼續念下一句。", "think", at=wrong,
                            avoid=e.used_rect)
        result = yield from self.listen(e, "念第三句：", target=THIRD, join=True)
        if result[0] == "skip":
            self._sp.settle(THIRD, draft=True)
        yield from self.wait(450)
        at = e.text.rfind(MISHEARD[1])
        if at >= 0:
            draft = e.draft
            e.replace(at, at + len(MISHEARD[1]), MISHEARD[0])
            e.caret = e.anchor = len(e.text)
            e.draft = draft
            e.flash_span(at, at + len(MISHEARD[0]))
        self.sprite.bounce()

        def fixed():
            i = e.text.rfind(MISHEARD[0])
            return e.char_rect(i, i + len(MISHEARD[0]))
        yield from self.say("看！聽到後面的「看得清楚」，我把整句再聽一次，「勢力」就自己改成「視力」了。", "proud",
                            at=fixed, avoid=e.used_rect)
        yield from self.say("所以一句話還沒說完時，錯字先別急著改：說完、停頓一下，常常就對了。")

    def ch_commit(self):
        e = self.desk.notepad.edit
        result = yield from self.listen(e, "說「句號」，這句就定稿了：黃底消失，句尾加上「。」", commands=["句號"])
        a, b = e.draft or (len(e.text), len(e.text))
        body = _END.sub("", e.text[a:b])
        e.replace(a, b, body + "。")
        e.commit()
        self.sprite.bounce()
        yield from self.say("定稿了！「逗號」「問號」也一樣，說出名字就會打出來。", "happy")
        yield from self.say("不說也沒關係：說下一個指令，或關掉麥克風時，句尾會自動補上「。」")

    def ch_undo(self):
        e = self.desk.notepad.edit
        result = yield from self.listen(e, "說「下一行」，換到下一行。", commands=["下一行", "換行"])
        e.insert("\n")
        before = (e.text, e.caret)
        result = yield from self.listen(e, "再念一句：", target="記得帶雨傘")
        if result[0] == "skip":
            self._sp.settle("記得帶雨傘", draft=True)
        result = yield from self.listen(e, "想收回剛剛那句？說「復原」，它就會不見。", commands=["復原"])
        e.set_text(*before)
        self.sprite.bounce()
        yield from self.say("收回來了！每說一次「復原」，就收回最後一個動作。", "happy")

    def ch_pick(self):
        d = self.desk
        e = d.notepad.edit
        yield from self.say("我偷偷打了一句話，裡面有一個字錯了，你找找看。", "think", at=lambda: d.notepad.geometry())
        if not e.text.endswith("\n"):
            e.insert("\n")
        for ch in PLANTED:
            e.insert(ch)
            d.notepad.update()
            yield from self.wait(70)
        at = len(e.text) - len(PLANTED) + PLANTED.index("定")

        def chosen(_name, _data):
            return True if e.selected_text == "定" else "只要選「定」這一個字就好。"
        while True:
            yield from self.click("selected:notepad", "「定」應該是「訂」。用滑鼠在「定」上拖曳選取，或在它上面點兩下。",
                                  at=lambda: e.char_rect(at, at + 1), check=chosen, status="等你選「定」",
                                  avoid=e.used_rect)
            d.picker.open_under(e.char_rect(at, at + 1), "定", PICK_TABS)
            name, word = yield from self.click(("picked", "picker_closed"), "選字選單打開了。同音的字在第一頁，點「訂」。",
                                               at=lambda: d.picker.geometry(), ring=None, status="等你點「訂」")
            if name == "picked":
                e.replace(at, at + 1, word)
                if word == "訂":
                    break
                yield from self.say(f"換成「{word}」了，但不是這個喔。再選一次，挑「訂」。", "oops",
                                    at=lambda: e.char_rect(at, at + 1), avoid=e.used_rect)
        self.sprite.bounce()
        yield from self.say("對了！選字選單會照讀音分頁：同音、不同聲調、模糊音。", "proud",
                            at=lambda: e.char_rect(at, at + 1), avoid=e.used_rect)
        yield from self.say("你選過的字，我會記住；之後同一個地方聽到同樣的音，就直接打對。")

    def ch_reselect(self):
        d = self.desk
        e = d.notepad.edit
        at = e.text.rfind("一張")

        def chosen(_name, _data):
            return True if e.selected_text == "一張" else "選「一張」這兩個字就好。"
        ask = "也可以整段換掉：用滑鼠選取「一張」。"
        while True:
            yield from self.click("selected:notepad", ask, at=lambda: e.char_rect(at, at + 2), check=chosen,
                                  status="等你選「一張」", avoid=e.used_rect)
            # the app opens the 選字 menu by itself over a selection this short: here too, let be
            d.picker.open_under(e.char_rect(at, at + 2), "一張", RESELECT_TABS)
            result = yield from self.listen(e, "選字選單也跳出來了，這次別理它，直接說「兩張」：", target="兩張",
                                            sel=("一張",))
            if result[0] != "lost":
                break
            self._lost()
            ask = "選取不見了，再選一次「一張」。"
        if result[0] == "skip":
            self._sp.settle("兩張")
        e.commit()
        self.sprite.bounce()
        yield from self.say("換好了！選取一段字再說話，就會整段取代。", "happy")

        def cut_chosen(_name, _data):
            return True if e.selected_text in (CUT, CUT[:-1]) else "選第一行開頭的「今天天氣很好，」就好。"
        ask = "不要的字也能用說的刪掉：選取第一行開頭的「今天天氣很好，」。"
        while True:
            yield from self.click("selected:notepad", ask, at=lambda: e.char_rect(0, len(CUT)), check=cut_chosen,
                                  status="等你選取", avoid=e.used_rect)
            result = yield from self.listen(e, "選好了，說「刪除」。", commands=["刪除"], sel=(CUT, CUT[:-1]))
            if result[0] != "lost":
                break
            self._lost()
            ask = "選取不見了，再選一次「今天天氣很好，」。"
        a = e.text.find(CUT)    # with its comma, selected or not, so the line reads on
        e.replace(a, a + len(CUT), "")
        self.sprite.bounce()
        yield from self.say("刪掉了！剩下的句子一樣通順。", "happy", at=lambda: e.char_rect(0, 1), avoid=e.used_rect)

    def _lost(self):
        """The selection went before it was spoken over: what was typed for it taken back, the guide a little
        sorry."""
        sp = self._sp
        if sp.typed:
            box = sp.box
            caret = box.caret
            sp.undo()
            box.caret = box.anchor = min(caret, len(box.text))
            box.update()
        self.sprite.set_face("oops")

    def ch_described(self):
        e = self.desk.notepad.edit
        e.set_focus(True)
        e.replace(len(e.text), len(e.text), "\n")
        yield from self.say("有些字單獨念，很難聽出是哪一個，像是名字裡的字。", "think")
        result = yield from self.listen(e, "這時候這樣說：先說一個詞，再說要的是哪個字。念：", char="節", quote="節日的節")
        if result[0] == "skip":
            self._sp.settle("節")
        self.sprite.bounce()
        yield from self.say("只打出了「節」這一個字！說「節日的節」「顯示的示」，就能指定是哪個字。", "proud")

    def ch_send(self):
        d = self.desk
        yield from self.say("最後來傳個訊息。我幫你打開聊天軟體。")
        d.notepad.edit.set_focus(False)
        d.open_app(d.chat, "chat")
        d.chat.edit.set_focus(True)
        d.float.raise_()
        yield from self.wait(300)
        c = d.chat.edit
        result = yield from self.listen(c, "小美在等你。念：", target="我等一下就到")
        if result[0] == "skip":
            self._sp.settle("我等一下就到", draft=True)
        result = yield from self.listen(c, "說「送出」，訊息就傳出去了。", commands=["送出"])
        text = _END.sub("", c.text) + "。"
        c.set_text("")
        d.chat.say(True, text)
        if self.mode == "std":   # 送出 turns it off in 標準 alone (stop_on_enter)
            self.set_mic(False)
        yield from self.wait(900)
        d.chat.say(False, "好，等你喔！")
        self.sprite.bounce()
        yield from self.say("傳出去了！送出之後，麥克風也自動關掉了。" if self.mode == "std" else
                            "傳出去了！送出之後麥克風還開著，可以接著說。", "proud", at=lambda: d.chat.geometry())

    def ch_off(self):
        d = self.desk
        c = d.chat.edit
        mode, key = self.mode, self.key_name
        if not self.mic:   # 標準: 送出 turned it off
            yield from self.click("text:chat", "要再說話：點一下輸入框，再點小氣泡。", at=lambda: _box_rect(d, c),
                                  status="等你點輸入框")
            yield from self.wait(200)
            yield from self.click("bubble", "點小氣泡。", at=lambda: _orb_rect(d.bubble),
                                  ring=lambda: (_orb_rect(d.bubble), True), status="等你點氣泡",
                                  avoid=c.used_rect)
            self.set_mic(True)
            yield from self.wait(260)
        if mode == "std":
            yield from self.listen(c, "關麥克風有兩種方法：說「結束」，或點右邊的浮動按鈕。選一種試試。",
                                   commands=["結束"], what=("float",), ring=lambda: (_orb_rect(d.float), True),
                                   alt="float")
        elif mode == "simple":
            yield from self.listen(c, "關麥克風有兩種方法：說「結束」，或再點一次浮動按鈕。選一種試試。",
                                   commands=["結束"], what=("float",), ring=lambda: (_orb_rect(d.float), True),
                                   alt="float")
        elif mode == "auto":
            yield from self.listen(c, "關麥克風有兩種方法：說「結束」，或點一下輸入框外面，像是桌面。選一種試試。",
                                   commands=["結束"], what=("stray",), alt="點外面")
        else:
            yield from self.listen(c, f"關麥克風有兩種方法：說「結束」，或再按一次{key}（點工作列的阿特圖示也行）。"
                                   "選一種試試。", commands=["結束"], what=("alt", "tray"),
                                   ring=lambda: d.tray_rect().adjusted(-3, -3, 3, 3), alt=f"按{key}、點圖示")
        self.set_mic(False)
        if mode == "auto":
            c.set_focus(False)
        self.sprite.bounce()
        minutes = PRESETS[mode]["auto_off_minutes"]
        if mode == "auto":
            yield from self.say("關好了！離開輸入框，麥克風就會自己關掉；點回輸入框，又會打開。", "happy")
        else:
            yield from self.say(f"關好了！另外，{_COUNT.get(minutes, minutes)}分鐘沒說話，麥克風也會自己關掉。",
                                "happy")
        yield from self.say("能說的指令還有很多，像「全選」「複製」「貼上」「空白」「括號」；全部都在設定的"
                            "「語音指令」頁，也可以自己新增。")
        how = {"std": "點進輸入框、點小氣泡，就能開始說", "simple": "點進輸入框、點浮動按鈕，就能開始說",
               "auto": "點進輸入框，就能直接說", "minimal": f"按{key}或點右下角的阿特圖示，就能開始說"}[mode]
        yield from self.say(f"都學會了！之後在任何程式裡，{how}。", "proud", next_text="開始使用")

    # --- ending ---
    def _ask_skip(self):
        from .sheet import Sheet
        sheet = Sheet(self.win, "略過教學？", "之後可以在「系統」頁的「重看教學」再看一次。", "略過教學")
        sheet.accepted.connect(lambda: self._finish(False))
        sheet.open()

    def _finish(self, done: bool):
        self.stop()
        crossfade(self.win, 320)
        self.hide()
        self.finished.emit(done)

    def stop(self):
        """Hidden or ended: the microphone isn't kept open unseen."""
        self.ear.stop()
        self.mic = False

    def hideEvent(self, e):
        self.ear.stop()
        super().hideEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        if self.mic and not self.ear.running:
            try:
                self.ear.start(self.win.cfg.mic)
            except Exception:
                self.mic_error = "麥克風打不開"


class _Speech:
    """A step taking speech into a text box: where what is said goes (the draft, from `start`), what came before
    (for 復原), the misses."""

    def __init__(self, box, target: str, commands: set, char: str, join: bool = False, plant=None):
        self.box, self.target, self.commands, self.char = box, target, commands, char
        self.plant = plant               # (heard right, shown): swapped in what is typed
        self.before = (box.text, box.anchor, box.caret, box.draft)   # 復原 puts this back
        # join: the draft before goes on with this speech, one sentence (its closing mark becomes ， when this is
        # typed, as at a pause in the app)
        self.join = box.draft[0] if join and box.draft else None
        self.misses = 0
        self.heard = ""
        self.miss_text = ""
        self.no_model = False
        self._reset()

    def _reset(self):
        a, b = self.box.selection
        self.start = self.join if self.join is not None else a   # the draft: box.text[start:end]
        self.own = self.utt = a          # this step's speech: box.text[own:end]; the utterance said from utt
        self.end = b                     # (a selection is replaced)
        self.joined = False
        self.typed = False
        self.miss = False

    def _join(self):
        if self.join is None or self.joined:
            return
        box = self.box
        head = box.text[self.start:self.own]
        new = _END.sub("", head) + "，"
        box.replace(self.start, self.own, new)
        moved = len(new) - len(head)
        self.own += moved
        self.utt += moved
        self.end += moved
        self.joined = True

    def type(self, text: str):
        """The utterance being said reads text now (replacing its last decode); with text after it on the line
        (a selection replaced mid-sentence) without the recognizer's closing mark, as the app does."""
        box = self.box
        if self.plant:
            text = text.replace(*self.plant)
        self._join()
        after = box.text[self.end:self.end + 1]
        if after and after != "\n":
            text = re.sub(r"[。，、！？；：.,!?;:]+$", "", text)
        box.replace(self.utt, self.end, text, draft=True)
        self.end = self.utt + len(text)
        box.draft = (self.start, self.end)
        box.update()
        self.typed = True

    def go_on(self):
        """The next utterance comes after this one."""
        self.utt = self.end

    def draft_text(self) -> str:
        """What this step heard (not the draft it joined)."""
        return self.box.text[self.own:self.end]

    def undo(self):
        text, anchor, caret, draft = self.before
        self.box.text = text
        self.box.anchor, self.box.caret = anchor, caret
        self.box.draft = draft
        self.box.update()
        misses = self.misses
        self._reset()
        self.misses = misses

    def settle(self, text: str, draft: bool = False):
        """Skipped or a described character: text in place of what was typed."""
        if self.typed or self.miss:
            self.undo()
        self._join()
        self.box.replace(self.own, self.end, text, draft=draft)
        self.end = self.own + len(text)
        if draft:
            self.box.draft = (self.start, self.end)


def _box_rect(desk, box) -> QRect:
    return QRect(box.mapTo(desk, QPoint(0, 0)), box.size())


def _orb_rect(orb) -> QRect:
    m = orb.margin
    return orb.geometry().adjusted(m, m, -m, -m)
