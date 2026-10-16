"""Settings persisted as config.json in the per-user data folder (see paths.py)."""
import json
from dataclasses import asdict, dataclass, field

from . import rules
from .rules import VERSION as RULES_VERSION
from .paths import CONFIG_PATH


GESTURE_TIME_RANGE = (0.15, 0.8)


@dataclass
class Config:
    mic: str = ""                  # input device name, "" = system default
    autostart: bool = False
    mute_while_recording: bool = True   # mute the speakers while listening
    period_to_comma: bool = True   # speaking on a selected 。 turns it into ， + the utterance + 。
    punctuation_names: bool = True  # an utterance of just a punctuation name (逗號, 句號 …) types the mark
    describe_char: bool = True     # 節日的節 types 節 (edit.described)
    # the mouse button or key (keys.MOUSE_TRIGGERS / KEY_TRIGGERS) a tap of which turns listening on and off, ""
    # none (2026-10-16, the user's design: the one key binding left; the key rows of 自訂操作 were removed)
    hotkey: str = "mouse_middle"
    glow: str = ""                 # glow.py style along the screen's edges while listening, "" for none
    glow_edges: str = "all"        # which edges glow (glow.EDGES): all, tb, lr, top, bottom
    # the floating microphone button's place (on_focus "float"), as fractions of the screen's free range
    float_pos: list = field(default_factory=lambda: [0.98, 0.88])
    # when the focus comes into a text box (2026-10-16, the user's requests): "" nothing, "bubble" a small microphone
    # bubble by the caret (a click listens), "float" the draggable floating button, shown only while text can be
    # typed where the focus is, "listen" listening turns on, and off when the focus leaves for a place where nothing
    # can be typed
    on_focus: str = ""
    # the color the draft is marked with (highlight.py), #AARRGGBB; highlighter yellow by default, unlike a
    # selection's blue (2026-10-16, the user's choice: a selection-blue draft passed for a selection)
    highlight_color: str = "#78FFE45C"
    # minutes without speech after which listening turns itself off, 0 never (the user's request, 2026-10-15: a
    # microphone left on by mistake; 5 their choice of default)
    auto_off_minutes: int = 5
    hotword_sort: str = "date"     # order of the 詞庫 tab (settings.HOTWORD_SORTS)
    pick_sort: str = "date"        # order of 選字記憶 on the 詞庫 tab (settings.PICK_SORTS)
    alias_sort: str = "date"       # order of 英文強制替換 (settings.ALIAS_SORTS)
    hotword_section: str = ""      # the open section of the 詞庫 tab ("" none, packs, words, picks, aliases)
    packs: list = field(default_factory=lambda: ["ai"])   # ids of the ticked term packs (packs.py)
    pack_hints: list = field(default_factory=list)   # packs a notice already suggested (App._suggest_pack)
    start_sound: str = "blip"     # cues.py id played when the recording indicator shows, "" for none
    stop_sound: str = "blip"      # cues.py id played when the recording ends, "" for none
    # seconds: a press this long is a hold, a press this soon after a tap's release makes a double tap (both given
    # back to the hotkey); no longer on a tab since 2026-10-16
    gesture_time: float = 0.15
    # while listening, when the text typed so far is decoded again and fixed: "command" (a spoken command or the
    # end of listening) or "pause" (every pause); the user's choice of default, 2026-10-14
    commit_at: str = "command"
    stop_sound_at: str = "stop"   # when the end sound plays: "stop" (recording stops) or "done" (text is in)
    save_recordings: bool = False   # development only, to be removed before release (recordings.py)
    rules: list = field(default_factory=rules.defaults)   # custom operations (rules.Rule)
    rules_version: int = RULES_VERSION

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k not in ("rules", "rules_version")}
        cfg = cls(**known)
        if data.get("float_button", False) and not data.get("on_focus"):
            cfg.on_focus = "float"   # the floating button's checkbox (2026-10-16, a few hours) became this choice
        cfg.gesture_time = min(max(float(cfg.gesture_time), GESTURE_TIME_RANGE[0]), GESTURE_TIME_RANGE[1])
        if "rules" in data:
            old = rules.upgrade(rules.migrate([rules.Rule.from_dict(d) for d in data["rules"]]),
                                data.get("rules_version", 1))
            if "hotkey" not in data:   # the key that recorded (the 自訂操作 key rows, until 2026-10-16)
                cfg.hotkey = next((r.key for r in old if r.enabled and r.source != rules.SPEECH
                                   and r.record_index() is not None), "")
            cfg.rules = rules.simplify(old)
        else:   # before custom operations (2026-10-11): one hotkey (read above) and the 換行 / 送出 switches
            cfg.rules = rules.defaults(data.get("newline_command", True), data.get("send_command", True))
        return cfg

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
