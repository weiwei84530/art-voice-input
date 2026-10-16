"""Custom operations (自訂操作, 2026-10-11): what a spoken phrase does.

Since 2026-10-16 only spoken operations are set (the user's design: listening is turned on and off from the
interface, and one hotkey, config.hotkey, taps it on and off; the key rows that also took back and deleted were
removed). A rule is an utterance that is exactly a phrase and one step: a command (結束錄音 stop listening, 復原 take
back VoiceInput's last change, 全選 / 複製 / 剪下 / 貼上), a key combination, text to type, or text typed on both
sides of the caret or selection (左右輸入文字). The engine still knows mouse and key triggers, gestures, situations
and several steps: the app builds the hotkey's one rule (a tap that records) from config.hotkey, and old configs
are read through them (migrate, upgrade).
"""
import re
from dataclasses import asdict, dataclass, field

MOUSE, KEY, SPEECH = "mouse", "key", "speech"
TAP, DOUBLE, HOLD = "tap", "double", "hold"
ANY, DICTATED, SELECTION = "any", "dictated", "selection"
COMMAND, KEYS, TEXT, WAIT = "command", "keys", "text", "wait"
WRAP = "wrap"   # 左右輸入文字 (2026-10-16): value [left, right], typed around the caret or the selection
RECORD, DELETE_SELECTION, DELETE_DICTATION = "record", "delete_selection", "delete_dictation"
PICK = "pick"
STOP = "stop"        # 結束錄音: listening off (送出 did it by default 2026-10-14/15)
UNDO = "undo"        # 復原: double tap and the spoken 復原 by default (the user's request 2026-10-14)
# 全選 / 複製 / 剪下 / 貼上 (2026-10-16, the user's request): commands, not keys, because a terminal differs: Claude
# Code clears its input on Ctrl+C, its mouse selection is not the cursor's, and nothing there selects all
SELECT_ALL, COPY, CUT, PASTE = "select_all", "copy", "cut", "paste"
EDIT_COMMANDS = (SELECT_ALL, COPY, CUT, PASTE)
_LISTEN = "listen"   # 連續聽寫, a command for a few hours on 2026-10-14 until 錄音 itself became continuous
_ADD_HOTWORD = "add_hotword"   # 加入熱詞, removed 2026-10-11: hotwords are typed in the 選字 menu instead
# config rules_version: 2 added the tap on a selection that opens 選字, 3 a tap that listens, 4 dropped 連續聽寫,
# 5 makes 送出 stop listening, 6 turns the double-tap deletes into 復原 and adds the spoken 復原, 7 brings back the
# double tap on a selection that deletes it, 8 adds the spoken 撤銷 (復原) and 刪除 (Backspace), 9 makes 送出 leave
# listening on (the user's request, 2026-10-15: the microphone stays on, the key turns it off), 10: the simple
# editor (simplify: hold on a selection = 選字 and the spoken 括號 dropped, 2026-10-16), 11 adds the spoken 結束
# (結束錄音, the user's request the same day), 12 adds 全選 / 複製 / 剪下 / 貼上 (commands) and drops 貼上 = Alt+V,
# 13 brings the spoken 括號 back as 左右輸入文字 （ ）, 14 adds 引號 「」 (the key rules went to config.hotkey)
VERSION = 14

_PUNCT = re.compile(r"[\s，。、！？；：,.!?;:…]+")


@dataclass
class Step:
    type: str = COMMAND
    value: object = RECORD      # command name, key combination ("Ctrl+Z"), text, or milliseconds to wait


@dataclass
class Rule:
    source: str = MOUSE
    key: str = "mouse_middle"   # mouse / keyboard trigger: a name in keys.MOUSE_TRIGGERS / keys.KEY_TRIGGERS
    phrase: str = ""            # speech trigger: the whole utterance
    gesture: str = HOLD         # not used by speech triggers
    when: str = ANY
    steps: list = field(default_factory=lambda: [Step()])
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "steps"}
        return cls(**known, steps=[Step(**s) for s in d.get("steps", [])])

    def to_dict(self) -> dict:
        return asdict(self)

    def record_index(self) -> int | None:
        return next((i for i, s in enumerate(self.steps) if s.type == COMMAND and s.value == RECORD), None)


