"""Other ways to write a selected number or letters-and-digits word, for the 選字 menu (2026-10-22, the user's
request): a number as Chinese (一百二十三, 一二三 digit by digit, 壹佰貳拾參 as on a cheque) and full-width (１２３);
letters with digits in other cases (a12 -> A12) and full-width (Ａ１２). Not learned: numbers differ every time."""
import re

_NUMBER = re.compile(r"[0-9０-９]+(?:[.．][0-9０-９]+)?")
_WORD = re.compile(r"[0-9A-Za-z０-９Ａ-Ｚａ-ｚ]{1,20}")
_DIGITS = "零一二三四五六七八九"
_CAPITAL = "零壹貳參肆伍陸柒捌玖"
_UNITS = ("", "十", "百", "千")
_CAPITAL_UNITS = ("", "拾", "佰", "仟")
_GROUPS = ("", "萬", "億", "兆")
_TO_HALF = {c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}
_TO_FULL = {c: c + 0xFEE0 for c in range(0x21, 0x7F)}


def half(text: str) -> str:
    return text.translate(_TO_HALF)


def full(text: str) -> str:
    return text.translate(_TO_FULL)


def is_number_word(text: str) -> bool:
    """A number (123, 3.14) or a word of letters and digits (a12, 2B), half- or full-width."""
    t = text.strip()
    return bool(_NUMBER.fullmatch(t) or _WORD.fullmatch(t) and any(c.isdigit() for c in t))


def _integer(digits: str, capital: bool = False) -> str:
    """2026 -> 二千零二十六 (capital: 貳仟零貳拾陸); groups of four digits under 萬 / 億 / 兆."""
    names, units = (_CAPITAL, _CAPITAL_UNITS) if capital else (_DIGITS, _UNITS)
    n = int(digits)
    if n == 0:
        return names[0]
    groups = []
    while n:
        groups.append(n % 10000)
        n //= 10000
    out, gap = "", False   # gap: a whole group of zeros since the last one written
    for gi in range(len(groups) - 1, -1, -1):
        g = groups[gi]
        if g == 0:
            gap = bool(out)
            continue
        if out and (gap or g < 1000):
            out += names[0]   # 十萬零一十, 一億零一
        part, inner = "", False
        for ui in range(3, -1, -1):
            d = g // 10 ** ui % 10
            if d == 0:
                inner = bool(part)
                continue
            if inner:
                part += names[0]   # 一千零二
                inner = False
            part += names[d] + units[ui]
        out += part + _GROUPS[gi]
        gap = False
    if not capital and out.startswith("一十"):
        out = out[1:]   # 十五, not 一十五
    return out


def chinese(text: str) -> list[str]:
    """123 -> [一百二十三, 一二三, 壹佰貳拾參]; 3.14 -> [三點一四]; 007 -> [〇〇七]."""
    t = half(text.strip())
    whole, _, frac = t.partition(".")
    by_digit = "".join("〇一二三四五六七八九"[int(c)] for c in whole)
    if frac:
        tail = "點" + "".join(_DIGITS[int(c)] for c in frac)
        return [(_integer(whole) if len(whole) <= 16 else by_digit) + tail]
    if len(whole) > 16 or len(whole) > 1 and whole[0] == "0":
        return [by_digit]
    out = [_integer(whole)]
    if len(whole) > 1:
        out.append(by_digit)
    out.append(_integer(whole, capital=True))
    return list(dict.fromkeys(out))


def cases(text: str) -> list[str]:
    """a12b -> [A12B, A12b]: all capitals, all small, the first letter a capital; not the text itself."""
    t = text.strip()
    first = next((i for i, c in enumerate(t) if c.isalpha()), None)
    forms = [t.upper(), t.lower()]
    if first is not None:
        forms.append(t[:first] + t[first].upper() + t[first + 1:].lower())
    return [f for f in dict.fromkeys(forms) if f != t]


def tabs(text: str) -> list[tuple[str, list[str]]]:
    """The 選字 menu's tabs for a number or a letters-and-digits word; empty ones left out."""
    t = text.strip()
    out = []
    if _NUMBER.fullmatch(t):
        out.append(("中文", chinese(t)))
    else:
        out.append(("大小寫", cases(t)))
    widths = list(dict.fromkeys(f for w in [t] + (cases(t) if not _NUMBER.fullmatch(t) else [])
                                for f in (half(w) if w != half(w) else full(w),)))
    out.append(("半形" if t != half(t) else "全形", [w for w in widths if w != t]))
    return [(name, words) for name, words in out if words]


_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
         "seventeen eighteen nineteen").split()
_TENS = {w: 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)}
_SCALES = {"thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9}
_EN_WORD = re.compile(r"[A-Za-z]+")


def english(text: str) -> str | None:
    """English number words as digits (2026-10-22, the user's request: X-ASR writes counting as words): One, two ->
    1, 2; twenty-one -> 21; one hundred and five -> 105; one two three -> 1 2 3. None when there are none."""
    t = text.strip()
    if len(t) > 60:
        return None
    out, runs, pos = [], [], 0   # runs: [start, end, value pieces] of number words
    words = list(_EN_WORD.finditer(t))
    for i, m in enumerate(words):
        w = m.group().lower()
        kind = "one" if w in _ONES else "ten" if w in _TENS else "hundred" if w == "hundred" \
            else "scale" if w in _SCALES else "and" if w == "and" else None
        last = runs[-1] if runs else None
        joined = last is not None and last[1] == words[i - 1].end() and t[last[1]:m.start()].strip(" -") == ""
        if kind == "and":
            nxt = words[i + 1].group().lower() if i + 1 < len(words) else ""
            if joined and last[3] in ("hundred", "scale") and (nxt in _ONES or nxt in _TENS):
                last[1] = m.end()
            continue
        if kind is None:
            continue
        # a new number: nothing to join, or two that cannot be one (one two, twenty thirty)
        if not joined or kind == "one" and last[3] in ("one",) or kind == "ten" and last[3] in ("one", "ten") \
                or kind == "one" and last[3] == "ten" and last[4] % 10:
            runs.append([m.start(), m.end(), 0, kind, 0])   # start, end, total, last kind, current
            last = runs[-1]
        last[1], last[3] = m.end(), kind
        if kind == "one":
            last[4] += _ONES.index(w)
        elif kind == "ten":
            last[4] += _TENS[w]
        elif kind == "hundred":
            last[4] = (last[4] or 1) * 100
        else:
            last[2] += (last[4] or 1) * _SCALES[w]
            last[4] = 0
    if not runs:
        return None
    for start, end, total, _, current in runs:
        out.append(t[pos:start] + str(total + current))
        pos = end
    return "".join(out) + t[pos:]
