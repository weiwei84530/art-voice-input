"""Scores every method on the lab's samples (results.jsonl, kws_zhen.jsonl) and writes out/report.json plus
out/queue.jsonl: the samples whose label is unknown and that some method takes for a command, for the user to label.

Labels: pos samples carry the command the app ran; labels.json (from label.py) adds or overrides labels:
wav -> a command phrase, "text" (real speech, no command), "noise" (no speech), "skip" (cannot tell)."""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import OUT, commands, norm  # noqa: E402

CMDS = list(commands())
NORM = {norm(c): c for c in CMDS}
_CJK = re.compile(r"[㐀-䶿一-鿿]")

# --- method D: the first decode's reading, compared with each command's -------------------------------------------
_NEAR_INITIALS = [{"z", "zh"}, {"c", "ch"}, {"s", "sh"}, {"n", "l"}, {"f", "h"}, {"b", "p"}, {"d", "t"}, {"g", "k"},
                  {"h", "k"}]
_NEAR_FINALS = [{"an", "ang"}, {"en", "eng"}, {"in", "ing"}, {"ian", "iang"}, {"uan", "uang"}, {"an", "uan"},
                {"ang", "uang"}, {"un", "ong"}, {"ao", "ou"}, {"e", "o"}]


def _split(syl):
    from pypinyin.contrib.tone_convert import to_finals, to_initials
    return to_initials(syl, strict=False), to_finals(syl, strict=False)


def _syls(text):
    from pypinyin import Style, lazy_pinyin
    from artvoiceinput.textfmt import to_simplified
    return [_split(p) for p in lazy_pinyin(to_simplified("".join(_CJK.findall(text))), style=Style.NORMAL)]


def _syl_cost(a, b):
    (ia, fa), (ib, fb) = a, b
    ci = 0 if ia == ib else (0.5 if any({ia, ib} <= g for g in _NEAR_INITIALS) else 1)
    cf = 0 if fa == fb else (0.5 if any({fa, fb} <= g for g in _NEAR_FINALS) else 1)
    return min(1.0, ci + cf)


_CMD_SYLS = {}


def method_d(raw1: str, short: bool, limit: float):
    """A command whose reading is within `limit` of the first decode's Chinese (same syllable count)."""
    if not short or not raw1 or re.search(r"[A-Za-z]", raw1):
        return None
    s = _syls(raw1)
    best, cost = None, 99
    for c in CMDS:
        cs = _CMD_SYLS.setdefault(c, _syls(c))
        if len(cs) != len(s):
            continue
        k = sum(_syl_cost(x, y) for x, y in zip(s, cs))
        if k < cost and any(x == y for x, y in zip(s, cs)):
            best, cost = c, k
    return best if cost <= limit else None


# --- the rest ------------------------------------------------------------------------------------------------------
def method_a(r, margin: float, gate_short=True):
    if "top" not in r or (gate_short and not r["short"]):
        return None
    c, lp = r["top"][0]
    return c if lp - r["lp_free"] >= margin else None


def kws_hit(k, th, r):
    if k is None or not r["short"]:
        return None
    hits = k.get(str(th)) or []
    return hits[-1] if hits else None


def load():
    samples = {json.loads(l)["wav"]: json.loads(l) for l in (OUT / "samples.jsonl").open(encoding="utf-8")}
    res = {json.loads(l)["wav"]: json.loads(l) for l in (OUT / "results.jsonl").open(encoding="utf-8")}
    kws = {}
    p = OUT / "kws_zhen.jsonl"
    if p.exists():
        kws = {json.loads(l)["wav"]: json.loads(l) for l in p.open(encoding="utf-8")}
    labels = {}
    if (OUT / "labels.json").exists():
        labels = json.loads((OUT / "labels.json").read_text(encoding="utf-8"))
    return samples, res, kws, labels