def defaults(newline: bool = True, send: bool = True) -> list[Rule]:
    """The spoken operations (the user's own setup, 2026-10-14/16), in the order the 自訂操作 tab groups them:
    typing (換行 Shift+Enter, 空白, 標點 "- ", 括號 （ ）, 引號 「」), changing (刪除 Backspace, 復原 / 撤銷), the
    clipboard (全選 / 複製 / 剪下 / 貼上) and ending (送出 Enter, listening goes on; 結束 turns it off). No key
    rules since 2026-10-16: the hotkey is config.hotkey."""
    out = [Rule(SPEECH, phrase="換行", steps=[Step(KEYS, "Shift+Enter")])] if newline else []
    out += [Rule(SPEECH, phrase="空白", steps=[Step(KEYS, "Space")]),
            Rule(SPEECH, phrase="標點", steps=[Step(TEXT, "- ")]),
            Rule(SPEECH, phrase="括號", steps=[Step(WRAP, ["（", "）"])]),
            Rule(SPEECH, phrase="引號", steps=[Step(WRAP, ["「", "」"])]),
            Rule(SPEECH, phrase="刪除", steps=[Step(KEYS, "Backspace")]),
            Rule(SPEECH, phrase="復原", steps=[Step(COMMAND, UNDO)]),
            Rule(SPEECH, phrase="撤銷", steps=[Step(COMMAND, UNDO)]),
            Rule(SPEECH, phrase="全選", steps=[Step(COMMAND, SELECT_ALL)]),
            Rule(SPEECH, phrase="複製", steps=[Step(COMMAND, COPY)]),
            Rule(SPEECH, phrase="剪下", steps=[Step(COMMAND, CUT)]),
            Rule(SPEECH, phrase="貼上", steps=[Step(COMMAND, PASTE)])]
    if send:
        out.append(Rule(SPEECH, phrase="送出", steps=[Step(KEYS, "Enter")]))
    out.append(Rule(SPEECH, phrase="結束", steps=[Step(COMMAND, STOP)]))
    return out


def migrate(rules: list[Rule]) -> list[Rule]:
    """The one 刪除 command (before the split, 2026-10-11) becomes the command for the rule's situation; a rule for
    any situation becomes two: one for a selection, one right after a dictation."""
    out = []
    for r in rules:
        if any(s.type == COMMAND and s.value == _ADD_HOTWORD for s in r.steps):
            r.steps = [s for s in r.steps if not (s.type == COMMAND and s.value == _ADD_HOTWORD)]
            if not r.steps:
                continue
        if not any(s.type == COMMAND and s.value == "delete" for s in r.steps):
            out.append(r)
            continue
        for when, command in ((SELECTION, DELETE_SELECTION), (DICTATED, DELETE_DICTATION)):
            if r.when in (when, ANY):
                steps = [Step(COMMAND, command) if s.type == COMMAND and s.value == "delete" else Step(s.type, s.value)
                         for s in r.steps]
                out.append(Rule(r.source, r.key, r.phrase, r.gesture, when, steps, r.enabled))
    return out


