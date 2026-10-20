"""The Chinese character an English word may have been (2026-10-21, the user's request): one character said alone,
to replace a selected one or to add one in Chinese text, comes out of X-ASR as an English syllable (啊 -> Ah,
的 -> The). App._as_chinese turns such an utterance into the character; 選字's 中文 tab offers them for selected
English, a few words as one Chinese word (How the -> 好的, chinese_words). Two ways in:
- a word spelled like pinyin is that syllable (hao, zai, shi);
- an English word in CMUdict (sounds.py's english.tsv.gz) is compared by its phonemes with every Mandarin syllable,
  each written as rough ARPAbet (_INITIALS / _FINALS), with sounds.py's weighted phoneme distance.
Tones are not known, so every tone of a syllable counts. Characters come from the McBopomofo dictionary
(candidates.py), each under the pinyin of its readings there (pypinyin's other readings are left out); one that
makes a dictionary word with the character before or after it goes first (你 how 嗎 -> 好: 你好), then the closer
syllable, then the more common character."""
import itertools
import logging
import math
import re
import threading

from pypinyin import Style, pinyin
from pypinyin.style import convert

from . import candidates, sounds

log = logging.getLogger("artvoiceinput")

MAX_LETTERS = 6       # longer English is not taken for one character
_MIN_SIM = 0.6
_SYLLABLES = 8        # the closest syllables used
_INITIALS = {"zh": ["JH"], "ch": ["CH"], "sh": ["SH"], "b": ["B"], "p": ["P"], "m": ["M"], "f": ["F"], "d": ["D"],
             "t": ["T"], "n": ["N"], "l": ["L"], "g": ["G"], "k": ["K"], "h": ["HH"], "j": ["JH"], "q": ["CH"],
             "x": ["SH"], "r": ["R"], "z": ["Z"], "c": ["T", "S"], "s": ["S"], "y": ["Y"], "w": ["W"]}
_FINALS = {"a": ["AA"], "o": ["AO"], "e": ["AH"], "ai": ["AY"], "ei": ["EY"], "ao": ["AW"], "ou": ["OW"],
           "an": ["AA", "N"], "en": ["AH", "N"], "ang": ["AA", "NG"], "eng": ["AH", "NG"], "ong": ["UH", "NG"],
           "er": ["ER"], "i": ["IY"], "ia": ["Y", "AA"], "ie": ["Y", "EH"], "iao": ["Y", "AW"], "iu": ["Y", "OW"],
           "ian": ["Y", "EH", "N"], "in": ["IY", "N"], "iang": ["Y", "AA", "NG"], "ing": ["IY", "NG"],
           "iong": ["Y", "UH", "NG"], "u": ["UW"], "ua": ["W", "AA"], "uo": ["W", "AO"], "uai": ["W", "AY"],
           "ui": ["W", "EY"], "uan": ["W", "AA", "N"], "un": ["W", "AH", "N"], "uang": ["W", "AA", "NG"],
           "ue": ["UW", "EH"], "v": ["Y", "UW"], "ve": ["Y", "UW", "EH"], "van": ["Y", "UW", "AA", "N"],
           "vn": ["Y", "UW", "N"]}
_BUZZ = {"zh", "ch", "sh", "r", "z", "c", "s"}   # their -i is no ee: shi is closer to "sher" than to "she"
_TONES = re.compile("[ˊˇˋ˙]")

_index: dict[str, list[tuple[str, int]]] | None = None   # toneless pinyin -> [(character, frequency)], commonest first
_phones: dict[str, list[str]] = {}
_lock = threading.Lock()


def _split(py: str) -> tuple[str, str]:
    for ini in ("zh", "ch", "sh"):
        if py.startswith(ini):
            return ini, py[2:]
    if py[:1] in _INITIALS:
        return py[0], py[1:]
    return "", py


def phones(py: str) -> list[str] | None:
    """A toneless pinyin syllable as rough ARPAbet (hao -> HH AW), None if it isn't one."""
    ini, fin = _split(py)
    if ini in _BUZZ and fin == "i":
        tail = ["IH"]
    elif ini == "y" and fin == "e":
        tail = ["EH"]
    elif ini in ("y", "w") and fin == "":
        return None
    else:
        tail = _FINALS.get(fin)
    if tail is None:
        return None
    return _INITIALS.get(ini, []) + tail


