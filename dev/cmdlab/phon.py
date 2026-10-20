"""Method E: the first decode, Chinese or English, as a coarse phone sequence compared with each command's
(weighted edit distance). X-ASR writes a command it misses mostly as English (刪除 -> Central, 復原 -> Full you,
換行 -> Hang kong), which a Chinese-only reading cannot match."""
import gzip
import re
from functools import lru_cache

from common import ROOT

_INI = {"b": "P", "p": "P", "m": "M", "f": "F", "d": "T", "t": "T", "n": "N", "l": "L", "g": "K", "k": "K",
        "h": "H", "j": "C", "q": "C", "x": "S", "zh": "C", "ch": "C", "sh": "S", "r": "L", "z": "C", "c": "C",
        "s": "S", "y": "Y", "w": "W", "": ""}
_FIN = {"a": "A", "ai": "A I", "an": "A N", "ang": "A NG", "ao": "A U", "e": "O", "ei": "E I", "en": "O N",
        "eng": "O NG", "er": "O L", "i": "I", "ia": "Y A", "ian": "Y E N", "iang": "Y A NG", "iao": "Y A U",
        "ie": "Y E", "in": "I N", "ing": "I NG", "iong": "Y U NG", "iu": "Y O U", "o": "O", "ong": "U NG",
        "ou": "O U", "u": "U", "ua": "W A", "uai": "W A I", "uan": "W A N", "uang": "W A NG", "ui": "W E I",
        "un": "W O N", "uo": "W O", "v": "I", "ve": "Y E", "van": "Y E N", "vn": "I N", "ue": "Y E", "n": "N",
        "ng": "NG", "m": "M"}
_ARPA = {"AA": "A", "AE": "A", "AH": "A", "AO": "O", "AW": "A U", "AY": "A I", "EH": "E", "ER": "O L", "EY": "E I",
         "IH": "I", "IY": "I", "OW": "O U", "OY": "O I", "UH": "U", "UW": "U", "B": "P", "P": "P", "CH": "C",
         "JH": "C", "D": "T", "T": "T", "DH": "T", "TH": "S", "F": "F", "V": "F", "G": "K", "K": "K", "HH": "H",
         "L": "L", "R": "L", "M": "M", "N": "N", "NG": "NG", "S": "S", "SH": "S", "Z": "S", "ZH": "S", "W": "W",
         "Y": "Y"}
VOWELS = set("AEIOU")
_NEAR = [{"H", "F"}, {"N", "NG"}, {"N", "M"}, {"N", "L"}, {"C", "S"}, {"P", "F"}, {"T", "C"}, {"W", "U"},
         {"Y", "I"}, {"K", "H"}]
_CJK = re.compile(r"[㐀-䶿一-鿿]")
_TOKEN = re.compile(r"[㐀-䶿一-鿿]+|[A-Za-z']+")   # a Chinese run at once: 行 in 換行 is hang


@lru_cache(maxsize=1)
def _english():
    out = {}
    with gzip.open(ROOT / "artvoiceinput" / "dict" / "english.tsv.gz", "rt", encoding="utf-8") as f:
        for line in f:
            w, _, pron = line.rstrip("\n").split("\t")
            out.setdefault(w, pron.split("|")[0])
    return out


def _pinyin_phones(ch):
    from pypinyin import Style, lazy_pinyin
    from pypinyin.contrib.tone_convert import to_finals, to_initials
    from artvoiceinput.textfmt import to_simplified
    out = []
    for p in lazy_pinyin(to_simplified(ch), style=Style.NORMAL):
        ini, fin = to_initials(p, strict=False), to_finals(p, strict=False).replace("ü", "v")
        if ini in ("j", "q", "x", "y") and fin.startswith("u"):
            fin = "v" + fin[1:]
        if ini in ("zh", "ch", "sh", "r", "z", "c", "s") and fin == "i":
            fin = "e"
        out += [_INI.get(ini, "")] + _FIN.get(fin, fin.upper()).split()
    return [x for x in out if x]


def phones(text):
    """Coarse phones of a decode, None when an English word is not in the dictionary."""
    out = []
    eng = _english()
    for tok in _TOKEN.findall(text):
        if _CJK.match(tok):
            out += _pinyin_phones(tok)
        else:
            pron = eng.get(tok.lower())
            if pron is None:
                return None
            for p in pron.split():
                out += _ARPA[re.sub(r"\d", "", p)].split()
    return out


def _sub(a, b):
    if a == b:
        return 0.0
    if a in VOWELS and b in VOWELS:
        return 0.5
    if any({a, b} <= g for g in _NEAR):
        return 0.5
    return 1.0


def _indel(a):
    return 0.5 if a in VOWELS or a in ("Y", "W", "H") else 0.8


def distance(a, b):
    d = [[0.0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        d[i][0] = d[i - 1][0] + _indel(a[i - 1])
    for j in range(1, len(b) + 1):
        d[0][j] = d[0][j - 1] + _indel(b[j - 1])
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + _indel(a[i - 1]), d[i][j - 1] + _indel(b[j - 1]),
                          d[i - 1][j - 1] + _sub(a[i - 1], b[j - 1]))
    return d[-1][-1]


@lru_cache(maxsize=None)
def _cmd_phones(c):
    return tuple(phones(c))


def closest(text, cmds):
    """(command, distance / its phone count) of the closest command, or (None, inf)."""
    p = phones(text)
    if not p:
        return None, float("inf")
    best = (None, float("inf"))
    for c in cmds:
        cp = _cmd_phones(c)
        k = distance(p, cp) / len(cp)
        if k < best[1]:
            best = (c, k)
    return best
