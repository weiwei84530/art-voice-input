"""What an utterance means for selected text, and punctuation names.

Speaking with text selected replaces it (as typing would). Deleting it is a custom operation (刪除, rules.py).

A bare punctuation name (逗號, 句號, 驚嘆號 …) is typed as the mark itself; only when the whole utterance is exactly
the name, so 逗號很重要 is dictated as spoken. Other spoken phrases (換行, 送出) are custom operations (rules.py).

A character described by a word (「節日的節」, a setting since 2026-10-11): an utterance that is exactly <word>的<one
character> types only that character, when the word contains it or a character that sounds like it (X-ASR may write
節日的結: the 節 of 節日 is typed). This is how people in Taiwan say which character they mean; a word said in natural
Chinese is recognized far more reliably than Bopomofo names (spelling with ㄔ ㄤ 昌 was tried and reverted the same
day: X-ASR heard the names as English letters).

An utterance on a selected 。 (setting, 2026-10-07) continues the sentence: the 。 becomes ， and moves to the end
(今天很好。明天 → 今天很好，我們去公園。明天).
"""
import re

from pypinyin import Style, pinyin

# 驚歎號 is how X-ASR may write 驚嘆號; 感嘆號 and 點點點 dropped, 逗點 / 破折號 / 斜線 added (2026-10-22, the user's
# choice)
SYMBOLS = {"逗號": "，", "逗點": "，", "句號": "。", "句點": "。", "頓號": "、", "問號": "？", "驚嘆號": "！",
           "驚歎號": "！", "分號": "；", "冒號": "：", "刪節號": "……", "省略號": "……", "破折號": "——",
           "斜線": "／", "斜槓": "／"}
# the marks a commit's added 。 gives way to when said right after it (not —— or ／)
MARKS = {"，", "。", "、", "？", "！", "；", "：", "……"}

_PUNCT = re.compile(r"[\s，。、！？；：,.!?;:…]+")
_TRAILING = re.compile(r"[。，,.！？!?；;]+$")


def symbol(formatted: str) -> str | None:
    """The punctuation mark when the whole utterance is its name (逗號 / 逗號。), else None."""
    return SYMBOLS.get(_PUNCT.sub("", formatted))


_DESCRIBED = re.compile(r"^([㐀-䶿一-鿿]{2,6})的([㐀-䶿一-鿿])$")


def _sounds(ch: str) -> set[str]:
    return set(pinyin(ch, style=Style.NORMAL, heteronym=True)[0])


def described(formatted: str) -> str | None:
    """The character when the whole utterance is <word>的<character> (節日的節 -> 節), else None. The part before 的
    must be one dictionary word, nothing else (2026-10-16, the user's rule, so the user knows what they are doing:
    只是顯示的是 typed 是; lead-ins such as 這個字是教育的育 no longer count, and the setting turns it all off). The
    word holds the character, or one that sounds like it (X-ASR wrote 一張的章, 節日的結: the word's is typed)."""
    from . import candidates
    m = _DESCRIBED.match(_PUNCT.sub("", formatted))
    if not m:
        return None
    word, ch = m.groups()
    if not candidates.is_word(word):
        return None
    if ch in word:
        return ch
    return next((c for c in reversed(word) if _sounds(c) & _sounds(ch)), None)


def continue_sentence(formatted: str) -> str:
    """The replacement for a selected 。: ， + the utterance + 。"""
    return "，" + _TRAILING.sub("", formatted.strip()) + "。"


_SPELLED = re.compile(r"\s*((?:[A-Za-z]\s+)+[A-Za-z])\s*[.。,，!！?？]?\s*")
_LATIN_WORD = re.compile(r"(\W*)([A-Za-z](?:[A-Za-z0-9'_ -]*[A-Za-z0-9])?)(\W*)")


def spelled(selected: str, raw: str) -> tuple[str, str, str] | None:
    """Letters spelled over a selected English word (2026-10-13, the user's request): B L I P over Bleep types Blip,
    A P P over API types APP, D O G over doggy types dog: the letters written in the selection's case (all
    capitals, a capital first, or lower case), the selection's surrounding punctuation kept. raw is the recognizer's
    text (X-ASR writes spelled letters as "B L I P."). Returns (replacement, old word, new word)."""
    m, w = _SPELLED.fullmatch(raw), _LATIN_WORD.fullmatch(selected)
    if not m or not w:
        return None
    letters = re.sub(r"\s+", "", m.group(1)).lower()
    word = w.group(2)
    cased = [c for c in word if c.isalpha()]
    if len(cased) > 1 and all(c.isupper() for c in cased):
        new = letters.upper()
    elif word[0].isupper():
        new = letters.capitalize()
    else:
        new = letters
    return w.group(1) + new + w.group(3), word, new


def replacement(selected: str, formatted: str) -> str:
    """The text that replaces a selection: sentence-final punctuation only if the selection had some."""
    text = formatted.strip()
    if not _TRAILING.search(selected):
        text = _TRAILING.sub("", text)
    return text

