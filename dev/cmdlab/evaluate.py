"""Runs every sample through the app's current command path (baseline) and the closed-set scorer (method A); writes
out/results.jsonl. Text-only methods (D) and the keyword spotter (B) are evaluated from / beside it."""
import json
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from common import OUT, REC, commands, config, norm, read_wav  # noqa: E402

MARKS = ["。", "，"]
A_MAX_S = 3.0   # method A runs on short pieces only (as it would in the app)


def main(limit=None):
    from artvoiceinput import packs
    from artvoiceinput.app import _COMMAND_SCORE, _WORDS, _bias, _one_command
    from artvoiceinput.asr import Recognizer
    from artvoiceinput.hotwords import Hotwords
    from artvoiceinput.textfmt import format_text
    from xscore import XScorer

    cmds = list(commands())
    cnorm = {norm(c): c for c in cmds}
    cfg = config()
    hw = Hotwords()
    hw.set_packs(packs.words_for(cfg.get("packs", [])), packs.PCT)
    bias = _bias([(w, s) for w, s in hw.bias() if norm(w) not in cnorm])
    boost = _bias([(w, _COMMAND_SCORE) for w in cmds])
    longest = max(map(len, cmds))
    rec = Recognizer("xasr")
    xs = XScorer()
    seqs, owner = [], []
    for c in cmds:
        base = xs.ids(c)
        if base is None:
            print("no tokens for", c)
            continue
        for m in [None] + MARKS:
            k = xs.tok2id.get("▁" + m) if m else None
            if m and k is None:
                continue
            seq = base + ([k] if k is not None else [])
            if seq not in seqs:   # 驚嘆號 / 驚歎號 are one Simplified sequence
                seqs.append(seq)
                owner.append(c)

    def match(raw):
        return cnorm.get(norm(format_text(raw, True)))

    samples = [json.loads(l) for l in (OUT / "samples.jsonl").open(encoding="utf-8")]
    done = set()
    path = OUT / "results.jsonl"
    if path.exists():
        done = {json.loads(l)["wav"] for l in path.open(encoding="utf-8")}
    f = path.open("a", encoding="utf-8")
    n = 0
    for s in samples:
        if s["wav"] in done:
            continue
        if limit and n >= limit:
            break
        n += 1
        audio = read_wav((OUT if s["wav"].startswith("pieces") else REC) / s["wav"])
        r = {"wav": s["wav"], "dur": len(audio) / 16000}
        t0 = time.perf_counter()
        raw1 = rec.recognize(audio, bias)
        r["t1"] = time.perf_counter() - t0
        r["raw1"] = raw1
        r["short"] = len(_WORDS.findall(raw1)) <= longest + 2
        got = match(raw1)
        if got is None and r["short"]:
            t0 = time.perf_counter()
            raw2 = _one_command(rec.recognize(audio, boost), cmds)
            r["t2"] = time.perf_counter() - t0
            r["raw2"] = raw2
            got = match(raw2)
        r["base"] = got
        # method A
        if not (r["short"] or r["dur"] <= A_MAX_S):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            continue
        t0 = time.perf_counter()
        enc = xs.encode(audio)
        t_enc = time.perf_counter() - t0
        g = xs.greedy(enc)
        scores = xs.logp_many(enc, [g] + seqs)
        r["tA"] = time.perf_counter() - t0
        r["tA_enc"] = t_enc
        r["greedy"] = xs.text(g)
        r["lp_free"] = scores[0]
        best = {}
        for c, v in zip(owner, scores[1:]):
            best[c] = max(best.get(c, -1e9), v)
        top = sorted(best.items(), key=lambda kv: -kv[1])[:3]
        r["top"] = [[c, round(v, 3)] for c, v in top]
        r["frames"] = int(enc.shape[0])
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
    print("done", n)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
