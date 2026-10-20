"""Key names: the hotkey that turns listening on and off (config.hotkey), and the names used in key combinations
(Ctrl+Shift+Enter) that a spoken operation's step presses.

The hotkey (2026-10-17, the user's design: click, then press anything) is any keyboard key or mouse button but the
left one, with or without held modifiers: "[ctrl+][shift+][alt+][win+]<main>", main "mouse_middle", "mouse_right",
"mouse_x1", "mouse_x2" or "vk:<hex>" (a left or right modifier alone is its own vk, "vk:a3" right Ctrl).
"""
import ctypes

MOUSE_BUTTONS = {"mouse_middle": "滑鼠中鍵", "mouse_right": "滑鼠右鍵", "mouse_x2": "滑鼠側鍵（上）",
                 "mouse_x1": "滑鼠側鍵（下）"}
HOTKEY_MODS = ("ctrl", "shift", "alt", "win")
# a modifier's virtual-key codes (generic, left, right) -> its name in a hotkey
MOD_OF = {0x10: "shift", 0xA0: "shift", 0xA1: "shift", 0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
          0x12: "alt", 0xA4: "alt", 0xA5: "alt", 0x5B: "win", 0x5C: "win"}
_MOD_LABELS = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win"}
_SIDE_LABELS = {0xA0: "左 Shift", 0xA1: "右 Shift", 0xA2: "左 Ctrl", 0xA3: "右 Ctrl", 0xA4: "左 Alt", 0xA5: "右 Alt",
                0x5B: "左 Win", 0x5C: "右 Win"}
_KEY_LABELS = {0x14: "CapsLock", 0x91: "ScrollLock", 0x13: "Pause", 0x90: "NumLock", 0x2C: "PrintScreen",
               0x5D: "Menu", 0x1B: "Esc", 0xA6: "瀏覽器上一頁", 0xA7: "瀏覽器下一頁", 0xA8: "瀏覽器重新整理",
               0xAA: "瀏覽器搜尋", 0xAB: "瀏覽器我的最愛", 0xAC: "瀏覽器首頁", 0xAD: "靜音", 0xAE: "音量－",
               0xAF: "音量＋", 0xB0: "下一首", 0xB1: "上一首", 0xB2: "停止播放", 0xB3: "播放／暫停", 0xB4: "郵件",
               0xB6: "應用程式 1", 0xB7: "應用程式 2"}
# the names of the fixed list of keys before 2026-10-17 (config.hotkey), for old configs
_OLD_KEYS = {"caps_lock": 0x14, "alt_r": 0xA5, "ctrl_r": 0xA3, "insert": 0x2D, "scroll_lock": 0x91, "pause": 0x13}
_OLD_KEYS.update({f"f{i}": 0x6F + i for i in range(1, 25)})


def hotkey_spec(mods, main: str) -> str:
    return "+".join([m for m in HOTKEY_MODS if m in mods] + [main])


def vk_main(vk: int) -> str:
    return f"vk:{vk:02x}"


def parse_hotkey(spec: str) -> tuple[frozenset, str, int | None]:
    """(modifiers, main, its vk or None for a mouse button); main "" when the spec is empty or not valid."""
    parts = spec.split("+") if spec else []
    if not parts:
        return frozenset(), "", None
    *mods, main = parts
    if any(m not in HOTKEY_MODS for m in mods):
        return frozenset(), "", None
    if main in MOUSE_BUTTONS:
        return frozenset(mods), main, None
    if main.startswith("vk:"):
        try:
            return frozenset(mods), main, int(main[3:], 16)
        except ValueError:
            pass
    return frozenset(), "", None


def upgrade_hotkey(spec: str) -> str:
    """A hotkey saved before 2026-10-17 (a name of the fixed list) in today's form."""
    return vk_main(_OLD_KEYS[spec]) if spec in _OLD_KEYS else spec


def _vk_label(vk: int) -> str:
    if vk in _SIDE_LABELS:
        return _SIDE_LABELS[vk]
    if vk in _KEY_LABELS:
        return _KEY_LABELS[vk]
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    u32 = ctypes.windll.user32
    scan = u32.MapVirtualKeyW(vk, 4)   # MAPVK_VK_TO_VSC_EX: an extended key's scan code has 0xE0 above it
    if scan & 0xFF:
        extended = (scan >> 8) in (0xE0, 0xE1) or vk in EXTENDED
        buf = ctypes.create_unicode_buffer(64)
        if u32.GetKeyNameTextW(((scan & 0xFF) << 16) | ((1 << 24) if extended else 0), buf, 64):
            return buf.value
    return f"按鍵 0x{vk:02X}"


def hotkey_label(spec: str) -> str:
    """Ctrl+Shift+Space, 滑鼠中鍵, 右 Ctrl …; "不使用" for none."""
    mods, main, vk = parse_hotkey(spec)
    if not main:
        return "不使用"
    name = MOUSE_BUTTONS[main] if vk is None else _vk_label(vk)
    return "+".join([_MOD_LABELS[m] for m in HOTKEY_MODS if m in mods] + [name])


MODIFIERS = {"Ctrl": 0x11, "Shift": 0x10, "Alt": 0x12, "Win": 0x5B}
_MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}

NAMES = {"Enter": 0x0D, "Tab": 0x09, "Esc": 0x1B, "Space": 0x20, "Backspace": 0x08, "Delete": 0x2E,
         "Insert": 0x2D, "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22, "Left": 0x25, "Up": 0x26,
         "Right": 0x27, "Down": 0x28, ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
         "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE}
NAMES.update({chr(c): c for c in range(ord("A"), ord("Z") + 1)})
NAMES.update({str(d): 0x30 + d for d in range(10)})
NAMES.update({f"F{i}": 0x6F + i for i in range(1, 25)})
# mouse buttons in a spoken operation's keys (2026-10-21, the user's request; the left one is the click that picks the
# field): their VK codes, sent as mouse input by output.press_chord
MOUSE_VKS = {"滑鼠右鍵": 0x02, "滑鼠中鍵": 0x04, "滑鼠側鍵（下）": 0x05, "滑鼠側鍵（上）": 0x06}
NAMES.update(MOUSE_VKS)
_VK_NAMES = {vk: name for name, vk in NAMES.items()}

# Keys sent with KEYEVENTF_EXTENDEDKEY (otherwise Windows takes them for the keypad's)
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0xA3, 0xA5}


def is_modifier(vk: int) -> bool:
    return vk in _MODIFIER_VKS


def combo_text(modifiers: list[str], vk: int) -> str | None:
    """"Ctrl+Shift+Z" for modifier names and a main key, None for a key without a name."""
    name = _VK_NAMES.get(vk)
    return "+".join(modifiers + [name]) if name else None


def combo_vks(text: str) -> list[int]:
    """The virtual-key codes of a combination ("Ctrl+Shift+Z" -> [0x11, 0x10, 0x5A]); [] if it is not valid."""
    vks = []
    for part in text.split("+") if text else []:
        vk = MODIFIERS.get(part) or NAMES.get(part)
        if vk is None:
            return []
        vks.append(vk)
    return vks
