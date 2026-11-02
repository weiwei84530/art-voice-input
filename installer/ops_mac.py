"""What the Mac setup does on disk (per user, no admin password): the same functions as ops.py, which the setup window
(ui.py) calls.

The setup app carries payload.tar.gz in its Resources: `app/` (the real app, PyInstaller onedir, with its models)
and `Art VoiceInput.app` (the launcher, packaging/mac). The real app goes to
~/Library/Application Support/ArtVoiceInput/app, beside the user's data, which an update leaves alone; the launcher
to /Applications (or ~/Applications when /Applications is not writable). The launcher never changes between
versions, so its permissions (microphone, Accessibility, Input Monitoring) survive an update; it is written only
when missing or different. A tar keeps the files' modes and symlinks, which the real app's frameworks need; the
files arrive byte for byte, so their ad hoc signatures hold."""
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from artvoiceinput import __version__

APP_ID = "ArtVoiceInput"
NAME = "阿特語音輸入法"
EXE = "ArtVoiceInput"
BUNDLE = "Art VoiceInput.app"
DATA_DIR = Path.home() / "Library" / "Application Support" / APP_ID   # artvoiceinput.paths.DATA_DIR
DEFAULT_DIR = DATA_DIR / "app"
VERSION_FILE = "version.txt"
CAN_MOVE = False   # no other place offered: the launcher looks for the app in DEFAULT_DIR


class SetupError(Exception):
    """A reason shown to the user."""


def _payload() -> Path:
    """payload.tar.gz in the setup app's Resources (PyInstaller puts the executable in Contents/MacOS)."""
    return Path(sys.executable).resolve().parent.parent / "Resources" / "payload.tar.gz"


def has_payload() -> bool:
    return _payload().is_file()


def apps_dir() -> Path:
    """Where the launcher goes: an earlier one's place, else /Applications when writable, else ~/Applications."""
    for d in (Path("/Applications"), Path.home() / "Applications"):
        if (d / BUNDLE).exists():
            return d
    if os.access("/Applications", os.W_OK):
        return Path("/Applications")
    return Path.home() / "Applications"


def installed_dir() -> Path | None:
    return DEFAULT_DIR if is_ours(DEFAULT_DIR) else None


def installed_version() -> str | None:
    try:
        return (DEFAULT_DIR / VERSION_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def target(chosen: Path) -> Path:
    return DEFAULT_DIR


def is_ours(folder: Path) -> bool:
    return (folder / EXE).is_file()


def close_running() -> bool:
    """Art VoiceInput is closed first (a kill; a mute it set is undone at its next launch). True when it was
    running."""
    r = subprocess.run(["pkill", "-f", str(DEFAULT_DIR / EXE)], capture_output=True)
    subprocess.run(["pkill", "-f", f"{BUNDLE}/Contents/MacOS/{EXE}"], capture_output=True)
    time.sleep(0.5)
    return r.returncode == 0


def _same_tree(a: Path, b: Path) -> bool:
    """The launcher bundles hold the same files (an update keeps the installed one, so its signature stays)."""
    if not b.exists():
        return False
    files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    return files_a == files_b and all((a / f).read_bytes() == (b / f).read_bytes() for f in files_a)


def install(folder: Path, progress) -> bool:
    """progress(fraction, what) from this worker thread. Over an earlier install (an update) only the app is
    replaced: settings, 詞庫 and logs live in DATA_DIR and are not touched. Art VoiceInput, if it was running, is
    started again at the end; True then."""
    if not has_payload():
        raise SetupError("安裝檔不完整，請重新下載。")
    progress(0.0, "正在關閉阿特語音輸入法")
    was_running = close_running()
    staging = DATA_DIR / ".setup"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    with tarfile.open(_payload(), "r:gz") as tar:
        members = tar.getmembers()
        total = sum(m.size for m in members) or 1
        done = 0
        for m in members:
            what = "正在放入辨識模型" if "/models/" in m.name else "正在複製程式檔案"
            progress(done / total * 0.95, what)
            tar.extract(m, staging, filter="tar")
            done += m.size
    progress(0.95, "正在替換舊版" if is_ours(DEFAULT_DIR) else "正在完成設定")
    shutil.rmtree(DEFAULT_DIR, ignore_errors=True)
    (staging / "app").rename(DEFAULT_DIR)
    (DEFAULT_DIR / VERSION_FILE).write_text(__version__, encoding="utf-8")
    apps = apps_dir()
    apps.mkdir(parents=True, exist_ok=True)
    bundle = apps / BUNDLE
    if not _same_tree(staging / BUNDLE, bundle):
        shutil.rmtree(bundle, ignore_errors=True)
        (staging / BUNDLE).rename(bundle)
    shutil.rmtree(staging, ignore_errors=True)
    if was_running:
        launch(folder)
    progress(1.0, "安裝完成")
    return was_running


def launch(folder: Path) -> None:
    subprocess.Popen(["open", "-a", str(apps_dir() / BUNDLE)])


def uninstall(folder: Path, delete_data: bool, progress) -> None:
    progress(0.0, "正在關閉阿特語音輸入法")
    close_running()
    progress(0.3, "正在移除程式")
    shutil.rmtree(DEFAULT_DIR, ignore_errors=True)
    shutil.rmtree(apps_dir() / BUNDLE, ignore_errors=True)
    (Path.home() / "Library" / "LaunchAgents" / f"com.artvoiceinput.{APP_ID}.plist").unlink(missing_ok=True)
    if delete_data:
        progress(0.9, "正在刪除設定與詞庫")
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    progress(1.0, "已解除安裝")


def delete_later(path: Path) -> None:
    pass
