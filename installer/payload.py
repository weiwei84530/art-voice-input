"""The app folder rides at the end of the setup exe as a zip (zipfile reads an archive with data before it). The zip's
comment holds the stub's length, so the uninstaller is the setup exe cut before the payload."""
import zipfile
from pathlib import Path

TAG = b"ArtVoiceInput-stub:"


def append(exe: Path, folder: Path) -> None:
    """Zip folder onto the end of exe."""
    stub = exe.stat().st_size
    with zipfile.ZipFile(exe, "a", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(folder).as_posix())
        z.comment = TAG + str(stub).encode()


def open_zip(exe: Path) -> zipfile.ZipFile | None:
    """The payload of exe, None when it has none (the uninstaller)."""
    try:
        z = zipfile.ZipFile(exe)
    except zipfile.BadZipFile:
        return None
    if not z.comment.startswith(TAG):
        z.close()
        return None
    return z


def stub_size(z: zipfile.ZipFile) -> int:
    return int(z.comment[len(TAG):])
