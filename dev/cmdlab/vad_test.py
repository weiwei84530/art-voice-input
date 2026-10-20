"""Speed idea: act on a command after 0.15s of silence instead of 0.3s. Two checks:
1. text utterances cut at 0.15s: short pieces that would now decode to a command (new false triggers);
2. command pieces with 0.1s less audio after the speech (the tail a 0.15s cut leaves): still recognized?"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import OUT, REC, SR, commands, norm, read_wav, vad_pieces  # noqa: E402


def main():
    from artvoiceinput.app import _COMMAND_SCORE, _WORDS, _bias, _one_command
    from artvoiceinput.asr import Recognizer
    from artvoiceinput.textfmt import format_text
    cmds = list(commands())
    cn = {norm(c): c for c in cmds}
    longest = max(map(len, cmds))
    rec = Recognizer("xasr")
    boost = _bias([(w, _COMMAND_SCORE) for w in cmds])

    def decide(a):
        raw = rec.recognize(a)
        got = cn.get(norm(format_text(raw, True)))
        if got is None and len(_WORDS.findall(raw)) <= longest + 2:
            raw = _one_command(rec.recognize(a, boost), cmds)
            got = cn.get(norm(format_text(raw, True)))
        return got, raw

    samples = [json.loads(l) for l in (OUT / "samples.jsonl").open(encoding="utf-8")]
    texts = {s["id"]: s for s in samples if s["kind"] == "neg"}
    out = {"cut015": Counter(), "examples": [], "tail": Counter(), "tail_lost": []}
    for sid, s in texts.items():
        audio = read_wav(REC / f"{sid}.wav")
        p3 = vad_pieces(audio, 0.3)
        p15 = vad_pieces(audio, 0.15)
        out["cut015"]["utterances"] += 1
        out["cut015"]["pieces_0.3"] += len(p3)
        out["cut015"]["pieces_0.15"] += len(p15)
        ends3 = {e for _, _, e, _ in p3}
        for lo, st, e, hi in p15:
            if e in ends3 or (e - st) > 1.5 * SR:   # the same cut as at 0.3s, or too long to be a command
                continue
            out["cut015"]["new_short"] += 1
            got, raw = decide(audio[lo:min(hi, e + int(0.15 * SR))])
            if got:
                out["cut015"]["false"] += 1
                out["examples"].append([sid, raw, got, s["asr"]])
    for s in [s for s in samples if s["kind"] == "pos" and s["era"] == "cont"]:
        a = read_wav(REC / s["wav"])
        got, raw = decide(a[:max(0, len(a) - int(0.1 * SR))])
        out["tail"]["n"] += 1
        out["tail"]["kept" if got == s["label"] else "lost"] += 1
        if got != s["label"]:
            out["tail_lost"].append([s["wav"], s["label"], raw])
    (OUT / "vad_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out["cut015"], out["tail"])


if __name__ == "__main__":
    main()
