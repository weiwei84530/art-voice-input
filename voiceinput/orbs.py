"""Energy-orb looks for the floating button and the bubble (2026-10-16, the user's pick of nine mockups, all nine
kept, chosen on the 外觀 tab; the microphone icon stays as the first choice). No icon: a ball of the glow's colors,
so the button reads as the same thing as the glow around the screen while listening.

Each look draws one frame at a phase (0..1 of its loop, `_LOOPS` seconds) with every motion a whole number of
cycles per loop, so a loop of frames drawn once (`OrbPlayer`, at `FPS`) plays forever with only a pixmap copied
per frame; frames are drawn again only when the colors or the size change. (`OrbPlayer.hover` draws live, brighter
frames; the buttons no longer use it: one look at rest, the user's choice, floatbtn.OrbButton moves them instead.)

Sizes: an orb is drawn on a canvas `SCALE` times the microphone button's size, so its body is about as big as the
microphone's disc and its light has room around it (the user found every look smaller than the microphone,
2026-10-16). 節流模式 (`lite`, the 外觀 tab, off by default: looks first, the user's choice) keeps the first
version: 15 frames a second, glows blurred from a quarter of the size, fewer specks and filaments; without it 30
frames a second, glows made of smooth gradients (流光's outer light looked coarse), the full counts.
光環 and 虹膜 can be drawn without their dark disc and pupil (`dark` False; an experiment the user asked for,
2026-10-16).
"""
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QConicalGradient, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)

FPS = 15        # 節流模式
FINE_FPS = 30
SCALE = 1.4     # canvas / the microphone button's size
LOOKS = {"mic": "麥克風（原始）", "flow": "流光", "breath": "呼吸光核", "halo": "光環", "plasma": "電漿",
         "tokamak": "約束場", "corona": "日冕", "iris": "虹膜", "liquid": "液態金屬", "nebula": "星雲"}
_LOOPS = {"flow": 6.0, "breath": 12.0, "halo": 8.0, "plasma": 3.0, "tokamak": 8.0, "corona": 8.0, "iris": 8.0,
          "liquid": 8.0, "nebula": 8.0}
TAU = math.tau


def _c(color: str, alpha: float = 1.0) -> QColor:
    q = QColor(color)
    q.setAlphaF(max(0.0, min(1.0, alpha)))
    return q


def _mix(a: str, b: str, t: float) -> str:
    x, y = QColor(a), QColor(b)
    return QColor(round(x.red() + (y.red() - x.red()) * t), round(x.green() + (y.green() - x.green()) * t),
                  round(x.blue() + (y.blue() - x.blue()) * t)).name()


def _drift(colors: list, x: float) -> str:
    """A color moving through the palette: x in palette steps, cyclic."""
    n = len(colors)
    f = x % n
    i = int(f)
    return _mix(colors[i], colors[(i + 1) % n], f - i)


def _conic(cx, cy, turns: float, colors: list) -> QConicalGradient:
    g = QConicalGradient(QPointF(cx, cy), -turns * 360)
    ring = list(colors) + [colors[0]]
    for i, col in enumerate(ring):
        g.setColorAt(i / (len(ring) - 1), QColor(col))
    return g


def _radial(cx, cy, r, stops) -> QRadialGradient:
    g = QRadialGradient(QPointF(cx, cy), max(r, 0.01))
    for at, col in stops:
        g.setColorAt(at, col)
    return g


