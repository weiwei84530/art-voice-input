"""What setup and uninstall do on disk and in the registry (per user, no admin): the app folder, uninstall.exe beside
it, a Start menu shortcut, the uninstall entry Windows' 設定 → 應用程式 lists, and on uninstall the autostart Run
value (only when it points into the app folder: a development copy registers the same value)."""
import base64
import os
import shutil
import subprocess
import sys
import time
import winreg
from pathlib import Path

from artvoiceinput import __version__

from . import payload

APP_ID = "ArtVoiceInput"
NAME = "阿特語音輸入法"
EXE = "ArtVoiceInput.exe"
UNINSTALLER = "uninstall.exe"
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
DEFAULT_DIR = LOCAL / "Programs" / APP_ID
DATA_DIR = LOCAL / APP_ID   # artvoiceinput.paths.DATA_DIR
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
SHORTCUT = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{NAME}.lnk"
NO_WINDOW = subprocess.CREATE_NO_WINDOW


class SetupError(Exception):
    """A reason shown to the user."""


def installed_dir() -> Path | None:
    """Where an earlier install went (its uninstall entry)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return Path(winreg.QueryValueEx(k, "InstallLocation")[0])
    except OSError:
        return None


def target(chosen: Path) -> Path:
    """A folder the user picked gets its own ArtVoiceInput folder inside, so uninstall never takes their files."""
    return chosen if chosen.name.lower() == APP_ID.lower() else chosen / APP_ID


def is_ours(folder: Path) -> bool:
    return (folder / EXE).is_file()


def close_running() -> None:
    """Art VoiceInput holds its files open: it is closed first (a kill; a mute it set is undone at its next launch)."""
    subprocess.run(["taskkill", "/F", "/IM", EXE], capture_output=True, creationflags=NO_WINDOW)
    time.sleep(0.5)


def _remove(folder: Path) -> None:
    for _ in range(20):   # a process just killed lets go of its files a moment later
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(0.25)
    raise SetupError(f"有檔案還在使用中，刪不掉：{folder}")


def install(folder: Path, progress) -> None:
    """progress(fraction, what) from this worker thread."""
    z = payload.open_zip(Path(sys.executable))
    if z is None:
        raise SetupError("安裝檔不完整，請重新下載。")
    progress(0.0, "正在關閉阿特語音輸入法")
    close_running()
    if folder.exists() and any(folder.iterdir()):
        if not is_ours(folder):
            raise SetupError(f"這個資料夾裡已經有其他檔案：{folder}")
        progress(0.0, "正在移除舊版")
        _remove(folder)
    folder.mkdir(parents=True, exist_ok=True)
    items = [i for i in z.infolist() if not i.is_dir()]
    total = sum(i.file_size for i in items) or 1
    done = 0
    for i in items:
        what = "正在放入辨識模型" if i.filename.startswith("models/") else "正在複製程式檔案"
        progress(done / total * 0.97, what)
        z.extract(i, folder)
        done += i.file_size
    progress(0.97, "正在完成設定")
    with open(sys.executable, "rb") as src, open(folder / UNINSTALLER, "wb") as dst:
        left = payload.stub_size(z)
        while left > 0:
            chunk = src.read(min(left, 1 << 20))
            dst.write(chunk)
            left -= len(chunk)
    z.close()
    _shortcut(folder / EXE)
    _register(folder, total)
    progress(1.0, "安裝完成")


def _shortcut(exe: Path) -> None:
    SHORTCUT.parent.mkdir(parents=True, exist_ok=True)
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{SHORTCUT}'); "
              f"$s.TargetPath = '{exe}'; $s.WorkingDirectory = '{exe.parent}'; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                    base64.b64encode(script.encode("utf-16-le")).decode()], capture_output=True, creationflags=NO_WINDOW)


def _register(folder: Path, size: int) -> None:
    values = {
        "DisplayName": NAME, "DisplayVersion": __version__, "Publisher": "Art VoiceInput",
        "DisplayIcon": str(folder / EXE), "InstallLocation": str(folder),
        "UninstallString": f'"{folder / UNINSTALLER}"', "QuietUninstallString": f'"{folder / UNINSTALLER}" /quiet',
    }
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, value in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        for name, value in (("EstimatedSize", size // 1024), ("NoModify", 1), ("NoRepair", 1)):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)


def launch(folder: Path) -> None:
    subprocess.Popen([str(folder / EXE)], cwd=folder, creationflags=subprocess.DETACHED_PROCESS, close_fds=True)


def uninstall(folder: Path, delete_data: bool, progress) -> None:
    progress(0.0, "正在關閉阿特語音輸入法")
    close_running()
    progress(0.2, "正在移除程式")
    if folder.exists():
        if not is_ours(folder):
            raise SetupError(f"找不到阿特語音輸入法：{folder}")
        _remove(folder)
    progress(0.8, "正在移除捷徑與登錄")
    SHORTCUT.unlink(missing_ok=True)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            if str(folder).lower() in str(winreg.QueryValueEx(k, APP_ID)[0]).lower():
                winreg.DeleteValue(k, APP_ID)
    except OSError:
        pass
    if delete_data:
        progress(0.9, "正在刪除設定與詞庫")
        _remove(DATA_DIR)
    progress(1.0, "已解除安裝")


def delete_later(path: Path) -> None:
    """The uninstaller's temp copy, removed once it has exited."""
    subprocess.Popen(f'cmd /c ping -n 4 127.0.0.1 >nul & del /f /q "{path}"', creationflags=NO_WINDOW, close_fds=True)
