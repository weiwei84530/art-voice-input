"""The app icon (2026-10-21, the user's pick J of https://claude.ai/artifact/JU4N5jkE3UiiURvWfUhUNK, 光澤): a rounded
square in a warm diagonal gradient (orange top left, the brand's red-orange, a little redder bottom right), a soft
curved sheen over its top, a highlight along its top edge, and the logo's white microphone over a soft dark red
shadow. Drawn on a 64 grid; `tile` alone is the base the tray's listening ring sits on. Used by the tray, the
setup wizard's badge and every window's icon (`icon`). A development copy (not `paths.FROZEN`) is blue, so it is
told apart from the installed build at a glance (2026-11-05, the user's request)."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

from . import paths

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)   # drawn for each, so 16px is not a scaled-down 256px
RADIUS = 14                                       # on the 64 grid (22%)
# the gradient top left, middle, bottom right, and the microphone's shadow
RELEASE = ("#FF6E3C", "#FF453A", "#EE3340", "#780A00")
DEVELOPMENT = ("#3CB4FF", "#2F7BF5", "#3D5AFE", "#0A2A78")
_COLORS = RELEASE if paths.FROZEN else DEVELOPMENT


def use_release():
    """The installed build's colors in a development copy: dev/build_icon.py and build_icns.py write the exe's."""
    global _COLORS
    _COLORS = RELEASE


def tile(p: QPainter, s: float):
    """The gradient square, its sheen and its top-edge highlight, filling 0..s."""
    k = s / 64
    p.save()
    p.setPen(Qt.NoPen)
    g = QLinearGradient(0, 0, s, s)
    g.setColorAt(0, QColor(_COLORS[0]))
    g.setColorAt(0.55, QColor(_COLORS[1]))
    g.setColorAt(1, QColor(_COLORS[2]))
    p.setBrush(g)
    p.drawRoundedRect(QRectF(0, 0, s, s), RADIUS * k, RADIUS * k)
    # the sheen: the top of the square down to a shallow curve
    sheen = QPainterPath()
    sheen.moveTo(0, 25 * k)
    sheen.lineTo(0, RADIUS * k)
    sheen.arcTo(QRectF(0, 0, 2 * RADIUS * k, 2 * RADIUS * k), 180, -90)
    sheen.lineTo((64 - RADIUS) * k, 0)
    sheen.arcTo(QRectF((64 - 2 * RADIUS) * k, 0, 2 * RADIUS * k, 2 * RADIUS * k), 90, -90)
    sheen.lineTo(64 * k, 25 * k)
    sheen.quadTo(32 * k, 35 * k, 0, 25 * k)
    p.setBrush(QColor(255, 255, 255, 33))
    p.drawPath(sheen)
    if s >= 24:   # a fraction of a pixel below that: only a blur on the edge
        edge = QLinearGradient(0, 0, 0, s)
        edge.setColorAt(0, QColor(255, 255, 255, 140))
        edge.setColorAt(0.45, QColor(255, 255, 255, 0))
        p.setPen(QPen(edge, 1.2 * k))
        p.setBrush(Qt.NoBrush)
        inset = 0.6 * k
        p.drawRoundedRect(QRectF(inset, inset, s - 2 * inset, s - 2 * inset), RADIUS * k - inset, RADIUS * k - inset)
    p.restore()


def mic(p: QPainter, s: float, color: QColor, dx: float = 0, dy: float = 0):
    """The logo's microphone (ui.kit.LOGO) in the square with 10% padding: capsule 20x34, the holder an arc 36 wide
    and the stem in 5-unit strokes."""
    pad = s * 0.1
    k = (s - 2 * pad) / 64
    p.save()
    p.translate(pad + dx, pad + dy)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(22 * k, 6 * k, 20 * k, 34 * k), 10 * k, 10 * k)
    pen = QPen(color, max(1.25, 5 * k))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(14 * k, 16 * k, 36 * k, 34 * k), 200 * 16, 140 * 16)   # the logo's A18 17 arc
    p.drawLine(QPointF(32 * k, 50 * k), QPointF(32 * k, 58 * k))
    p.restore()


def paint(p: QPainter, s: float):
    """The whole icon, filling 0..s."""
    tile(p, s)
    k = s / 64
    # the soft shadow: nine faint copies spread round a point 1.6 units down (Qt has no blur for a painter)
    shade = QColor(_COLORS[3])
    shade.setAlpha(18)
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            mic(p, s, shade, i * 1.1 * k, 1.6 * k + j * 1.1 * k)
    mic(p, s, QColor("#FFFFFF"))


def pixmap(s: int) -> QPixmap:
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    paint(p, s)
    p.end()
    return pm


def icon() -> QIcon:
    result = QIcon()
    for s in SIZES:
        result.addPixmap(pixmap(s))
    return result