def _blurred(px: int, s: float, draw, factor: int = 4) -> QImage:
    """draw(painter) at 1/factor of px, scaled back up smoothly: a cheap blur (only for frames drawn ahead)."""
    small = QImage(max(1, px // factor), max(1, px // factor), QImage.Format_ARGB32_Premultiplied)
    small.fill(0)
    p = QPainter(small)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(small.width() / s, small.height() / s)
    draw(p)
    p.end()
    return small.scaled(px, px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def _disc(p: QPainter, cx, cy, r):
    p.drawEllipse(QPointF(cx, cy), r, r)


# --- the nine looks: draw(p, s, phase, hover, colors, px); s the size in logical px, px in device px ---

def _masked(px: int, s: float, fill, stops) -> QImage:
    """fill (a brush) over the whole canvas, its alpha cut by a radial gradient around the center: a smooth light
    in place of a blurred shape (stops: (at, alpha) along the radius s / 2)."""
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    q = QPainter(img)
    q.setRenderHint(QPainter.Antialiasing)
    q.scale(px / s, px / s)
    q.fillRect(QRectF(0, 0, s, s), fill)
    q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    q.fillRect(QRectF(0, 0, s, s), _radial(s / 2, s / 2, s / 2, [(at, _c("#000000", a)) for at, a in stops]))
    q.end()
    return img


def _flow(p, s, ph, h, colors, px, fine):
    """流光: the glow's colors flowing inside, a highlight, a soft light of the same colors around it."""
    c, r, u = s / 2, s * 0.34, ph * TAU

    def halo(q):
        q.setPen(Qt.NoPen)
        q.setBrush(_conic(c, c, ph, colors))
        _disc(q, c, c, r * 1.22)
    p.save()
    p.setOpacity(0.45 + 0.35 * h)
    if fine:   # fading out smoothly from the body's edge to the canvas's
        k = r / c
        p.drawImage(QRectF(0, 0, s, s), _masked(px, s, _conic(c, c, ph, colors),
                                                [(0, 1), (k * 0.9, 1), (k * 1.12, 0.55), (k * 1.3, 0.22), (1, 0)]))
    else:
        p.drawImage(QRectF(0, 0, s, s), _blurred(px, s, halo))
    p.restore()
    p.save()
    clip = QPainterPath()
    clip.addEllipse(QPointF(c, c), r, r)
    p.setClipPath(clip)
    p.fillRect(QRectF(0, 0, s, s), _conic(c, c, ph, colors))
    ox, oy = c + r * 0.35 * math.cos(u), c + r * 0.35 * math.sin(u)

    def swirl(q):
        q.fillRect(QRectF(0, 0, s, s), _conic(ox, oy, -ph * 2, list(reversed(colors))))
    p.setOpacity(0.6)
    p.drawImage(QRectF(0, 0, s, s), _blurred(px, s, swirl, 2 if fine else 3))
    p.setOpacity(1)
    p.fillRect(QRectF(0, 0, s, s), _radial(c - r * 0.35, c - r * 0.4, r * 0.9, [
        (0, _c("#ffffff", 0.75)), (0.35, _c("#ffffff", 0.18)), (1, _c("#ffffff", 0))]))
    p.fillRect(QRectF(0, 0, s, s), _radial(c, c, r, [(0, _c("#000000", 0)), (0.55, _c("#000000", 0)),
                                                       (1, _c("#00001e", 0.28))]))
    p.restore()


def _breath(p, s, ph, h, colors, px, fine):
    """呼吸光核: a white core in a breathing glow of the colors, no edge."""
    c, u = s / 2, ph * TAU
    n = len(colors)
    breathe = 0.5 + 0.5 * math.sin(4 * u)
    col, col2 = _drift(colors, ph * n), _drift(colors, ph * n + 1.5)
    R = s * (0.44 + 0.04 * breathe)
    p.setPen(Qt.NoPen)
    p.setBrush(_radial(c, c, R, [(0, _c("#ffffff", 0.95)), (0.16 + 0.04 * h, _c(_mix(col, "#ffffff", 0.55), 0.95)),
                                 (0.42, _c(col, 0.75 + 0.2 * h)), (0.72, _c(col2, 0.25 + 0.15 * breathe)),
                                 (1, _c(col2, 0))]))
    _disc(p, c, c, R)


def _halo(p, s, ph, h, colors, px, fine, dark=True):
    """光環: a dark glass disc in a turning ring of the colors."""
    c, r = s / 2, s * 0.32

    def glow(q):
        q.setPen(QPen(_conic(c, c, ph, colors), s * 0.12))
        q.setBrush(Qt.NoBrush)
        _disc(q, c, c, r)
    p.save()
    p.setOpacity(0.55 + 0.35 * h)
    if fine:   # a ring of light fading both ways from the ring
        k = r / c
        p.drawImage(QRectF(0, 0, s, s), _masked(px, s, _conic(c, c, ph, colors),
                                                [(k * 0.7, 0), (k, 0.85), (k * 1.18, 0.4), (k * 1.4, 0.12), (1, 0)]))
    else:
        p.drawImage(QRectF(0, 0, s, s), _blurred(px, s, glow))
    p.restore()
    p.setPen(Qt.NoPen)
    if dark:
        p.setBrush(_radial(c - r * 0.3, c - r * 0.3, r * 1.3, [(0, QColor("#3a3f4c")), (1, QColor("#16181e"))]))
        _disc(p, c, c, r * 0.97)
    p.setPen(QPen(_conic(c, c, ph, colors), s * (0.045 + 0.02 * h)))
    p.setBrush(Qt.NoBrush)
    _disc(p, c, c, r)
    core = _drift(colors, ph * len(colors))
    p.setPen(Qt.NoPen)
    p.setBrush(_radial(c, c, r * 0.5, [(0, _c(core, 0.55 + 0.3 * h)), (1, _c(core, 0))]))
    _disc(p, c, c, r * 0.5)


def _plasma(p, s, ph, h, colors, px, fine):
    """電漿: blobs of the colors passing through each other, a white-hot center, a soft round edge."""
    c, R, u = s / 2, s * 0.45, ph * TAU
    layer = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    layer.fill(0)
    q = QPainter(layer)
    q.setRenderHint(QPainter.Antialiasing)
    q.scale(px / s, px / s)
    q.setCompositionMode(QPainter.CompositionMode_Plus)
    n = max(4, len(colors) + 1)
    for i in range(n):
        a = u * (1 if i % 2 else -1) + i * 2.1
        rr = R * (0.28 + 0.18 * math.sin(2 * u + i))
        x, y = c + math.cos(a) * rr, c + math.sin(a + 0.6) * rr
        col = colors[i % len(colors)]
        q.fillRect(QRectF(0, 0, s, s), _radial(x, y, R * 0.9, [(0, _c(col, 0.7 + 0.25 * h)), (0.5, _c(col, 0.22)),
                                                                 (1, _c(col, 0))]))
    q.fillRect(QRectF(0, 0, s, s), _radial(c, c, R * 0.45, [(0, _c("#ffffff", 0.95)), (0.4, _c("#ffffff", 0.35)),
                                                             (1, _c("#ffffff", 0))]))
    q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    q.fillRect(QRectF(0, 0, s, s), _radial(c, c, R * 1.15, [(0, _c("#000000", 1)), (0.48, _c("#000000", 1)),
                                                             (1, _c("#000000", 0))]))
    q.end()
    p.drawImage(QRectF(0, 0, s, s), layer)


def _tokamak(p, s, ph, h, colors, px, fine):
    """約束場: a hot core inside tilted orbits, a spark running on each."""
    c, R, u = s / 2, s * 0.36, ph * TAU
    rings = 3 if fine or s >= _SMALL else 2
    hc = _drift(colors, ph * len(colors))
    p.save()
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    p.fillRect(QRectF(0, 0, s, s), _radial(c, c, R * 1.25, [(0, _c(hc, 0.35 + 0.2 * h)), (1, _c(hc, 0))]))
    for i in range(rings):
        col = colors[(i * 2) % len(colors)]
        tilt = i * 180 / rings + math.degrees(u / 2) * (-1 if i % 2 else 1)   # half a turn a loop: an ellipse
        p.save()
        p.translate(c, c)
        p.rotate(tilt)
        p.setPen(QPen(_c(col, 0.75), max(0.8, s * 0.018)))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), R, R * 0.34)
        a = 2 * u + i * 2
        sx, sy = math.cos(a) * R, math.sin(a) * R * 0.34
        p.setPen(Qt.NoPen)
        p.setBrush(_radial(sx, sy, s * 0.09, [(0, _c("#ffffff", 0.95)), (0.4, _c(col, 0.7)), (1, _c(col, 0))]))
        _disc(p, sx, sy, s * 0.09)
        p.restore()
    pulse = 0.5 + 0.5 * math.sin(3 * u)
    rc = R * (0.36 + 0.05 * pulse + 0.08 * h)
    p.setPen(Qt.NoPen)
    p.setBrush(_radial(c, c, rc, [(0, _c("#ffffff", 1)), (0.45, _c(_mix(hc, "#ffffff", 0.5), 0.9)),
                                  (1, _c(hc, 0))]))
    _disc(p, c, c, rc)
    p.restore()


def _corona(p, s, ph, h, colors, px, fine):
    """日冕: a white-hot core, flickering filaments, a soft halo."""
    c, R, u = s / 2, s * 0.2, ph * TAU
    n = len(colors)
    hc = _drift(colors, ph * n)
    p.save()
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    p.fillRect(QRectF(0, 0, s, s), _radial(c, c, s * 0.48, [(0, _c(hc, 0.45)), (R * 0.5 / (s * 0.48), _c(hc, 0.45)),
                                                             (1, _c(hc, 0))]))
    # 28 at first; the slowest look to draw, so 節流模式 has fewer (2026-10-16)
    count = (20 if s < _SMALL else 28) if fine else (12 if s < _SMALL else 20)
    for i in range(count):
        a = i / count * TAU + math.sin(u + i) * 0.08
        flick = 0.5 + 0.5 * math.sin((4 + i % 5) * u + i * 1.7)
        length = R * (0.5 + 0.9 * flick * (0.6 + 0.4 * math.sin(i * 2.3))) * (1 + 0.5 * h)
        col = _drift(colors, ph * n + i / count * n)
        x0, y0 = c + math.cos(a) * R * 0.85, c + math.sin(a) * R * 0.85
        x1, y1 = c + math.cos(a) * (R + length), c + math.sin(a) * (R + length)
        g = QLinearGradient(x0, y0, x1, y1)
        g.setColorAt(0, _c(col, 0.8))
        g.setColorAt(1, _c(col, 0))
        pen = QPen(g, max(0.8, s * 0.022))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    p.setPen(Qt.NoPen)
    p.setBrush(_radial(c, c, R * 1.1, [(0, _c("#ffffff", 1)), (0.6, _c(_mix(hc, "#ffffff", 0.6), 0.95)),
                                       (1, _c(hc, 0))]))
    _disc(p, c, c, R * 1.1)
    p.restore()


def _iris(p, s, ph, h, colors, px, fine, dark=True):
    """虹膜: thin rings of the colors around a dark pupil, focusing in and out."""
    c, R, u = s / 2, s * 0.36, ph * TAU
    focus = 0.5 + 0.5 * math.sin(2 * u)
    pupil = R * (0.26 + 0.06 * focus + 0.08 * h)
    n = 7 if s >= _SMALL else (5 if fine else 4)
    hc = _drift(colors, ph * len(colors))
    p.setPen(Qt.NoPen)
    p.fillRect(QRectF(0, 0, s, s), _radial(c, c, R * 1.2, [(0, _c(hc, 0)), (0.5, _c(hc, 0.3 + 0.25 * h)),
                                                            (1, _c(hc, 0))]))
    if dark:
        p.setBrush(QColor("#14161c"))
        _disc(p, c, c, R)
    p.setBrush(Qt.NoBrush)
    for i in range(n):
        f = i / (n - 1)
        r = pupil + (R - pupil) * (0.15 + 0.85 * f) * (0.94 + 0.06 * math.sin(2 * u - f * 3))
        p.setOpacity(min(1.0, 0.35 + 0.5 * (1 - f) + 0.15 * h))
        p.setPen(QPen(_conic(c, c, ph * (1 if i % 2 else -1) + i / 7, colors), max(0.7, s * 0.016)))
        _disc(p, c, c, r)
    p.setOpacity(1)
    p.setPen(Qt.NoPen)
    if not dark:
        return
    p.setBrush(_radial(c, c, pupil, [(0, QColor("#05060a")), (0.8, QColor("#0b0d12")), (1, _c(hc, 0.6))]))
    _disc(p, c, c, pupil)
    p.setBrush(_c("#ffffff", 0.75))
    _disc(p, c - pupil * 0.35, c - pupil * 0.4, max(1.0, pupil * 0.18))


def _liquid(p, s, ph, h, colors, px, fine):
    """液態金屬: a softly wobbling drop of the colors with a metallic sheen."""
    c, R, u = s / 2, s * 0.34, ph * TAU
    wob = 0.06 + 0.05 * h
    path = QPainterPath()
    points = 128 if fine else 64
    for i in range(points + 1):
        a = i / points * TAU
        r = R * (1 + wob * math.sin(3 * a + 2 * u) + wob * 0.7 * math.sin(2 * a - u)
                 + wob * 0.4 * math.sin(5 * a + 3 * u))
        pt = QPointF(c + math.cos(a) * r, c + math.sin(a) * r)
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    glow = _drift(colors, ph * len(colors))
    p.setPen(Qt.NoPen)
    p.fillRect(QRectF(0, 0, s, s), _radial(c, c, R * 1.4, [(0, _c(glow, 0.7 + 0.2 * h)), (0.6, _c(glow, 0.35)),
                                                            (1, _c(glow, 0))]))
    p.fillPath(path, _conic(c, c, ph, colors))
    p.save()
    p.setClipPath(path)
    g = QLinearGradient(c - R, c - R + math.sin(u) * R * 0.4, c + R, c + R)
    g.setColorAt(0, _c("#ffffff", 0.75))
    g.setColorAt(0.3, _c("#ffffff", 0.08))
    g.setColorAt(0.55, _c("#ffffff", 0))
    g.setColorAt(0.8, _c("#000014", 0.25))
    p.fillRect(QRectF(0, 0, s, s), g)
    p.restore()


def _nebula(p, s, ph, h, colors, px, fine):
    """星雲: specks orbiting a soft core with short trails."""
    c, R, u = s / 2, s * 0.42, ph * TAU
    hc = _drift(colors, ph * len(colors))
    p.save()
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    p.fillRect(QRectF(0, 0, s, s), _radial(c, c, R, [(0, _c(_mix(hc, "#ffffff", 0.5), 0.8 + 0.2 * h)),
                                                      (0.35, _c(hc, 0.35)), (1, _c(hc, 0))]))
    p.setPen(Qt.NoPen)
    # 24 specks with 5-dot trails at first, 3x slower to draw than the other looks: 節流模式 has fewer (2026-10-16)
    n = (16 if s < _SMALL else 24) if fine else (10 if s < _SMALL else 16)
    trail = 5 if fine else 3
    for i in range(n):
        orbit = R * (0.25 + 0.7 * ((i * 0.618) % 1))
        laps = max(1, round(0.9 / (0.3 + orbit / R) * _LOOPS["nebula"] / TAU)) * (-1 if i % 3 == 0 else 1)
        a = laps * u + i * 2.4
        tilt = 0.55 + 0.35 * ((i * 0.37) % 1)
        col = colors[i % len(colors)]
        for k in range(trail):   # the head and its trail
            ak = a - k * 0.42 / trail * (1 if laps > 0 else -1)
            p.setBrush(_c(_mix(col, "#ffffff", 0.6) if k == 0 else col, (1 - k / trail) * 0.85))
            _disc(p, c + math.cos(ak) * orbit, c + math.sin(ak) * orbit * tilt,
                  max(0.6, s * (0.017 if fine else 0.014) * (1 - k / (trail + 1))))
    p.restore()


_SMALL = 50   # a canvas below this (the bubble's) gets fewer details

_DRAW = {"flow": _flow, "breath": _breath, "halo": _halo, "plasma": _plasma, "tokamak": _tokamak,
         "corona": _corona, "iris": _iris, "liquid": _liquid, "nebula": _nebula}


def palette(style) -> list:
    """The colors of a glow style (glow.Style, None for 彩虹), without the stop that closes its ring."""
    if style is None:
        return ["#3d7bff", "#a259ff", "#ff4fa3", "#ff9f43", "#29d3ff"]
    cols = list(style.colors)
    return cols[:-1] if len(cols) > 2 and cols[0] == cols[-1] else cols


def canvas(size: int) -> int:
    """The canvas of an orb for a button of size px (the microphone's disc)."""
    return round(size * SCALE)


def draw(look: str, size: float, ratio: float, phase: float, hover: float, colors: list,
         fine: bool = True, dark: bool = True) -> QPixmap:
    """One frame of a look: size logical px (the canvas), device pixel ratio, phase 0..1 of its loop."""
    px = max(1, round(size * ratio))
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(px / size, px / size)
    kw = {"dark": dark} if look in ("halo", "iris") else {}
    _DRAW[look](p, size, phase, hover, colors, px, fine, **kw)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(px / size)
    return pm


class OrbPlayer:
    """The frames of one look at one size, played while its widget shows: update() is called at the frame rate.
    size is the button's (the microphone's disc); the orb fills `canvas(size)`, the widget's size."""

    def __init__(self, widget, size: int):
        self.widget = widget
        self.size = canvas(size)
        self.look = "mic"
        self.colors = ["#3d7bff", "#a259ff", "#ff4fa3", "#ff9f43", "#29d3ff"]
        self.lite = False
        self.dark = True
        self.hover = False
        self._frames: list = []
        self._key = None
        self._t0 = time.monotonic()
        self._timer = QTimer(widget, interval=1000 // FINE_FPS, timeout=widget.update)

    def set_look(self, look: str, colors: list, lite: bool = False, dark: bool = True):
        self.look = look if look in LOOKS else "mic"
        self.colors = list(colors) or self.colors
        self.lite = lite
        self.dark = dark
        self._frames = []
        self._timer.setInterval(1000 // (FPS if lite else FINE_FPS))
        if self.look == "mic":
            self._timer.stop()
        self.widget.update()

    def start(self):
        if self.look != "mic":
            self._timer.start()

    def stop(self):
        self._timer.stop()

    def _phase(self) -> float:
        return ((time.monotonic() - self._t0) / _LOOPS[self.look]) % 1.0

    def paint(self, p: QPainter) -> bool:
        """Draw the current frame; False for the microphone look (the widget draws its own)."""
        if self.look == "mic":
            return False
        ratio = self.widget.devicePixelRatioF()
        fine = not self.lite
        key = (self.look, tuple(self.colors), ratio, fine, self.dark)
        if self.hover:   # drawn live while the pointer is on it
            p.drawPixmap(0, 0, draw(self.look, self.size, ratio, self._phase(), 1.0, self.colors, fine, self.dark))
            return True
        if key != self._key or not self._frames:   # drawn as they first play: no pause to draw a whole loop
            self._frames = [None] * round(_LOOPS[self.look] * (FINE_FPS if fine else FPS))
            self._key = key
        i = int(self._phase() * len(self._frames)) % len(self._frames)
        if self._frames[i] is None:
            self._frames[i] = draw(self.look, self.size, ratio, i / len(self._frames), 0.0, self.colors, fine,
                                   self.dark)
        p.drawPixmap(0, 0, self._frames[i])
        return True
