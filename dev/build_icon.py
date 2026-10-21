"""Writes artvoiceinput/appicon.ico from `appicon` (each size drawn on its own, stored as PNG), for the exe.

    .venv/Scripts/python dev/build_icon.py
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from artvoiceinput import appicon  # noqa: E402

OUT = ROOT / "artvoiceinput" / "appicon.ico"


def png(size: int) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    appicon.pixmap(size).save(buf, "PNG")
    return bytes(data)


def main():
    QApplication([])
    images = [(s, png(s)) for s in appicon.SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, body = b"", b""
    for s, data in images:
        side = 0 if s >= 256 else s   # 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    OUT.write_bytes(header + entries + body)
    print(f"{OUT} ({len(images)} sizes, {OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
