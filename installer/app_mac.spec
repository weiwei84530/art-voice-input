# PyInstaller spec of the Mac app itself: onedir build/dist/ArtVoiceInput (the ArtVoiceInput executable + _internal),
# not a bundle: the launcher (packaging/mac) is the app macOS sees. Built by installer/build_mac.py.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
PKG = ROOT / "artvoiceinput"

datas = [(str(PKG / d), f"artvoiceinput/{d}") for d in ("dict", "cues", "packs")]
datas += [(str(f), "artvoiceinput/ui") for f in (PKG / "ui").glob("*.svg")]
datas += collect_data_files("opencc") + collect_data_files("pypinyin")

a = Analysis(
    [str(ROOT / "run.pyw")],
    pathex=[str(ROOT)],
    binaries=collect_dynamic_libs("sherpa_onnx"),
    datas=datas,
    hiddenimports=["artvoiceinput.mac.system", "artvoiceinput.mac.keyboard", "artvoiceinput.mac.hotkey",
                   "artvoiceinput.mac.selection", "artvoiceinput.mac.mute", "artvoiceinput.mac.autostart",
                   "ApplicationServices", "Quartz", "AppKit", "objc"],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtWebEngineCore",
              "pynput", "comtypes"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ArtVoiceInput", console=False, upx=False,
          argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ArtVoiceInput", upx=False)
