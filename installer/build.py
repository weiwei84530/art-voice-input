"""Build ArtVoiceInput-Setup-<version>.exe:
1. the app, PyInstaller onedir (installer/app.spec) -> build/dist/ArtVoiceInput
2. the models (X-ASR files and the VAD, from the data folder) copied into it, under models/
3. the setup program, PyInstaller onefile (installer/setup.spec) -> build/dist/setup-stub.exe
4. the app folder zipped and appended to the stub (payload.py) -> dist/ArtVoiceInput-Setup-<version>.exe

    .venv\\Scripts\\python.exe installer\\build.py [--skip-app]
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from artvoiceinput import __version__, models   # noqa: E402
from installer import payload                   # noqa: E402

BUILD = ROOT / "build"
DIST = BUILD / "dist"
APP = DIST / "ArtVoiceInput"
OUT = ROOT / "dist" / f"ArtVoiceInput-Setup-{__version__}.exe"
PYINSTALLER = Path(sys.executable).with_name("pyinstaller.exe")


def pyinstaller(spec: str):
    subprocess.run([str(PYINSTALLER), str(ROOT / "installer" / spec), "--noconfirm", "--log-level", "WARN",
                    "--distpath", str(DIST), "--workpath", str(BUILD / "work")], check=True)


def add_models():
    dest = APP / "models"
    shutil.rmtree(dest, ignore_errors=True)
    m = models.MODELS[models.MAIN_MODEL]
    src = models.DEFAULT_MODELS_DIR / m["dir"]
    (dest / m["dir"]).mkdir(parents=True)
    for name in m["files"] + ["bpe.vocab", "README.md"]:
        if (src / name).exists():
            shutil.copy2(src / name, dest / m["dir"] / name)
    shutil.copy2(models.vad_path(), dest / models.VAD_FILE)


def main():
    if "--skip-app" not in sys.argv:
        pyinstaller("app.spec")
    add_models()
    pyinstaller("setup.spec")
    OUT.parent.mkdir(exist_ok=True)
    shutil.copyfile(DIST / "setup-stub.exe", OUT)
    payload.append(OUT, APP)
    with zipfile.ZipFile(OUT) as z:   # the payload reads back
        assert "ArtVoiceInput.exe" in z.namelist()
    print(f"{OUT}  {OUT.stat().st_size / 2**20:.0f} MB")


if __name__ == "__main__":
    main()
