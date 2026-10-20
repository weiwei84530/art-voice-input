"""Accuracy idea: silence added around a short piece before its boosted-first decode (X-ASR misses a command less
when the audio starts and ends in silence). For each continuous-listening sample with at most GATE seconds of
speech: the boosted decode of the padded audio per variant; out/pad_test.jsonl."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import OUT, REC, commands, read_wav  # noqa: E402

GATE = 1.2
VARIANTS = {"both0.3": (0.3, 0.3), "both0.5": (0.5, 0.5), "head0.3": (0.3, 0.0), "tail0.6": (0.0, 0.6),
            "both0.3plain": (0.3, 0.3)}


def main():
    from artvoiceinput.app import _bias, _one_command
    from artvoiceinput.asr import Recognizer
    cmds = list(commands())
    rec = Recognizer("xasr")
    boost = _bias([(w, 5.0) for w in cmds])
    speech = {json.loads(l)["wav"]: json.loads(l)["speech"] for l in (OUT / "boost_first.jsonl").open(encoding="utf-8")}
    with (OUT / "pad_test.jsonl").open("w", encoding="utf-8") as f:
        for line in (OUT / "samples.jsonl").open(encoding="utf-8"):
            s = json.loads(line)
            if s["era"] != "cont" or speech[s["wav"]] > GATE:
                continue
            a = read_wav((OUT if s["wav"].startswith("pieces") else REC) / s["wav"])
            r = {"wav": s["wav"]}
            for name, (h, t) in VARIANTS.items():
                x = np.concatenate([np.zeros(int(h * 16000), np.float32), a, np.zeros(int(t * 16000), np.float32)])
                raw = rec.recognize(x) if name.endswith("plain") else rec.recognize(x, boost)
                r[name] = _one_command(raw, cmds)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
