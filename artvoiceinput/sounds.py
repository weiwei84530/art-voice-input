"""English words that sound like a selection, for 選字 (2026-10-13): clock code -> Claude Code, lanchin ->
LangChain, Deepsec -> DeepSeek, Laura -> LoRA. Only known terms are offered (the user's list, ticked term packs,
English terms on screen): a misheard word cannot be turned into one nobody listed.

A rough consonant skeleton (key) is compared by edit distance, and the plain letters by difflib; the better of the
two counts. The key forgives what X-ASR mixes up with a Taiwanese accent: voicing (b/p, d/t, g/k, v/f, z/s), ng/n,
vowels, a doubled letter. A short acronym is read as letter names first (CNS -> "si en es", near Seedance). Tested
on the TTS mishearings of the AI pack (dev experiment 2026-10-13): 20 of 22 targets first, Claude for clock and
Gemini for Jimmy second; ordinary words (email, meeting) get look-alikes scoring up to ~0.67.
"""
import gzip
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

THRESHOLD = 0.6

_RULES = [(r"ph", "f"), (r"gh", ""), (r"ck", "k"), (r"sch", "sk"), (r"[cs]h", "x"), (r"th", "t"), (r"wh", "w"),
          (r"qu", "kw"), (r"q", "k"), (r"x", "ks"), (r"c(?=[eiy])", "s"), (r"c", "k"), (r"dg", "j"),
          (r"g(?=[eiy])", "j"), (r"ng", "n"), (r"b", "p"), (r"d", "t"), (r"g", "k"), (r"v", "f"), (r"z", "s"),
          (r"j", "x"), (r"h", ""), (r"(?<=.)[aeiouy]+", ""), (r"^[aeiouy]+", "a"), (r"w(?![aeiouy])", ""),
          (r"(.)\1+", r"\1")]
_RULES = [(re.compile(a), b) for a, b in _RULES]
_LETTERS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                    "ei bi si di i ef ji eich ai jei kei el em en ou pi kiu ar es ti iu vi dabliu eks wai zi".split()))
_ACRONYM = re.compile(r"\b[A-Z]{2,4}\b")


def _spoken(text: str) -> str:
    """CNS -> si en es: a short all-capital word is what X-ASR writes for letter names."""
    return _ACRONYM.sub(lambda m: " ".join(_LETTERS[c] for c in m.group()), text)


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def key(text: str) -> str:
    s = _letters(text)
    for pattern, repl in _RULES:
        s = pattern.sub(repl, s)
    return s


