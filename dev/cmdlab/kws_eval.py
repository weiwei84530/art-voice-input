"""Method B: sherpa-onnx keyword spotters (small streaming models) on every sample; writes out/kws_<model>.jsonl with
the keywords each threshold detected and the time it took."""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import OUT, REC, commands, read_wav  # noqa: E402

KWS = Path(os.environ["CMDLAB_KWS"])
MODELS = {
    "wenet": ("wenet", "epoch-12-avg-2-chunk-16-left-64"),
    "zhen": ("zhen", "epoch-13-avg-2-chunk-16-left-64"),
}
THRESHOLDS = [0.05, 0.1, 0.2, 0.3]


def keywords(tokens: set) -> str:
    from pypinyin import Style, pinyin
    from pypinyin.contrib.tone_convert import to_finals_tone, to_initials
    lines = []
    from voiceinput.textfmt import to_simplified
    for phrase in commands():
        toks = []
        # Simplified: pypinyin reads 換行 as huan xing, 换行 as huan hang
        for (p,) in pinyin(to_simplified(phrase), style=Style.TONE):
            ini, fin = to_initials(p, strict=False), to_finals_tone(p, strict=False)
            toks += [t for t in (ini, fin) if t]
        if all(t in tokens for t in toks):
            lines.append(" ".join(toks) + " @" + phrase)
        else:
            print("skip", phrase, toks)
    return "\n".join(lines) + "\n"


def main(name, every=1, suffix=""):
    import sherpa_onnx
    d, tag = MODELS[name]
    d = KWS / d   # short paths: sherpa-onnx fails on paths over 260 characters
    tokens = {l.split()[0] for l in (d / "tokens.txt").read_text(encoding="utf-8").splitlines() if l.strip()}
    kw = OUT / f"keywords_{name}.txt"
    kw.write_text(keywords(tokens), encoding="utf-8")
    spotters = {th: sherpa_onnx.KeywordSpotter(
        tokens=str(d / "tokens.txt"), encoder=str(d / f"encoder-{tag}.int8.onnx"),
        decoder=str(d / f"decoder-{tag}.onnx"), joiner=str(d / f"joiner-{tag}.int8.onnx"),
        keywords_file=str(kw), num_threads=1, keywords_threshold=th, keywords_score=2.0) for th in THRESHOLDS}
    samples = [json.loads(l) for l in (OUT / "samples.jsonl").open(encoding="utf-8")][::every]
    with (OUT / f"kws_{name}{suffix}.jsonl").open("w", encoding="utf-8") as f:
        for s in samples:
            audio = read_wav((OUT if s["wav"].startswith("pieces") else REC) / s["wav"])
            audio = np.concatenate([audio, np.zeros(int(0.3 * 16000), np.float32)])
            r = {"wav": s["wav"], "dur": len(audio) / 16000 - 0.3}
            for th, sp in spotters.items():
                t0 = time.perf_counter()
                st = sp.create_stream()
                st.accept_waveform(16000, audio)
                st.input_finished()
                hits = []
                while sp.is_ready(st):
                    sp.decode_stream(st)
                    k = sp.get_result(st)
                    if k:
                        hits.append(k)
                        sp.reset_stream(st)
                r[f"t{th}"] = time.perf_counter() - t0
                r[str(th)] = hits
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1, sys.argv[3] if len(sys.argv) > 3 else "")
