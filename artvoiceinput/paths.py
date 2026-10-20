"""Where things live. The app folder holds only code and runtime tools; user data (settings, models, logs)
lives in a per-user data folder so it survives moving, reinstalling or updating the app."""
import os
import shutil
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ArtVoiceInput"

CONFIG_PATH = DATA_DIR / "config.json"
LOG_PATH = DATA_DIR / "artvoiceinput.log"
LOCK_PATH = DATA_DIR / ".artvoiceinput.lock"
MUTED_PATH = DATA_DIR / ".muted"   # there while we keep the speakers muted (mute.py)
DEFAULT_MODELS_DIR = DATA_DIR / "models"


def migrate_legacy() -> None:
    """Move data from the old layout (everything inside the app folder) into DATA_DIR, once."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for src, dst in ((APP_DIR / "config.json", CONFIG_PATH), (APP_DIR / "artvoiceinput.log", LOG_PATH),
                     (APP_DIR / "models", DEFAULT_MODELS_DIR)):
        if src.exists() and not dst.exists():
            shutil.move(src, dst)
    for stale in ("llama-server.log", ".artvoiceinput.lock"):
        (APP_DIR / stale).unlink(missing_ok=True)