def upgrade(rules: list[Rule], version: int) -> list[Rule]:
    """Defaults added after a config was saved, on the key that records by holding unless that tap is taken:
    version 2 adds tap on a selection = 選字, version 3 tap = 錄音 (listening until the next tap). Version 4: the
    連續聽寫 command became 錄音."""
    hold = next((r for r in rules if r.source != SPEECH and r.gesture == HOLD and r.record_index() is not None), None)
    if hold and version < 2:
        if not any(r.key == hold.key and r.gesture == TAP and r.when in (SELECTION, ANY) for r in rules):
            rules.append(Rule(hold.source, hold.key, gesture=TAP, when=SELECTION, steps=[Step(COMMAND, PICK)]))
    if hold and version < 3:
        if not any(r.key == hold.key and r.gesture == TAP and r.when == ANY for r in rules):
            rules.append(Rule(hold.source, hold.key, gesture=TAP, steps=[Step(COMMAND, RECORD)]))
    if version < 4:
        for r in rules:
            r.steps = [Step(COMMAND, RECORD) if st.type == COMMAND and st.value == _LISTEN else st for st in r.steps]
    if version < 5:
        for r in rules:
            if r.source == SPEECH and normalize(r.phrase) == "送出" and not any(
                    st.type == COMMAND and st.value == STOP for st in r.steps):
                r.steps.append(Step(COMMAND, STOP))
    if version < 6:
        deletes = [r for r in rules if r.source != SPEECH and r.gesture == DOUBLE
                   and [(st.type, st.value) for st in r.steps] in ([(COMMAND, DELETE_SELECTION)],
                                                                   [(COMMAND, DELETE_DICTATION)])]
        for key in dict.fromkeys(r.key for r in deletes):
            first = next(i for i, r in enumerate(rules) if r in deletes and r.key == key)
            mine = [r for r in deletes if r.key == key]
            if not any(r.key == key and r.gesture == DOUBLE and r.when == ANY and r not in mine for r in rules):
                rules.insert(first, Rule(mine[0].source, key, gesture=DOUBLE, steps=[Step(COMMAND, UNDO)]))
            for r in mine:
                rules.remove(r)
        if not any(r.source == SPEECH and normalize(r.phrase) == "復原" for r in rules):
            rules.append(Rule(SPEECH, phrase="復原", steps=[Step(COMMAND, UNDO)]))
    if version < 7:
        for i, r in reversed(list(enumerate(rules))):
            if r.source != SPEECH and r.gesture == DOUBLE and r.when == ANY \
                    and [(st.type, st.value) for st in r.steps] == [(COMMAND, UNDO)] \
                    and not any(o.key == r.key and o.gesture == DOUBLE and o.when == SELECTION for o in rules):
                rules.insert(i, Rule(r.source, r.key, gesture=DOUBLE, when=SELECTION,
                                     steps=[Step(COMMAND, DELETE_SELECTION)]))
    if version < 8:
        for phrase, step in (("撤銷", Step(COMMAND, UNDO)), ("刪除", Step(KEYS, "Backspace"))):
            if not any(r.source == SPEECH and normalize(r.phrase) == phrase for r in rules):
                rules.append(Rule(SPEECH, phrase=phrase, steps=[step]))
    if version < 9:
        for r in rules:
            if r.source == SPEECH and normalize(r.phrase) == "送出" \
                    and [(st.type, st.value) for st in r.steps] == [(KEYS, "Enter"), (COMMAND, STOP)]:
                r.steps.pop()
    if version < 11 and not any(r.source == SPEECH and normalize(r.phrase) == "結束" for r in rules):
        rules.append(Rule(SPEECH, phrase="結束", steps=[Step(COMMAND, STOP)]))
    if version < 13 and not any(r.source == SPEECH and normalize(r.phrase) == "括號" for r in rules):
        rules.append(Rule(SPEECH, phrase="括號", steps=[Step(WRAP, ["（", "）"])]))
    if version < 14 and not any(r.source == SPEECH and normalize(r.phrase) == "引號" for r in rules):
        rules.append(Rule(SPEECH, phrase="引號", steps=[Step(WRAP, ["「", "」"])]))
    if version < 12:
        rules[:] = [r for r in rules if not (r.source == SPEECH and normalize(r.phrase) == "貼上"
                                             and [(st.type, st.value) for st in r.steps] == [(KEYS, "Alt+V")])]
        for phrase, command in (("全選", SELECT_ALL), ("複製", COPY), ("剪下", CUT), ("貼上", PASTE)):
            if not any(r.source == SPEECH and normalize(r.phrase) == phrase for r in rules):
                rules.append(Rule(SPEECH, phrase=phrase, steps=[Step(COMMAND, command)]))
    return rules


