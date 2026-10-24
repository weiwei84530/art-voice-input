# PyInstaller spec of the app itself: onedir dist/ArtVoiceInput (ArtVoiceInput.exe + _internal). Built by
# installer/build.py, which then adds the models and packs the folder into the setup exe.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
PKG = ROOT / "artvoiceinput"

datas = [(str(PKG / d), f"artvoiceinput/{d}") for d in ("dict", "cues", "packs")]
datas += [(str(f), "artvoiceinput/ui") for f in (PKG / "ui").glob("*.svg")]
datas += [(str(PKG / "appicon.ico"), "artvoiceinput")]
datas += collect_data_files("opencc") + collect_data_files("pypinyin")

a = Analysis(
    [str(ROOT / "run.pyw")],
    pathex=[str(ROOT)],
    binaries=collect_dynamic_libs("sherpa_onnx"),
    datas=datas,
    hiddenimports=["pynput.keyboard._win32", "pynput.mouse._win32", "pynput._util.win32"],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtWebEngineCore"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ArtVoiceInput", icon=str(PKG / "appicon.ico"),
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ArtVoiceInput", upx=False)
