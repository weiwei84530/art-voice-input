"""Launch at login: HKCU Run key."""
import sys
import winreg
from pathlib import Path

from ..paths import APP_DIR, FROZEN, ID

APP_ID = ID   # the Run value's name: ArtVoiceInput installed, ArtVoiceInput-dev here
LAUNCHER = APP_DIR / "run.pyw"
FLAG = "--autostart"   # launched at login: no settings window (app.main)


def _python() -> str:
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else exe)


def command() -> str:
    """How this run is started again: the installed exe, else pythonw with run.pyw."""
    return f'"{sys.executable}"' if FROZEN else f'"{_python()}" "{LAUNCHER}"'


def set_enabled(enabled: bool, debug: bool = False) -> None:
    """debug: the entry launches with --debug too (it follows how this run was launched)."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, f'{command()} {FLAG}' + (" --debug" if debug else ""))
        else:
            try:
                winreg.DeleteValue(k, APP_ID)
            except FileNotFoundError:
                pass
