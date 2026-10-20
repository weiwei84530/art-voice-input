"""Settings persisted as config.json in the per-user data folder (see paths.py)."""
import json
from dataclasses import asdict, dataclass, field

from . import rules
from .rules import VERSION as RULES_VERSION
from .paths import CONFIG_PATH


# launched with --debug (2026-10-17, the user's request): the 開發測試 settings are shown and work; a release is
# launched without it, and they are off. Set by app.main before the config is loaded.
DEBUG = False
BUTTON_SCALE_RANGE = (75, 125)


@dataclass
class Config:
    # defaults: the user's own setup (screenshots of 2026-10-17)
    mic: str = ""                  # input device name, "" = system default
    # the settings window's and the 選字 menu's colors (2026-10-18, the redesign): light, dark or system (Windows'
    # app mode)
    theme: str = "system"
    autostart: bool = True
    mute_while_recording: bool = True   # mute the speakers while listening
    period_to_comma: bool = True   # speaking on a selected 。 turns it into ， + the utterance + 。
    punctuation_names: bool = True  # an utterance of just a punctuation name (逗號, 句號 …) types the mark
    describe_char: bool = True     # 節日的節 types 節 (edit.described)
    # the key or mouse button, with modifiers, a press of which turns listening on and off (keys.parse_hotkey), ""
    # none (2026-10-16, the user's design: the one key binding left; any key since 2026-10-17)
    hotkey: str = ""
    glow: str = "siri"             # glow.py style along the screen's edges while listening, "" for none
    glow_edges: str = "all"        # which edges glow (glow.EDGES): all, tb, lr, top, bottom
    glow_motion: str = "soft"      # how it moves (glow.MOTIONS): soft, wave, comet, ripple
    # the floating button's and the bubble's look (orbs.LOOKS): the microphone, or an energy orb in the glow's colors
    button_look: str = "flow"
    # 節流模式 (2026-10-16): the orbs as first made, 15 fps and coarser; off, 30 fps and finer (looks first)
    orb_lite: bool = False
    # the floating button's and the bubble's size, percent of the usual (75-125; 2026-10-16, the user's request)
    button_scale: int = 100
    # each glow style's changed parameters: style id -> colors (2-4), turn, pulse, depth, bright (glow.PARAM_KEYS)
    glow_edits: dict = field(default_factory=dict)
    # the floating microphone button's place (show_float), as fractions of the screen's free range
    float_pos: list = field(default_factory=lambda: [0.98, 0.88])
    # the floating button only while text can be typed where the focus is and listening is off; False: always, while
    # listening too, a click turning it off (2026-10-16, the user's request). The 一般 tab calls it
    # 未偵測到輸入區域時隱藏, unticked by default (2026-10-17)
    float_text_only: bool = False
    # float_keep: the floating button stays while listening (a click jumps it and turns listening off) instead of
    # growing and fading out with the glow (2026-10-16, the user's request). Shown inverted as 錄音時隱藏按鈕,
    # unticked by default (2026-10-17)
    float_keep: bool = True
    # when the focus comes into a text box (2026-10-16, the user's requests): "" nothing, "bubble" a small microphone
    # bubble by the caret (a click listens), "float" the draggable floating button, shown only while text can be
    # typed where the focus is, "listen" listening turns on, and off when the focus leaves for a place where nothing
    # can be typed
    # 輸入框旁的按鈕 (the 外觀 tab, two checkboxes; 2026-10-16, the user's design: they were one choice with
    # auto_listen): the bubble by the click that put the focus in a text box, and the draggable floating button
    # (kept on screen with float_keep, a fixed place to turn listening off); either may go with auto_listen
    show_bubble: bool = True
    show_float: bool = True
    # 點進輸入框時 自動開麥克風 (the 麥克風 page): a left click that puts the focus in a text box turns listening on,
    # at the moments the bubble would show (2026-10-20, the user's design; keyboard focus does nothing). One choice
    # with show_bubble (點進輸入框時: 不使用 / bubble / this), so at most one of them is on
    auto_listen: bool = False
    # 自動關閉麥克風 (that card's checkbox, 2026-10-20, the user's design; off by default): the focus leaving a text box
    # for a place where nothing can be typed turns listening off, however it was turned on
    auto_off: bool = False
    # the color the draft is marked with (highlight.py), #AARRGGBB; highlighter yellow by default, unlike a
    # selection's blue (2026-10-16, the user's choice: a selection-blue draft passed for a selection)
    highlight_color: str = "#78FFE45C"
    # minutes without speech after which listening turns itself off, 0 never (the user's request, 2026-10-15: a
    # microphone left on by mistake; 5 their choice of default)
    auto_off_minutes: int = 5
    # 送出後關閉麥克風 (2026-10-16, the user's request): Enter (or Ctrl+Enter) pressed, or a spoken operation's Enter
    # step (送出), turns listening off; Shift+Enter (a new line) does not
    stop_on_enter: bool = False
    hotword_sort: str = "date"     # order of 詞庫列表 (ui/page_bank.SORTS)
    pick_sort: str = "date"        # order of 選字記憶 (ui/page_bank.SORTS)
    alias_sort: str = "date"       # order of 英文替換 (ui/page_bank.SORTS)
    hotword_section: str = ""      # the open section of the 詞庫 tab ("" none, packs, words, picks, aliases)
    # ids of the ticked term packs (packs.py); none by default since 2026-10-17 (the user's choice; the AI pack before)
    packs: list = field(default_factory=list)
    start_sound: str = "blip"     # cues.py id played when the recording indicator shows, "" for none
    stop_sound: str = "blip"      # cues.py id played when the recording ends, "" for none
    # development only, to be removed before release (recordings.py): on exactly when launched with --debug
    save_recordings: bool = field(default_factory=lambda: DEBUG)
    rules: list = field(default_factory=lambda: rules.defaults(dev=DEBUG))   # custom operations (rules.Rule)
    rules_version: int = RULES_VERSION

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls.from_data(data)

    @classmethod
    def from_data(cls, data: dict) -> "Config":
        """A config from saved data (config.json, or an exported file: userdata.py), older formats migrated."""
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k not in ("rules", "rules_version")}
        cfg = cls(**known)
        if "show_bubble" not in data and "show_float" not in data:
            # on_focus, one choice of "", bubble, float, listen until the evening of 2026-10-16, split in two; the
            # floating button's checkbox (a few hours that day) before it
            on_focus = data.get("on_focus") or ("float" if data.get("float_button") else "")
            cfg.show_bubble, cfg.show_float = on_focus == "bubble", on_focus == "float"
            cfg.auto_listen = on_focus == "listen"
        if cfg.auto_listen:
            cfg.show_bubble = False
        if data.get("glow") == "custom":   # the 自訂 style (2026-10-16, a few hours): 彩虹 changed that way
            cfg.glow = "siri"
            cfg.glow_edits = {"siri": data.get("glow_custom") or {}}
        cfg.button_scale = min(max(int(cfg.button_scale), BUTTON_SCALE_RANGE[0]), BUTTON_SCALE_RANGE[1])
        cfg.save_recordings = DEBUG   # no setting (2026-10-20): recordings are kept exactly in debug mode
        if "rules" in data:
            old = rules.upgrade([rules.Rule.from_dict(d) for d in data["rules"]], data.get("rules_version", 1))
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
