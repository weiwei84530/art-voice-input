"""The word list the app asks "is this a word / how common is it" (disfluency removal), and same-sounding
word candidates (城市 -> 程式, 誠實, 乘勢 …) for suspects.py, which is off for now.

The words come from McBopomofo (小麥注音, MIT): ~146k Taiwanese phrases of 2-6 characters and the Big5 single
characters, each with its Bopomofo reading and a frequency counted in a Taiwanese corpus (dict/words.tsv.gz, built
by dev/build_dict.py). Every word is indexed by its toneless reading, made fuzzy for Taiwanese-accent confusions
(ㄓ/ㄗ, ㄔ/ㄘ, ㄕ/ㄙ, ㄥ/ㄣ, ㄤ/ㄢ which also covers ㄧㄤ/ㄧㄢ and ㄨㄤ/ㄨㄢ, ㄖ/ㄌ; the user's set,
2026-10-11: ㄖ/ㄌ replaced ㄌ/ㄋ, ㄈ/ㄏ left out), under both McBopomofo's reading and pypinyin's (垃圾 is listed as
ㄌㄜˋ ㄙㄜˋ but said ㄌㄚ ㄐㄧ). Candidates are ordered: same reading with tones, same reading without tones,
fuzzy reading; then frequency. The index is cached in DATA_DIR/cache and built in the background at startup.

Until 2026-10-02 this used jieba's dict.txt (349k mainland words, POS tags); see AGENTS.md.
"""
import gzip
import logging
import pickle
import re
import threading
from pathlib import Path

from pypinyin import Style, lazy_pinyin

from .paths import DATA_DIR

log = logging.getLogger("voiceinput")

_DICT = Path(__file__).resolve().parent / "dict" / "words.tsv.gz"
_CACHE = DATA_DIR / "cache" / "word_index.pkl"
_OLD_CACHE = DATA_DIR / "cache" / "pinyin_index.pkl"   # the jieba index, removed on first build
_CACHE_VERSION = 4   # the index keys depend on _FUZZY
_CJK = re.compile(r"^[㐀-䶿一-鿿]+$")
_TONES = re.compile("[ˊˇˋ˙]")
# ㄩㄣ with ㄧㄣ (雲 / 銀, 軍 / 今; 2026-10-16, the user's request)
# ㄈ with ㄏㄨ (飛 ㄈㄟ / 灰 ㄏㄨㄟ, 發 / 花, 福 / 胡) and ㄋ with ㄌ (你 / 裡), the user's choice the same day
_FUZZY = [("ㄓ", "ㄗ"), ("ㄔ", "ㄘ"), ("ㄕ", "ㄙ"), ("ㄤ", "ㄢ"), ("ㄖ", "ㄌ"), ("ㄩㄣ", "ㄧㄣ"), ("ㄈㄨ", "ㄏㄨ"),
          ("ㄈ", "ㄏㄨ"), ("ㄋ", "ㄌ")]
_ENG = re.compile("(?<![ㄨㄩ])ㄥ")   # eng/en and ing/in, but not ong/un or iong/ün

_index: dict[str, list[tuple[str, str, int]]] | None = None   # fuzzy key -> [(word, toned reading, frequency)]
_words: dict[str, tuple[int, list[str]]] = {}                  # word -> (frequency, toned readings)
_lock = threading.Lock()


def _toned(syllable: str) -> str:
    """pypinyin puts the neutral-tone dot first (˙ㄉㄜ), McBopomofo last (ㄉㄜ˙)."""
    return syllable[1:] + "˙" if syllable.startswith("˙") else syllable


def _key(reading: str) -> str:
    key = _ENG.sub("ㄣ", _TONES.sub("", reading))
    for a, b in _FUZZY:
        key = key.replace(a, b)
    return key


def _pypinyin_reading(word: str) -> str:
    return " ".join(_toned(s) for s in lazy_pinyin(word, style=Style.BOPOMOFO))


def _build() -> tuple[dict, dict]:
    index: dict[str, list[tuple[str, str, int]]] = {}
    words: dict[str, tuple[int, list[str]]] = {}
    with gzip.open(_DICT, "rt", encoding="utf-8") as f:
        for line in f:
            word, reading, freq = line.rstrip("\n").split("\t")
            freq = int(freq)
            readings = words.setdefault(word, (freq, []))[1]
            readings.append(reading)
    for word, (freq, readings) in words.items():
        keys = {_key(r): r for r in readings}
        if len(word) > 1:
            spoken = _pypinyin_reading(word)
            keys.setdefault(_key(spoken), spoken)
        for key, reading in keys.items():
            index.setdefault(key, []).append((word, reading, freq))
    return index, words


