"""匯出詞庫 / 匯入詞庫 / 清空詞庫 (the 一般 tab's buttons, 2026-10-17, the user's design): everything the 詞庫 tab
holds, in one JSON file: the word list with its 英文強制替換 aliases (hotwords.py), 選字記憶 (memory.py), which term
packs are ticked and the user's copies of the pack files (packs.py).

Importing merges (the user's choice): what the file has is added, and an entry both have takes the file's; to
replace everything, clear first. Clearing puts the packs back as shipped and ticks none.
"""
import json
import shutil
import time
from pathlib import Path

from . import packs

FORMAT = "voiceinput-wordbank"
VERSION = 1


def export(path: Path, cfg, hotwords, memory) -> None:
    files = {}
    for p in sorted(packs.DIR.glob("*.txt")):
        try:
            files[p.stem] = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
    data = {"format": FORMAT, "version": VERSION, "exported": time.strftime("%Y-%m-%d %H:%M:%S"),
            "hotwords": hotwords.export(), "smart_picks": memory.export(), "packs_ticked": list(cfg.packs),
            "pack_files": files}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path: Path) -> dict:
    """The file's data; ValueError when it is not an exported 詞庫."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("不是 VoiceInput 匯出的詞庫檔")
    return data


def merge(data: dict, cfg, hotwords, memory) -> dict:
    """Adds the file's 詞庫 to what is here; counts of what came in."""
    words = hotwords.merge(data.get("hotwords", []))
    picks = memory.merge(data.get("smart_picks", {}))
    added_terms = 0
    packs.DIR.mkdir(parents=True, exist_ok=True)
    for pack_id, text in (data.get("pack_files") or {}).items():
        if not isinstance(text, str) or not pack_id or any(c in pack_id for c in "\\/:*?\"<>|."):
            continue
        dst = packs.path(pack_id)
        if not dst.exists():
            dst.write_text(text, encoding="utf-8")
            continue
        here = set(packs._load(dst).words)
        theirs = [line.strip() for line in text.splitlines()]
        new = list(dict.fromkeys(w for w in theirs if w and not w.startswith("#") and w not in here))
        if new:
            mine = dst.read_text(encoding="utf-8")
            mine += ("" if mine.endswith("\n") or not mine else "\n") + \
                f"\n# imported {time.strftime('%Y-%m-%d')}\n" + "\n".join(new) + "\n"
            dst.write_text(mine, encoding="utf-8")
            added_terms += len(new)
    ticked = [i for i in data.get("packs_ticked", []) if isinstance(i, str)]
    cfg.packs = list(dict.fromkeys(list(cfg.packs) + ticked))
    return {"words": words, "picks": picks, "pack_terms": added_terms}


def clear(cfg, hotwords, memory) -> None:
    hotwords.clear()
    memory.clear()
    for p in packs.DIR.glob("*.txt"):
        p.unlink(missing_ok=True)
    for src in packs.SHIPPED.glob("*.txt"):
        shutil.copyfile(src, packs.DIR / src.name)
    cfg.packs = []
