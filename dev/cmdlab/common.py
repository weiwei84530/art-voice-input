"""Shared bits of the command-recognition lab (dev only): paths, the user's command words, audio io, VAD pieces."""
import json
import os
import re
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ["LOCALAPPDATA"]) / "ArtVoiceInput-dev"   # artvoiceinput.paths.DATA_DIR of a development copy
REC = DATA / "recordings"
MODELS = DATA / "models"
XASR = MODELS / "sherpa-onnx-x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03"
OUT = Path(os.environ.get("CMDLAB_OUT", ROOT / "dev" / "cmdlab" / "out"))
SR = 16000
# press-and-talk until this commit time; continuous listening (pieces cut by the VAD) after it
CONTINUOUS_FROM = "2026-10-14 21:31:08"
_PUNCT = re.compile(r"[\s，。、！？；：,.!?;:…]+")


def norm(text: str) -> str:
    from artvoiceinput.textfmt import to_traditional
    return _PUNCT.sub("", to_traditional(text)).casefold()


def config() -> dict:
    return json.loads((DATA / "config.json").read_text(encoding="utf-8"))


def commands() -> dict:
    """phrase -> what it does, as the app's _command_words: enabled speech rules and punctuation names."""
    from artvoiceinput import edit
    out = {}
    for r in config()["rules"]:
        if r.get("source") == "speech" and r.get("enabled", True) and r.get("phrase", "").strip():
            out[r["phrase"].strip()] = r["steps"][0]["type"] + ":" + str(r["steps"][0]["value"])
    for name, mark in edit.SYMBOLS.items():
        out.setdefault(name, "mark:" + mark)
    return {p: v for p, v in out.items() if len(set(p)) > 1}


def read_wav(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    return pcm.astype(np.float32) / 32768


def write_wav(path, audio: np.ndarray):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def vad_pieces(audio: np.ndarray, silence: float = 0.3, lead: float = 0.5, tail: float = 0.25):
    """Pieces as listen.Listener cuts them: [(lo, start, end, hi)] in samples."""
    import sherpa_onnx
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(MODELS / "silero_vad.onnx")
    cfg.silero_vad.min_silence_duration = silence
    cfg.silero_vad.max_speech_duration = 30
    cfg.sample_rate = SR
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=40)
    win = cfg.silero_vad.window_size
    out, prev_end = [], 0

    def emit():
        nonlocal prev_end
        while not vad.empty():
            seg = vad.front
            s, e = seg.start, seg.start + len(seg.samples)
            vad.pop()
            out.append((max(prev_end, s - int(lead * SR)), s, e, min(len(audio), e + int(tail * SR))))
            prev_end = e
    padded = np.concatenate([audio, np.zeros(int(SR * (silence + 0.2)), np.float32)])
    for i in range(0, len(padded) - win + 1, win):
        vad.accept_waveform(padded[i:i + win])
        emit()
    vad.flush()
    emit()
    return out