def load() -> dict:
    """The reading index, built (and cached) on first use. Safe to call from any thread."""
    global _index, _words
    with _lock:
        if _index is None:
            try:
                version, index, words = pickle.loads(_CACHE.read_bytes())
                if version == _CACHE_VERSION:
                    _index, _words = index, words
            except (OSError, ValueError, pickle.PickleError, EOFError):
                pass
            if _index is None:
                log.info("building word index…")
                index, words = _build()
                _CACHE.parent.mkdir(parents=True, exist_ok=True)
                _CACHE.write_bytes(pickle.dumps((_CACHE_VERSION, index, words)))
                _OLD_CACHE.unlink(missing_ok=True)
                _words, _index = words, index
                log.info("word index: %d words, %d readings", len(_words), len(_index))
        return _index


def is_word(word: str) -> bool | None:
    """Whether word (Traditional Chinese) is a dictionary word; None while the dictionary is still loading
    (never blocks)."""
    if _index is None:
        return None
    return word in _words


def frequency(word: str) -> int:
    """How common word is (0 if unknown or still loading)."""
    return _words.get(word, (0, []))[0]


def preload() -> None:
    threading.Thread(target=load, daemon=True).start()


def _readings(word: str) -> list[str]:
    """Toned readings of word: the dictionary's and the spoken one (pypinyin), else character by character
    (first-listed reading)."""
    if word in _words:
        readings = list(_words[word][1])
        if len(word) > 1 and (spoken := _pypinyin_reading(word)) not in readings:
            readings.append(spoken)
        return readings
    return [" ".join(_words[c][1][0] if c in _words else _pypinyin_reading(c) for c in word)]


def rank_of(word: str, other: str) -> int | None:
    """How close other sounds to word, as in ranked (0 / 1 / 2), or None; for words the dictionary lacks (the
    user's hotwords: 光暈 is not in it)."""
    if len(word) != len(other):
        return None
    load()
    best = None
    for a in _readings(word):
        for b in _readings(other):
            r = 0 if a == b else 1 if _TONES.sub("", a) == _TONES.sub("", b) else 2 if _key(a) == _key(b) else None
            if r is not None and (best is None or r < best):
                best = r
    return best


def sounds_alike(a: str, b: str) -> bool:
    """Whether b (Traditional Chinese, as written) sounds like a, character by character, without tones and with
    the fuzzy pairs: a spoken command the recognizer wrote as a homophone (金嘆號 for the user's 驚嘆號, said jin;
    換一航). Any reading of a 多音字 in a counts (行 is hang in 換一行), b only as read in its words (還行 is hai
    xing, not 換行). Only for short phrases."""
    if len(a) != len(b) or not _CJK.match(a) or not _CJK.match(b):
        return False
    load()
    said = [_key(s) for s in _pypinyin_reading(b).split()]
    if len(said) != len(b):
        return False
    return all(x == y or k in {_key(r) for r in (_words[x][1] if x in _words else [_pypinyin_reading(x)])}
               for x, y, k in zip(a, b, said))


COMMON = 5   # frequency from which a word counts as common (McBopomofo lists many obscure words at 1-2)


def homophones(word: str, limit: int = 8) -> list[str]:
    """Words that sound like word (Traditional Chinese), best first: common words before rare ones, then the same
    reading with tones, without tones, fuzzy, then frequency; word itself excluded."""
    found = ranked(word)
    # rare entries (逆號, 塵事: frequency 1) go last whatever their reading: common words are what the user means
    return sorted(found, key=lambda w: (-found[w][1] < COMMON, found[w]))[:limit]


def ranked(word: str) -> dict[str, tuple[int, int]]:
    """Words that sound like word -> (rank, -frequency); rank 0: the same reading with tones, 1: without tones,
    2: fuzzy."""
    word = word.strip()
    if not _CJK.match(word) or len(word) > 6:
        return {}
    index = load()
    readings = _readings(word)
    found: dict[str, tuple[int, int]] = {}
    for reading in readings:
        toneless = _TONES.sub("", reading)
        for w, r, freq in index.get(_key(reading), []):
            rank = 0 if r == reading else 1 if _TONES.sub("", r) == toneless else 2
            if w != word and (w not in found or rank < found[w][0]):
                found[w] = (rank, -freq)
    return found
