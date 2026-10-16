"""Speed idea: a piece whose speech is short (VAD) is decoded with the commands boosted first; a command ends it
there, anything else goes the current way (plain decode, then the boost again if the text is short).
Writes out/boost_first.jsonl: per sample the boosted-first decode and the speech length."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import OUT, REC, SR, commands, read_wav, vad_pieces  # noqa: E402

GATE = 1.6   # seconds of speech


def main():
    from voiceinput.app import _COMMAND_SCORE, _bias, _one_command
    from voiceinput.asr import Recognizer
    cmds = list(commands())
    rec = Recognizer("xasr")
    boost = _bias([(w, _COMMAND_SCORE) for w in cmds])
    with (OUT / "boost_first.jsonl").open("w", encoding="utf-8") as f:
        for line in (OUT / "samples.jsonl").open(encoding="utf-8"):
            s = json.loads(line)
            a = read_wav((OUT if s["wav"].startswith("pieces") else REC) / s["wav"])
            sp = sum(e - st for _, st, e, _ in vad_pieces(a)) / SR
            r = {"wav": s["wav"], "speech": sp}
            if sp <= GATE:
                r["boosted"] = _one_command(rec.recognize(a, boost), cmds)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
