"""Build ArtVoiceInput-<version>-mac-<arch>.dmg on a Mac (CI: .github/workflows/mac.yml):
1. the app, PyInstaller onedir (installer/app_mac.spec) -> build/dist/ArtVoiceInput, with the models under models/
2. the launcher bundle, Art VoiceInput.app (packaging/mac): the committed one (packaging/mac/launcher/), else built
   from launcher.m and signed ad hoc (its signature must stay the same across versions: commit what CI built)
3. payload.tar.gz: app/ and the launcher bundle
4. the setup app (installer/setup_mac.spec) with the payload in its Resources, signed again ad hoc
5. a .dmg holding the setup app

    python installer/build_mac.py
"""
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from artvoiceinput import __version__   # noqa: E402
from installer import build              # noqa: E402  (add_models, shared with the Windows build)

MAC = ROOT / "packaging" / "mac"
BUILD = ROOT / "build"
DIST = BUILD / "dist"
APP = DIST / "ArtVoiceInput"
LAUNCHER = BUILD / "Art VoiceInput.app"
COMMITTED = MAC / "launcher" / "Art VoiceInput.app"
SETUP = DIST / "安裝阿特語音輸入法.app"
ARCH = platform.machine()   # arm64 / x86_64
OUT = ROOT / "dist" / f"ArtVoiceInput-{__version__}-mac-{ARCH}.dmg"


def run(*args, **kw):
    print("+", " ".join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], check=True, **kw)


def pyinstaller(spec: str):
    run(sys.executable, "-m", "PyInstaller", ROOT / "installer" / spec, "--noconfirm", "--log-level", "WARN",
        "--distpath", DIST, "--workpath", BUILD / "work")


def launcher():
    """The launcher bundle: the committed one when there is one (same signature at every release)."""
    shutil.rmtree(LAUNCHER, ignore_errors=True)
    if COMMITTED.exists():
        shutil.copytree(COMMITTED, LAUNCHER, symlinks=True)
        (LAUNCHER / "Contents" / "MacOS" / "ArtVoiceInput").chmod(0o755)
        run("codesign", "--verify", "--strict", "--verbose", LAUNCHER)
        return
    macos = LAUNCHER / "Contents" / "MacOS"
    res = LAUNCHER / "Contents" / "Resources"
    macos.mkdir(parents=True)
    res.mkdir(parents=True)
    shutil.copy2(MAC / "Info.plist", LAUNCHER / "Contents" / "Info.plist")
    shutil.copy2(MAC / "appicon.icns", res / "appicon.icns")
    run("clang", "-fobjc-arc", "-O2", "-mmacosx-version-min=11.0", "-arch", "x86_64", "-arch", "arm64",
        "-framework", "Cocoa", MAC / "launcher.m", "-o", macos / "ArtVoiceInput")
    run("codesign", "--force", "--sign", "-", "--identifier", "com.artvoiceinput.app", LAUNCHER)
    run("codesign", "--verify", "--strict", "--verbose", LAUNCHER)


def payload() -> Path:
    out = BUILD / "payload.tar.gz"
    with tarfile.open(out, "w:gz", compresslevel=6) as tar:
        tar.add(APP, "app")
        tar.add(LAUNCHER, LAUNCHER.name)
    return out


def dmg():
    stage = BUILD / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    run("ditto", SETUP, stage / SETUP.name)
    OUT.parent.mkdir(exist_ok=True)
    OUT.unlink(missing_ok=True)
    run("hdiutil", "create", "-volname", "阿特語音輸入法", "-srcfolder", stage, "-ov", "-format", "UDZO", OUT)


def main():
    if "--skip-app" not in sys.argv:
        pyinstaller("app_mac.spec")
    build.APP = APP
    build.add_models()
    launcher()
    tar = payload()
    pyinstaller("setup_mac.spec")
    shutil.copy2(tar, SETUP / "Contents" / "Resources" / "payload.tar.gz")
    run("codesign", "--force", "--deep", "--sign", "-", SETUP)
    run("codesign", "--verify", "--deep", "--strict", "--verbose", SETUP)
    dmg()
    print(f"{OUT}  {OUT.stat().st_size / 2**20:.0f} MB")


if __name__ == "__main__":
    main()
