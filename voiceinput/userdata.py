"""A user's VoiceInput data in one file (the 一般 tab's 匯出 / 匯入 / 還原預設, 2026-10-17, the user's design): every
setting (config.json, 自訂操作 included) and the 詞庫: the word list with its 英文強制替換 aliases (hotwords.py),
選字記憶 (memory.py), which term packs are ticked and the user's copies of the pack files (packs.py).

Importing replaces the settings, but those tied to this computer (LOCAL: the microphone, autostart, the floating
button's place), and merges the 詞庫 (the user's choice): what the file has is added, an entry both have takes the
file's, packs ticked on either side stay ticked. 還原預設 puts everything back as installed, the 詞庫 too: the
packs as shipped, none ticked.
"""
import json
import shutil
import time
from dataclasses import asdict, fields
from pathlib import Path

from . import packs
from .config import Config

FORMAT = "voiceinput-data"
VERSION = 1
LOCAL = ("mic", "autostart", "float_pos")


def export(path: Path, cfg, hotwords, memory) -> None:
    files = {}
    for p in sorted(packs.DIR.glob("*.txt")):
        try:
            files[p.stem] = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
    data = {"format": FORMAT, "version": VERSION, "exported": time.strftime("%Y-%m-%d %H:%M:%S"),
            "settings": asdict(cfg), "hotwords": hotwords.export(), "smart_picks": memory.export(),
            "pack_files": files}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path: Path) -> dict:
    """The file's data; ValueError when it is not a VoiceInput export."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("settings"), dict):
        raise ValueError("不是 VoiceInput 匯出的設定檔")
    return data


def import_into(data: dict, cfg, hotwords, memory) -> dict:
    """The file's settings in place of cfg's (not LOCAL ones), its 詞庫 merged; counts of what came in."""
    ticked = list(cfg.packs)
    new = Config.from_data(data["settings"])
    for f in fields(Config):
        if f.name not in LOCAL:
            setattr(cfg, f.name, getattr(new, f.name))
    cfg.packs = list(dict.fromkeys(ticked + list(cfg.packs)))
    words = hotwords.merge(data.get("hotwords", []))
    picks = memory.merge(data.get("smart_picks", {}))
    terms = 0
    packs.DIR.mkdir(parents=True, exist_ok=True)
    for pack_id, text in (data.get("pack_files") or {}).items():
        if not isinstance(text, str) or not pack_id or any(c in pack_id for c in "\\/:*?\"<>|."):
            continue
        dst = packs.path(pack_id)
        if not dst.exists():
            dst.write_text(text, encoding="utf-8")
            continue
        here = set(packs._load(dst).words)
        new_words = list(dict.fromkeys(w.strip() for w in text.splitlines()
                                       if w.strip() and not w.strip().startswith("#") and w.strip() not in here))
        if new_words:
            mine = dst.read_text(encoding="utf-8")
            mine += ("" if mine.endswith("\n") or not mine else "\n") + \
                f"\n# imported {time.strftime('%Y-%m-%d')}\n" + "\n".join(new_words) + "\n"
            dst.write_text(mine, encoding="utf-8")
            terms += len(new_words)
    return {"words": words, "picks": picks, "pack_terms": terms}


def reset(cfg, hotwords, memory) -> None:
    """Everything as installed: every setting, and the 詞庫 emptied (packs as shipped, none ticked)."""
    fresh = Config()
    for f in fields(Config):
        setattr(cfg, f.name, getattr(fresh, f.name))
    hotwords.clear()
    memory.clear()
    for p in packs.DIR.glob("*.txt"):
        p.unlink(missing_ok=True)
    for src in packs.SHIPPED.glob("*.txt"):
        shutil.copyfile(src, packs.DIR / src.name)