# Spoken rows (2026-10-16, the user's choice: no built-in rows, every one editable): a phrase box (several phrases
# separated by 、, one rule each) and one step: keys, text, 左右輸入文字, 復原 (VoiceInput's own, not Ctrl+Z), 結束錄音
# or an edit command.
PHRASES = re.compile(r"[、,，/／;；]+")


def phrases(text: str) -> list[str]:
    """復原、撤銷 -> [復原, 撤銷]"""
    return [p.strip() for p in PHRASES.split(text) if p.strip()]


def spoken_ok(rule: Rule) -> bool:
    """A speech rule the simple editor can show: one step of keys, text, 復原, 結束錄音 or an edit command."""
    if rule.source != SPEECH or len(rule.steps) != 1:
        return False
    st = rule.steps[0]
    return st.type in (KEYS, TEXT, WRAP) or st.type == COMMAND and st.value in (UNDO, STOP) + EDIT_COMMANDS


def simplify(rules: list[Rule]) -> list[Rule]:
    """The rules the simple editor can show (2026-10-16): enabled speech rules of one step, for any situation, the
    first of a phrase; the rest is dropped (key rules: the hotkey is config.hotkey; hold on a selection = 選字, the
    spoken 括號 of two steps)."""
    out, seen = [], set()
    for r in rules:
        if r.enabled and spoken_ok(r) and normalize(r.phrase) and normalize(r.phrase) not in seen:
            seen.add(normalize(r.phrase))
            out.append(Rule(SPEECH, phrase=r.phrase, steps=[Step(r.steps[0].type, r.steps[0].value)]))
    return out


def normalize(phrase: str) -> str:
    return _PUNCT.sub("", phrase).casefold()


def _same_trigger(a: Rule, b: Rule) -> bool:
    if a.source != b.source:
        return False
    if a.source == SPEECH:
        return normalize(a.phrase) == normalize(b.phrase)
    return a.key == b.key and a.gesture == b.gesture


def candidates(rules: list[Rule], source: str, trigger: str, gesture: str = "") -> list[Rule]:
    """Enabled, valid rules for a trigger (a key name, or the utterance for speech) and gesture."""
    probe = Rule(source, key=trigger, phrase=trigger, gesture=gesture)
    return [r for r in rules if r.enabled and _same_trigger(r, probe) and not problems(r, rules)]


def pick(cands: list[Rule], selection: bool, dictated: bool) -> Rule | None:
    """The rule for the situation: selected text first, then right after a dictation, then any."""
    for when, applies in ((SELECTION, selection), (DICTATED, dictated), (ANY, True)):
        if applies:
            for r in cands:
                if r.when == when:
                    return r
    return None


def problems(rule: Rule, rules: list[Rule]) -> list[str]:
    """Why a rule cannot work (shown under it in the settings); it is skipped while it has any."""
    out = []
    if rule.source == SPEECH and not normalize(rule.phrase):
        out.append("請輸入要說的話")
    records = sum(1 for s in rule.steps if s.type == COMMAND and s.value == RECORD)
    if rule.source == SPEECH and records:
        out.append("「說出」的操作不能錄音")
    elif records > 1:
        out.append("一個操作最多一個「錄音」")
    if any(s.type == KEYS and not s.value for s in rule.steps):
        out.append("按鍵步驟還沒設定組合鍵")
    if not rule.steps:
        out.append("沒有步驟")
    if rule.enabled:
        for r in rules:
            if r is rule:
                break
            if r.enabled and _same_trigger(r, rule) and r.when == rule.when:
                out.append("和上面一條操作的觸發、按法、情境都相同，這條不會生效")
                break
    return out
