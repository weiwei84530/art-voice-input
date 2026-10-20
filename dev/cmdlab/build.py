"""Builds the lab's dataset from the saved recordings (read only): out/samples.jsonl, one sample per line.

kind: pos (a command fired: op, or a punctuation name typed), neg (a VAD piece of an utterance that was text),
review (a short utterance that was typed as text: a missed command or real short text, for the user to label).
A sample is a wav (a piece as the app decodes it: 0.5s lead-in, 0.25s tail) plus what the app did with it."""
import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from common import CONTINUOUS_FROM, OUT, REC, SR, commands, norm, read_wav, vad_pieces, write_wav  # noqa: E402
from artvoiceinput import edit  # noqa: E402

UNITS = __import__("re").compile(r"[㐀-䶿一-鿿]|[A-Za-z0-9]+")


def main():
    cmds = commands()
    names = {norm(p): p for p in cmds}
    marks = set(edit.SYMBOLS.values())
    rows = [json.loads(l) for l in (REC / "index.jsonl").open(encoding="utf-8")]
    out = []
    for r in rows:
        if r.get("type") != "dictation" or not (REC / f"{r['id']}.wav").exists():
            continue
        era = "cont" if r["time"] >= CONTINUOUS_FROM else "press"
        base = {"id": r["id"], "era": era, "asr": r.get("asr", ""), "op": r.get("op"), "result": r.get("result")}
        op = r.get("op")
        said = norm(r.get("fmt") or r.get("asr") or "")
        if op or (r.get("result") in marks and said in names):
            phrase = op or names[said]
            if norm(phrase) not in names:
                continue   # a phrase no longer in use (改成, 標點 …)
            out.append({**base, "kind": "pos", "label": names[norm(phrase)], "wav": f"{r['id']}.wav"})
            continue
        audio = read_wav(REC / f"{r['id']}.wav")
        units = len(UNITS.findall(r.get("asr") or ""))
        if units <= 4:
            out.append({**base, "kind": "review", "label": None, "wav": f"{r['id']}.wav"})
            continue
        # a longer utterance: the pieces the VAD cuts it into, each a negative unless its decode is a command
        for k, (lo, s, e, hi) in enumerate(vad_pieces(audio)):
            name = f"{r['id']}_p{k}.wav"
            write_wav(OUT / "pieces" / name, audio[lo:hi])
            out.append({**base, "kind": "neg", "label": None, "wav": "pieces/" + name, "speech_s": (e - s) / SR})
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "samples.jsonl").open("w", encoding="utf-8") as f:
        for s in out:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    from collections import Counter
    print(Counter((s["kind"], s["era"]) for s in out))
    print(Counter(s["label"] for s in out if s["kind"] == "pos").most_common())
    print("commands:", list(cmds))


if __name__ == "__main__":
    main()
