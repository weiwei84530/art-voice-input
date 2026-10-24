"""The tutorial's speech through the real recognizer: each phrase the tutorial asks for is spoken by Windows TTS
(dev/tts.ps1, zh-TW Hanhan), decoded the way App._tutorial_decode does (commands boosted first on a short piece)
and judged by the tutorial's own rules (tutorial.alike / described), plus a few wrong readings that must fail.

    .venv/Scripts/python dev/tutorial_asr.py
"""
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from artvoiceinput import models  # noqa: E402
from artvoiceinput.app import App  # noqa: E402
from artvoiceinput.asr import Recognizer  # noqa: E402
from artvoiceinput.ui import tutorial  # noqa: E402

# (spoken, what the step wants: ("read", target) / ("cmd", name) / ("char", ch), should pass)
CASES = [
    ("今天天氣很好，我們去公園散步", ("read", tutorial.FIRST), True),
    ("今天天氣很好，我們去公司上班", ("read", tutorial.FIRST), False),
    ("爺爺的視力很好", ("read", tutorial.SECOND), True),
    ("連對面的招牌都看得清楚", ("read", tutorial.THIRD), True),
    ("句號", ("cmd", "句號"), True),
    ("下一行", ("cmd", "下一行"), True),
    ("記得帶雨傘", ("read", "記得帶雨傘"), True),
    ("復原", ("cmd", "復原"), True),
    ("兩張", ("read", "兩張"), True),
    ("刪除", ("cmd", "刪除"), True),
    ("節日的節", ("char", "節"), True),
    ("我等一下就到", ("read", "我等一下就到"), True),
    ("送出", ("cmd", "送出"), True),
    ("結束", ("cmd", "結束"), True),
    ("我想吃牛肉麵", ("read", "我等一下就到"), False),
]


def tts(text: str, out: Path) -> np.ndarray:
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "dev" / "tts.ps1"),
                    str(out), text], check=True)
    with wave.open(str(out)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def main():
    rec = Recognizer(models.MAIN_MODEL)
    results = []
    host = SimpleNamespace(recognizer=rec, worker=SimpleNamespace(submit=lambda f: f()),
                           main=SimpleNamespace(emit=lambda f: f()))
    tmp = Path(tempfile.mkdtemp(prefix="vi-tut-"))
    bad = 0
    for i, (spoken, (kind, want), should) in enumerate(CASES):
        audio = tts(spoken, tmp / f"{i}.wav")
        short = len(audio) / 16000 <= tutorial.Ear.SHORT + 0.6   # TTS leaves little silence round the speech
        App._tutorial_decode(host, audio, tutorial.COMMANDS if short else [], results.append)
        got = results[-1]
        if kind == "cmd":
            ok = got == ("cmd", want)
        elif kind == "char":
            ok = got[0] == "text" and tutorial.described(got[1]) == want
        else:
            ok = got[0] == "text" and tutorial.alike(got[1], want) >= tutorial.ALIKE
        score = f"{tutorial.alike(got[1], want):.2f}" if kind == "read" and got[0] == "text" else ""
        mark = "ok " if ok == should else "BAD"
        bad += ok != should
        print(f"{mark} {spoken} -> {got} {score} (pass={ok}, expected {should})", flush=True)
    print("all as expected" if not bad else f"{bad} unexpected")


if __name__ == "__main__":
    main()
