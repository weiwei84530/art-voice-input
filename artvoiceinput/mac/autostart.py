"""macOS: launch at login with a LaunchAgent (~/Library/LaunchAgents/<label>.plist). The installed build starts its
app bundle with `open`, so macOS counts it as that app (its microphone and Accessibility permissions); a development
copy starts its Python with run.pyw."""
import os
import plistlib
import sys
from pathlib import Path

from ..paths import APP_DIR, FROZEN, ID

APP_ID = ID
FLAG = "--autostart"   # launched at login: no settings window (app.main)
LABEL = f"com.artvoiceinput.{ID}"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LAUNCHER = APP_DIR / "run.pyw"
APP_ENV = "ARTVOICEINPUT_APP"   # the app bundle the launcher started us from (packaging/mac/launcher.c)


def arguments() -> list[str]:
    """How this run is started again: the app bundle through `open`, else Python with run.pyw."""
    bundle = os.environ.get(APP_ENV)
    if FROZEN and bundle:
        return ["/usr/bin/open", "-a", bundle, "--args"]
    return [sys.executable] if FROZEN else [sys.executable, str(LAUNCHER)]


def command() -> str:
    return " ".join(f'"{a}"' for a in arguments())


def set_enabled(enabled: bool, debug: bool = False) -> None:
    """debug: the agent launches with --debug too (it follows how this run was launched)."""
    if not enabled:
        PLIST.unlink(missing_ok=True)
        return
    args = arguments() + [FLAG] + (["--debug"] if debug else [])
    data = {"Label": LABEL, "ProgramArguments": args, "RunAtLoad": True, "ProcessType": "Interactive"}
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    new = plistlib.dumps(data)
    if not PLIST.exists() or PLIST.read_bytes() != new:
        PLIST.write_bytes(new)
