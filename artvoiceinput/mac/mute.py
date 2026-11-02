"""macOS: the speakers muted while listening (錄音時暫時靜音電腦音效), through AppleScript's volume settings (no
package; `osascript` takes ~0.1s, so it runs on a thread of its own, in order). Only a mute we set is undone; a
marker file (paths.MUTED_PATH) lets the next launch unmute after the app was killed while listening."""
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor

from ..paths import MUTED_PATH

log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=1)


def _script(text: str) -> str:
    return subprocess.run(["osascript", "-e", text], capture_output=True, text=True, timeout=5).stdout.strip()


def _muted() -> bool:
    return _script("output muted of (get volume settings)") == "true"


def _set(on: bool) -> None:
    _script(f"set volume output muted {'true' if on else 'false'}")


class Muter:
    def __init__(self):
        self._ours = False   # the speakers are muted by us (or will be in a moment), so restore() unmutes them

    @property
    def active(self) -> bool:
        return self._ours

    def mute(self):
        if self._ours:
            return
        self._ours = True
        _pool.submit(self._mute_job)

    def _mute_job(self):
        try:
            if not self._ours:
                return   # listening ended before this ran
            if _muted():
                self._ours = False   # the user's own mute: left alone (no marker, so no unmute)
                return
            MUTED_PATH.parent.mkdir(parents=True, exist_ok=True)
            MUTED_PATH.write_text("muted by Art VoiceInput while listening", encoding="utf-8")
            _set(True)
        except Exception:
            self._ours = False
            log.exception("mute failed")

    def restore(self):
        if not self._ours:
            return
        self._ours = False
        _pool.submit(self._restore_job)

    def _restore_job(self):
        if not MUTED_PATH.exists():
            return   # the user had muted the speakers themselves: left alone
        try:
            _set(False)
            MUTED_PATH.unlink(missing_ok=True)
        except Exception:
            log.exception("unmute failed")


def recover() -> None:
    """At launch: a mute left by a run that was killed while listening is undone."""
    if not MUTED_PATH.exists():
        return
    try:
        _set(False)
        log.info("unmuted the speakers a killed run had muted")
    except Exception:
        log.exception("unmute at launch failed")
    MUTED_PATH.unlink(missing_ok=True)
