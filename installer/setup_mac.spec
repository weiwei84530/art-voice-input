# PyInstaller spec of the Mac setup program: build/dist/安裝阿特語音輸入法.app. installer/build_mac.py puts
# payload.tar.gz in its Resources, signs it again (ad hoc) and packs it into the .dmg.
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "artvoiceinput"

a = Analysis(
    [str(ROOT / "installer" / "setup_main.py")],
    pathex=[str(ROOT)],
    datas=[(str(PKG / "ui" / "check.svg"), "artvoiceinput/ui"), (str(PKG / "ui" / "down.svg"), "artvoiceinput/ui")],
    hiddenimports=["installer.ops_mac"],
    excludes=["tkinter", "numpy", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf",
              "pynput", "comtypes"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ArtVoiceInputSetup", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ArtVoiceInputSetup", upx=False)
app = BUNDLE(coll, name="安裝阿特語音輸入法.app", icon=str(ROOT / "packaging" / "mac" / "appicon.icns"),
             bundle_identifier="com.artvoiceinput.setup",
             info_plist={"CFBundleDisplayName": "安裝阿特語音輸入法", "NSHighResolutionCapable": True,
                         "LSMinimumSystemVersion": "11.0"})
