# PyInstaller spec of the setup program: onefile build/dist/setup-stub.exe. installer/build.py appends the app folder
# to a copy of it; the copy without it is the uninstaller.
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "artvoiceinput"

a = Analysis(
    [str(ROOT / "installer" / "setup_main.py")],
    pathex=[str(ROOT)],
    datas=[(str(PKG / "ui" / "check.svg"), "artvoiceinput/ui"), (str(PKG / "ui" / "down.svg"), "artvoiceinput/ui")],
    excludes=["tkinter", "numpy", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="setup-stub", icon=str(PKG / "appicon.ico"),
          console=False, upx=False)
