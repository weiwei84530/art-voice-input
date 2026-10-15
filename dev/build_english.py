r"""Build voiceinput/dict/english.tsv.gz, the common English words 選字 offers as near sounds (2026-10-16).

  .venv\Scripts\python.exe dev\build_english.py <cmudict.dict> [count]

Words: the most frequent English words (wordfreq 3.1.1, its data CC BY-SA 4.0: install it apart, e.g.
`uv pip install --target <dir> wordfreq` and put <dir> on PYTHONPATH; it is not an app dependency) that the CMU
Pronouncing Dictionary lists (BSD; https://github.com/cmusphinx/cmudict at 74790861f652b15e4ac49015a90074ad62a27690,
file cmudict.dict). Each line: word, zipf frequency x 100, its pronunciations (ARPAbet without stress marks,
separated by |). The rest of the dictionary follows with frequency 0: never offered, only used to know how a
selected word is said (Bleep is not among the common words).
"""
import gzip
import re
import sys
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

OUT = Path(__file__).resolve().parent.parent / "voiceinput" / "dict" / "english.tsv.gz"
# never offered: a near sound of an ordinary word should not be an insult
_BLOCK = {"shit", "fuck", "fucking", "fucked", "cunt", "bitch", "dick", "cock", "pussy", "slut", "whore", "nigger",
          "nigga", "fag", "faggot", "retard", "retarded", "asshole", "bastard", "damn", "piss", "tits", "boobs",
          "porn", "sex", "sexy", "rape", "nazi", "dildo", "anal", "penis", "vagina", "horny", "cum", "jizz"}


def main():
    cmu: dict[str, list[str]] = {}
    for line in open(sys.argv[1], encoding="utf-8"):
        line = line.split("#")[0].strip()
        if not line:
            continue
        word, *phones = line.split()
        word = re.sub(r"\(\d+\)$", "", word)
        pron = " ".join(re.sub(r"\d", "", p) for p in phones)
        if pron not in cmu.setdefault(word, []):
            cmu[word].append(pron)
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 30000
    rows = []
    for word in top_n_list("en", count * 3):
        if len(rows) >= count:
            break
        if not re.fullmatch(r"[a-z]{2,}", word) or word in _BLOCK or word not in cmu:
            continue
        rows.append(f"{word}\t{round(zipf_frequency(word, 'en') * 100)}\t{'|'.join(cmu[word])}\n")
    common = {r.split("\t")[0] for r in rows}
    print(f"{len(rows)} common words")
    rows += [f"{w}\t0\t{'|'.join(p)}\n" for w, p in cmu.items()
             if re.fullmatch(r"[a-z]{2,}", w) and w not in common and w not in _BLOCK]
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        f.writelines(rows)
    print(f"{len(rows)} words -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