def _distance(a: str, b: str) -> float:
    """Edit distance; a different last sound costs half (clock / Claude: klk / klt)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            sub = 0 if ca == cb else 0.5 if i == len(a) and j == len(b) else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + sub))
        prev = cur
    return prev[-1]


def similarity(heard: str, term: str) -> float:
    best = 0.0
    for h in dict.fromkeys((heard, _spoken(heard))):
        ka, kb = key(h), key(term)
        by_key = 1 - _distance(ka, kb) / max(len(ka), len(kb), 1)
        by_letters = SequenceMatcher(None, _letters(h), _letters(term)).ratio()
        best = max(best, by_key, by_letters)
    return best


def alike(heard: str, terms, limit: int = 4) -> list[str]:
    """Known terms that sound like heard, best first (ties keep the order of terms); never heard itself."""
    scored = []
    for i, term in enumerate(dict.fromkeys(terms)):
        if term == heard.strip():
            continue
        s = similarity(heard, term)
        if s >= THRESHOLD:
            scored.append((-s, i, term))
    return [t for _, _, t in sorted(scored)[:limit]]


# --- common English words that sound alike (2026-10-16, the user's request: 選字 on an English word should offer
# near sounds, not only known terms) ---
_ENGLISH = Path(__file__).resolve().parent / "dict" / "english.tsv.gz"
_VOWELS = set("AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW".split())
_PAIRS = {frozenset(p.split()) for p in ("B P", "D T", "G K", "V F", "Z S", "ZH SH", "DH TH", "JH CH", "M N", "N NG",
                                 "TH F", "DH D", "L R", "W V", "S SH", "Z ZH")}
_english: list | None = None   # [(word, zipf, pronunciations, key)]
_by_word: dict = {}
_english_lock = threading.Lock()


def _load_english() -> list:
    global _english
    with _english_lock:
        if _english is None:
            rows = []
            with gzip.open(_ENGLISH, "rt", encoding="utf-8") as f:
                for line in f:
                    word, zipf, prons = line.rstrip("\n").split("\t")
                    prons = [p.split() for p in prons.split("|")]
                    if zipf == "0":   # only how a selected word is said
                        _by_word[word] = (word, 0, prons, "")
                    else:
                        rows.append((word, int(zipf) / 100, prons, key(word)))
            _by_word.update((r[0], r) for r in rows)
            _english = rows
        return _english


def preload_english():
    threading.Thread(target=_load_english, daemon=True).start()


def _phone_cost(a: str, b: str) -> float:
    if a == b:
        return 0
    if a in _VOWELS and b in _VOWELS:
        return 0.5
    return 0.5 if frozenset((a, b)) in _PAIRS else 1


def _phone_distance(a: list, b: list) -> float:
    prev = [j * 1.0 for j in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        cur = [float(i)]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + _phone_cost(ca, cb)))
        prev = cur
    return prev[-1]


def _by_phones(pa: list, pb: list) -> float:
    return max(1 - _phone_distance(x, y) / max(len(x), len(y)) for x in pa for y in pb)


def _cased(word: str, like: str) -> str:
    """word written in the case of like: all capitals, a capital first, or lower case."""
    letters = [c for c in like if c.isalpha()]
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return word.upper()
    return word.capitalize() if like[:1].isupper() else word


def _near_score(low: str, kh: str, mine, word: str, prons) -> float:
    """How much word sounds like the heard word low (consonant skeleton kh, pronunciations mine or None)."""
    k = key(word)
    by_key = 1 - _distance(kh, k) / max(len(kh), len(k), 1)
    if by_key < 0.5:
        return 0.0
    by_letters = SequenceMatcher(None, low, word.lower()).ratio()
    if mine is not None and prons:   # how both are said, mostly; the letters break ties
        return 0.75 * _by_phones(mine[2], prons) + 0.25 * by_letters
    return max(by_key * 0.9, by_letters)


def near(heard: str, known=(), limit: int = 10) -> list[str]:
    """Words that sound like one English word heard, best first: common English words (english.tsv.gz) and the
    known terms together (the user's choice, 2026-10-16), a known term a little ahead at the same similarity.
    Compared by pronunciations when both are in CMUdict, else by the consonant skeleton and the letters; a more
    frequent word goes first among near equals. Never heard itself."""
    h = heard.strip()
    low = h.lower()
    if not re.fullmatch(r"[A-Za-z]+", h):
        return []
    rows = _load_english()
    kh = key(h)
    mine = _by_word.get(low)
    scored = {}
    for word, zipf, prons, k in rows:
        if word == low or abs(len(k) - len(kh)) > 2 or abs(len(word) - len(low)) > 4:
            continue
        s = _near_score(low, kh, mine, word, prons)
        if s >= THRESHOLD:
            scored[word] = (s + zipf * 0.01, _cased(word, h))
    for term in dict.fromkeys(known):   # written as known (claude is a common word too: Claude once)
        t = term.lower()
        if t == low or not re.fullmatch(r"[a-z]+", t):
            continue
        s = _near_score(low, kh, mine, t, _by_word.get(t, (0, 0, None))[2])
        if s >= THRESHOLD:
            scored[t] = (max(s + 0.08, scored.get(t, (0,))[0]), term)
    return [w for _, w in sorted(scored.values(), key=lambda sw: -sw[0])[:limit]]
