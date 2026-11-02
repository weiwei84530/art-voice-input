"""Writes packaging/mac/appicon.icns from `appicon` (the Mac app's icon: each size drawn on its own, stored as PNG),
inset like macOS icons (the artwork takes 824 of 1024, Apple's grid), no iconutil needed.

    .venv/Scripts/python dev/build_icns.py
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from artvoiceinput import appicon  # noqa: E402

OUT = ROOT / "packaging" / "mac" / "appicon.icns"
# ICNS element types holding PNG data, by pixel size (the @2x ones share sizes with plain ones)
TYPES = [("icp4", 16), ("icp5", 32), ("ic07", 128), ("ic08", 256), ("ic09", 512), ("ic10", 1024), ("ic11", 32),
         ("ic12", 64), ("ic13", 256), ("ic14", 512)]


def png(size: int) -> bytes:
    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    art = round(size * 824 / 1024)
    p = QPainter(canvas)
    p.drawPixmap((size - art) // 2, (size - art) // 2, appicon.pixmap(art))
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    canvas.save(buf, "PNG")
    return bytes(data)


def main():
    QApplication([])
    cache: dict[int, bytes] = {}
    body = b""
    for kind, size in TYPES:
        data = cache.setdefault(size, png(size))
        body += kind.encode() + struct.pack(">I", 8 + len(data)) + data
    OUT.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)
    print(f"{OUT} ({len(TYPES)} images, {OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
