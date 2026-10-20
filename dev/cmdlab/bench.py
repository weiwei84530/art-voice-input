"""Speed and memory of each method on a fixed subset (run with nothing else busy): seconds per piece, median and p90."""
import json
import os
import statistics as st
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import OUT, REC, commands, read_wav  # noqa: E402


def rss():
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
                   [(n, ctypes.c_size_t) for n in ("Peak", "WS", "QPP", "QP", "QNPP", "QNP", "Pf", "PPf")]
    c = PMC()
    c.cb = ctypes.sizeof(c)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.WS / 2 ** 20


def q(xs):
    xs = sorted(xs)
    return f"median {st.median(xs) * 1000:.0f}ms  p90 {xs[int(0.9 * len(xs))] * 1000:.0f}ms"


def main():
    import sherpa_onnx
    from artvoiceinput.app import _COMMAND_SCORE, _bias
    from artvoiceinput.asr import Recognizer
    samples = [json.loads(l) for l in (OUT / "samples.jsonl").open(encoding="utf-8")]
    pos = [s for s in samples if s["kind"] == "pos" and s["era"] == "cont"][::10][:60]
    audios = [read_wav(REC / s["wav"]) for s in pos]
    print("pieces:", len(audios), "mean length %.2fs" % np.mean([len(a) / 16000 for a in audios]))
    cmds = list(commands())
    m0 = rss()
    rec = Recognizer("xasr")
    m1 = rss()
    boost = _bias([(w, _COMMAND_SCORE) for w in cmds])
    for a in audios[:3]:
        rec.recognize(a)
    t = [time.perf_counter() - t0 for a in audios for t0 in [time.perf_counter()] if rec.recognize(a) is not None]
    print("sherpa X-ASR decode          ", q(t), f"(model RAM {m1 - m0:.0f}MB)")
    t = [time.perf_counter() - t0 for a in audios for t0 in [time.perf_counter()] if rec.recognize(a, boost) is not None]
    print("sherpa decode, commands boost", q(t))

    from xscore import XScorer
    m0 = rss()
    xs = XScorer(threads=2)
    m1 = rss()
    seqs, owner = [], []
    for c in cmds:
        b = xs.ids(c)
        for m in (None, "。", "，"):
            s = b + ([xs.tok2id["▁" + m]] if m else [])
            if s not in seqs:
                seqs.append(s)
                owner.append(c)
    te, tg, tf, tp = [], [], [], []
    for a in audios:
        t0 = time.perf_counter()
        enc = xs.encode(a)
        t1 = time.perf_counter()
        g = xs.greedy(enc)
        t2 = time.perf_counter()
        xs.logp_many(enc, [g] + seqs)
        t3 = time.perf_counter()
        xs.logp(enc, g)
        xs.score_commands(enc, seqs, owner)
        t4 = time.perf_counter()
        te.append(t1 - t0); tg.append(t2 - t1); tf.append(t3 - t2); tp.append(t4 - t3)
    print("A: encoder (onnxruntime)     ", q(te), f"(second copy of the model: RAM {m1 - m0:.0f}MB)")
    print("A: greedy search             ", q(tg))
    print("A: score all commands        ", q(tf))
    print("A: score, pruned             ", q(tp))
    print("A total, pruned              ", q([a + b + c for a, b, c in zip(te, tg, tp)]))

    kd = Path(os.environ["CMDLAB_KWS"]) / "zhen"
    tag = "epoch-13-avg-2-chunk-16-left-64"
    m0 = rss()
    sp = sherpa_onnx.KeywordSpotter(tokens=str(kd / "tokens.txt"), encoder=str(kd / f"encoder-{tag}.int8.onnx"),
                                    decoder=str(kd / f"decoder-{tag}.onnx"), joiner=str(kd / f"joiner-{tag}.int8.onnx"),
                                    keywords_file=str(OUT / "keywords_zhen.txt"), num_threads=1,
                                    keywords_threshold=0.1, keywords_score=2.0)
    m1 = rss()
    t, total = [], 0
    for a in audios:
        t0 = time.perf_counter()
        s = sp.create_stream()
        s.accept_waveform(16000, a)
        s.input_finished()
        while sp.is_ready(s):
            sp.decode_stream(s)
            sp.get_result(s)
        t.append(time.perf_counter() - t0)
        total += len(a) / 16000
    print("B: keyword spotter, whole piece", q(t), f"RTF {sum(t) / total:.3f} (one core: {100 * sum(t) / total:.1f}% "
          f"while listening)  RAM {m1 - m0:.0f}MB")


if __name__ == "__main__":
    main()
