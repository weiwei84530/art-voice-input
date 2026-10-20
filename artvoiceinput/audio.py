"""Microphone devices (listen.Listener records) and the level probe of 測試麥克風."""
import math
import threading

import numpy as np
import sounddevice as sd


def list_input_devices() -> list[str]:
    """Input device names from the platform's default host API (avoids MME/WASAPI duplicates)."""
    try:
        default_api = sd.default.hostapi
        devices = sd.query_devices()
    except Exception:
        return []
    names = []
    for d in devices:
        if (d["max_input_channels"] > 0 and d["hostapi"] == default_api
                and "Sound Mapper" not in d["name"] and d["name"] not in names):
            names.append(d["name"])
    return names


def resolve_device(name: str):
    if not name:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["name"] == name and d["max_input_channels"] > 0:
            return i
    return None


class LevelProbe:
    """The microphone's loudness for 測試麥克風 (the 麥克風 page): a stream of its own, so it works whether listening
    is on or not (Windows shares the device). `level` is the loudest block since the last read, 0..1 over -60..0
    dBFS."""
    FLOOR_DB = -60.0

    def __init__(self):
        self._stream = None
        self._peak = 0.0
        self._lock = threading.Lock()

    def start(self, device_name: str = ""):
        """Raises what sounddevice raises when the device can't be opened."""
        self.stop()
        self._stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=480,
                                      device=resolve_device(device_name), callback=self._callback)
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._peak = 0.0

    @property
    def running(self) -> bool:
        return self._stream is not None

    def _callback(self, data, frames, time_info, status):
        rms = float(np.sqrt(np.mean(np.square(data[:, 0])))) if frames else 0.0
        with self._lock:
            self._peak = max(self._peak, rms)

    def read(self) -> float:
        with self._lock:
            rms, self._peak = self._peak, 0.0
        if rms <= 0:
            return 0.0
        db = 20 * math.log10(rms)
        return min(max((db - self.FLOOR_DB) / -self.FLOOR_DB, 0.0), 1.0)