def _load() -> dict:
    global _index
    with _lock:
        if _index is None:
            candidates.load()
            index = {}
            for ch, (freq, readings) in candidates._words.items():
                if len(ch) != 1:
                    continue
                theirs = {_TONES.sub("", r) for r in readings}
                for py in pinyin(ch, style=Style.TONE, heteronym=True)[0]:
                    if _TONES.sub("", convert(py, Style.BOPOMOFO, strict=True) or "") not in theirs:
                        continue
                    plain = convert(py, Style.NORMAL, strict=True).replace("ü", "v")
                    if phones(plain) is not None:
                        index.setdefault(plain, {})[ch] = freq
            _index = {s: sorted(cs.items(), key=lambda cf: -cf[1]) for s, cs in index.items()}
            _phones.update({s: phones(s) for s in _index})
            log.info("syllables: %d, from %d characters", len(_index), sum(len(v) for v in _index.values()))
        return _index


def preload():
    threading.Thread(target=_load, daemon=True).start()


def syllables_for(word: str) -> list[tuple[str, float]]:
    """(toneless pinyin, similarity) the English word may have been, closest first."""
    low = word.strip().lower()
    if not re.fullmatch(r"[a-z]{1,%d}" % MAX_LETTERS, low):
        return []
    index = _load()
    best = {}
    spelled = low.replace("u:", "v")
    if spelled in index:
        best[spelled] = 1.0
    sounds._load_english()
    row = sounds._by_word.get(low)
    if row is not None:
        for s, ph in _phones.items():
            sim = max(1 - sounds._phone_distance(p, ph) / max(len(p), len(ph)) for p in row[2])
            if sim >= _MIN_SIM and sim > best.get(s, 0):
                best[s] = sim
    return sorted(best.items(), key=lambda sv: -sv[1])[:_SYLLABLES]


def chinese_for(word: str, before: str = "", after: str = "", limit: int = 10, exclude: str = "") -> list[str]:
    """Single characters the English word may have been, best first. before / after: the character right before and
    right after it ("" for none); exclude: a character not wanted (the one being replaced)."""
    scored = _scored(word, before, after, exclude)
    return [ch for ch, _ in sorted(scored.items(), key=lambda cs: -cs[1])[:limit]]


def chinese_words(text: str, before: str = "", after: str = "", limit: int = 10) -> list[str]:
    """What English text may have been in Chinese: one word, single characters (chinese_for); two or three, the
    dictionary words their characters make (How the -> 好的), best first."""
    words = text.split()
    if len(words) == 1:
        return chinese_for(words[0], before, after, limit)
    if not 2 <= len(words) <= 3:
        return []
    per = []
    for i, w in enumerate(words):
        s = _scored(w, before if i == 0 else "", after if i == len(words) - 1 else "")
        if not s:
            return []
        per.append(sorted(s.items(), key=lambda cs: -cs[1])[:15])
    top = max(candidates.frequency(w) for w in ("的", "是", "我")) or 1
    out = {}
    for combo in itertools.product(*per):
        w = "".join(ch for ch, _ in combo)
        if candidates.is_word(w):
            out[w] = sum(s for _, s in combo) / len(combo) + 0.3 * math.log(candidates.frequency(w) + 1) / math.log(top + 1)
    return [w for w, _ in sorted(out.items(), key=lambda ws: -ws[1])[:limit]]


def _scored(word: str, before: str = "", after: str = "", exclude: str = "") -> dict[str, float]:
    index = _load()
    scored = {}
    top = max((f for cs in index.values() for _, f in cs[:1]), default=1)
    for s, sim in syllables_for(word):
        for ch, freq in index[s]:
            if ch == exclude:
                continue
            words = [w for w in (before + ch if before else "", ch + after if after else "") if w]
            joins = any(candidates.is_word(w) for w in words)
            if freq < candidates.COMMON and not joins:
                continue
            score = sim + (0.6 if joins else 0) + 0.3 * math.log(freq + 1) / math.log(top + 1)
            if score > scored.get(ch, 0):
                scored[ch] = score
    return scored