def methods():
    """name -> f(r, k) -> command or None; r: results row, k: kws row."""
    m = {"現況（一般解碼＋加權再解碼）": lambda r, k: r.get("base"),
         "只有一般解碼（不加權再解碼）": lambda r, k: NORM.get(norm(r["raw1"]))}
    first = m["只有一般解碼（不加權再解碼）"]
    for th in (0.05, 0.1, 0.2, 0.3):
        m[f"B 關鍵詞模型 {th}"] = lambda r, k, th=th: kws_hit(k, th, r)
        m[f"現況 + B {th}"] = lambda r, k, th=th: r.get("base") or kws_hit(k, th, r)
    for lim in (0.5, 1.0):
        m[f"D 拼音比對 ≤{lim}"] = lambda r, k, lim=lim: first(r, k) or method_d(r["raw1"], r["short"], lim)
        m[f"現況 + D ≤{lim}"] = lambda r, k, lim=lim: r.get("base") or method_d(r["raw1"], r["short"], lim)
    from phon import closest

    def method_e(r, lim):
        if not r["short"]:
            return None
        c, k = closest(r["raw1"], CMDS)
        return c if k <= lim else None
    for lim in (0.1, 0.2, 0.3, 0.4):
        m[f"E 音譯比對 ≤{lim}"] = lambda r, k, lim=lim: first(r, k) or method_e(r, lim)
    for mg in (0, -1, -2, -3, -4, -5, -6, -8):
        m[f"A 分數比對 ≥{mg}"] = lambda r, k, mg=mg: first(r, k) or method_a(r, mg)
        m[f"現況 + A ≥{mg}"] = lambda r, k, mg=mg: r.get("base") or method_a(r, mg)
    return m


def truth(s, labels):
    """The command a sample is, "" for none, None when unknown."""
    lab = labels.get(s["wav"])
    if lab is not None:
        return None if lab == "skip" else ("" if lab in ("text", "noise") else lab)
    if s["kind"] == "pos":
        return s["label"]
    if s["kind"] == "neg":
        return ""
    return None


def main():
    samples, res, kws, labels = load()
    ms = methods()
    stats = {name: Counter() for name in ms}
    queue = {}
    for wav, r in res.items():
        s = samples[wav]
        k = kws.get(wav)
        t = truth(s, labels)
        outs = {name: f(r, k) for name, f in ms.items()}
        # the queue: continuous listening only (press-and-talk files keep the start sound the app cut out before
        # recognizing), and not from E, which the data already rules out (it flags hundreds of plain words)
        guesses = {v for n, v in outs.items() if v and not n.startswith("E ")}
        if s["era"] != "cont":
            guesses = set()
        # unknown, or a text piece some method takes for a command, or a command the app ran that the plain
        # current path now reads otherwise (the app's own label may be wrong: 括號 at 200% heard for 逗號)
        doubt = s["kind"] == "pos" and s["era"] == "cont" and r.get("base") != s["label"]
        if wav not in labels and (t is None and guesses or s["kind"] == "neg" and guesses or doubt):
            guesses = guesses | ({s["label"]} if s["kind"] == "pos" else set())
            queue[wav] = {"wav": wav, "kind": s["kind"], "era": s["era"], "asr": s["asr"], "raw1": r["raw1"],
                          "guesses": sorted(guesses), "dur": r["dur"]}
        if t is None:
            continue
        for name, got in outs.items():
            st = stats[name]
            if t:
                st["cmd"] += 1
                st["hit" if got == t else ("wrong" if got else "miss")] += 1
                if s["era"] == "cont":
                    st["cmd_cont"] += 1
                    st["hit_cont" if got == t else "miss_cont"] += 1
            else:
                st["non"] += 1
                if got:
                    st["false"] += 1
                    if r["short"]:
                        st["false_short"] += 1
    with (OUT / "queue.jsonl").open("w", encoding="utf-8") as f:
        for q in queue.values():
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    rows = []
    for name, st in stats.items():
        rows.append({"method": name, **st})
        print(f"{name:28s} 命中 {st['hit']:4d}/{st['cmd']:4d}  認成別的 {st['wrong']:3d}  漏 {st['miss']:4d}  "
              f"誤觸 {st['false']:3d}/{st['non']:4d}")
    (OUT / "report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("queue:", len(queue), Counter(q["kind"] for q in queue.values()))


if __name__ == "__main__":
    main()
