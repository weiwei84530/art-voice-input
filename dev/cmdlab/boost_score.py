"""Accuracy idea: a stronger command boost (and a wider beam) for short pieces. Decodes every continuous-listening
sample with at most GATE seconds of speech with the commands boosted at several scores; out/boost_score.jsonl."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import OUT, REC, commands, read_wav  # noqa: E402

GATE = 1.6
SCORES = [5, 6, 7, 8, 10]


def main():
    from voiceinput.app import _bias, _one_command
    from voiceinput.asr import Recognizer
    cmds = list(commands())
    rec = Recognizer("xasr")
    speech = {json.loads(l)["wav"]: json.loads(l)["speech"] for l in (OUT / "boost_first.jsonl").open(encoding="utf-8")}
    with (OUT / "boost_score.jsonl").open("w", encoding="utf-8") as f:
        for line in (OUT / "samples.jsonl").open(encoding="utf-8"):
            s = json.loads(line)
            if s["era"] != "cont" or speech[s["wav"]] > GATE:
                continue
            a = read_wav((OUT if s["wav"].startswith("pieces") else REC) / s["wav"])
            r = {"wav": s["wav"]}
            for sc in SCORES:
                r[str(sc)] = _one_command(rec.recognize(a, _bias([(w, float(sc)) for w in cmds])), cmds)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
