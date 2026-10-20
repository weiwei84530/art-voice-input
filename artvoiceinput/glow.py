"""A glow along the screen's edges while listening, like Siri's (the user's request, 2026-10-15; a style picked on
the 外觀 tab, off by default). It brightens and reaches further in with the voice (the user's choice).

Four thin windows along the edges, not one over the whole screen: a translucent window is handed to Windows whole
at every frame. Each strip is drawn at a third of its size and scaled up (the glow is soft anyway): its colors
filled with one gradient, then cut by a falloff mask computed once per level when it shows. Stroking the glow as
ten wide gradient lines each frame took more than a whole CPU core (2026-10-15); now ~10-20% of one
core at 24 frames a second (12 when quiet), most of it Windows compositing the strips.
UI Automation looks through the strips (checked: the elements under the screen's edges are the same with and
without them), so terminal selections near the edges still work."""
import math
import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QWidget

DEPTH = 72          # px of the screen each strip covers, the glow's widest
_SCALE = 3          # strips are drawn at 1/_SCALE and scaled up
FADE_MS = 220       # the glow fades in and out in this time (the floating button and the bubble move with it)
_LEVELS = 12        # falloff masks from quiet to loud
_FPS = 24          # 柔光, and every motion with 節流模式
# 波浪 / 流星 / 漣漪 without 節流模式 (the user's request, 2026-10-16: 流星 did not look smooth). Measured on the
# user's screen (1920x1080, i5-8500, this process only; Windows' compositing not counted): 柔光 ~17% of a core at
# 24 fps (~26% at 36, ~34% at 48), 流星 ~32% at 24, ~50-59% at 48; most of it is the strips painted at full size and
# handed to Windows, which grows with the frame rate. The colors used to be a conical gradient painted by Qt each
# frame (流星 ~44% at 24 fps). The CPU slows down between frames, so a frame costs ~4x what a busy loop measures.
FINE_FPS = 48


@dataclass(frozen=True)
class Style:
    id: str
    name: str
    colors: tuple       # stops around the screen (conical gradient), first = last
    turn: float         # turns per second of the colors around the screen (0: still)
    pulse: float        # breathing when quiet: 0 none, 1 strong
    depth: float = 1.0  # how far in it reaches, times DEPTH
    bright: float = 1.0  # opacity, times the usual


STYLES = [
    Style("siri", "彩虹", ("#3d7bff", "#a259ff", "#ff4fa3", "#ff9f43", "#29d3ff", "#3d7bff"), 0.18, 0.2),
    Style("aurora", "極光", ("#14e8b5", "#2fa8ff", "#7b5cff", "#14e8b5", "#5cffd0", "#14e8b5"), 0.08, 0.3),
    Style("sunset", "暖陽", ("#ff7a3d", "#ff3d6e", "#ffc23d", "#ff7a3d", "#ff5c8a", "#ff7a3d"), 0.1, 0.3),
    Style("ocean", "冰藍", ("#7fd6ff", "#3a8dff", "#c8f0ff", "#7fd6ff", "#4fa8ff", "#7fd6ff"), 0.06, 0.4),
    Style("red", "錄音紅", ("#ff453a", "#ff6b5e", "#ff2d20", "#ff453a"), 0.0, 1.0),
    # added 2026-10-16 (the user's requests): 草本, quiet Japanese greens (青磁 celadon, 抹茶, 苔 moss, a pale washi
    # green), turning slowly, for a calm, zen feel; 紫金, a rainbow of purple flowing into orange-yellow and back
    Style("herb", "草本", ("#7ebea5", "#a8c97f", "#5b8a72", "#d8e3c3", "#8aa88a", "#7ebea5"), 0.05, 0.25),
    Style("violet", "紫金", ("#6d4aff", "#b05cff", "#ff7a59", "#ffb340", "#ff9a3c", "#9b4dff", "#6d4aff"), 0.1, 0.3),
]
BY_ID = {s.id: s for s in STYLES}
# every style's parameters can be changed on the 外觀 tab (2026-10-16, the user's design, replacing a separate 自訂
# style): config.glow_edits holds the changed ones per style id, 恢復預設 drops them. The edges are one of them
# (2026-10-21, the user's request: one setting for every style, not shown as an edit, read wrong)
PARAM_KEYS = ("colors", "turn", "pulse", "depth", "bright", "edges")
MAX_COLORS = 6


def params(style: Style) -> dict:
    """A style's parameters as config.glow_edits holds them: its colors (2-MAX_COLORS) without the repeated last one
    (cut to 4 until 2026-10-16: changing any slider of 彩虹 dropped its fifth color)."""
    colors = list(style.colors[:-1]) if style.colors[0] == style.colors[-1] else list(style.colors)
    return {"colors": colors[:MAX_COLORS], "turn": style.turn, "pulse": style.pulse, "depth": style.depth,
            "bright": style.bright, "edges": "all"}


def edited(style_id: str, edits: dict | None) -> bool:
    """The style's parameters differ from its defaults."""
    preset = BY_ID.get(style_id)
    e = (edits or {}).get(style_id)
    return bool(preset and e) and {**params(preset), **e} != params(preset)


def edges_for(style_id: str, edits: dict | None) -> str:
    """Which edges the style glows on (EDGES), all unless changed."""
    edges = ((edits or {}).get(style_id) or {}).get("edges", "all")
    return edges if edges in EDGES else "all"


def style_for(style_id: str, edits: dict | None) -> Style | None:
    """The style picked, with the user's changes to it (config.glow_edits); None for no glow."""
    preset = BY_ID.get(style_id)
    if preset is None:
        return None
    e = (edits or {}).get(style_id)
    if not e:
        return preset
    c = {**params(preset), **{k: v for k, v in e.items() if k in PARAM_KEYS}}
    colors = [x for x in c["colors"] if QColor(x).isValid()] or list(params(preset)["colors"])
    return Style(preset.id, preset.name, tuple(colors + [colors[0]]), float(c["turn"]), float(c["pulse"]),
                 min(max(float(c["depth"]), 0.4), 2.0), min(max(float(c["bright"]), 0.3), 1.6))
# how it moves (the 外觀 tab, 2026-10-16, the user's request for three, one of them waves): 柔光 is the glow as it
# was (falloff masks made once per level); the others compute their mask every frame (motion_mask)
MOTIONS = {"soft": "柔光", "wave": "波浪", "comet": "流星", "ripple": "漣漪"}
_REACH = {"soft": 1.0, "wave": 1.9, "comet": 1.5, "ripple": 1.0}   # strip depth, times the style's
# which edges glow (the 外觀 tab, 2026-10-16, the user's request): id -> (label, top, bottom, left, right)
EDGES = {"all": ("上下左右", True, True, True, True), "tb": ("上下", True, True, False, False),
         "lr": ("左右", False, False, True, True), "top": ("上", True, False, False, False),
         "bottom": ("下", False, True, False, False)}


def _strength(level: int) -> float:
    """How far in and how bright the glow is at a mask level (0 quiet .. _LEVELS - 1 loud)."""
    return 0.45 + 0.55 * level / (_LEVELS - 1)


def _profile(dist: np.ndarray, strength: float, depth: float = 1.0, bright: float = 1.0) -> np.ndarray:
    """Opacity at `dist` px from an edge: bright at the edge, fading inward."""
    x = np.clip(dist / (DEPTH * depth * strength), 0, 1)
    return np.clip((1 - x) ** 2.4 * (0.35 + 0.6 * strength) * bright, 0, 1)


def mask(screen: QRect, rect: QRect, strength: float, edges=(True, True, True, True), depth: float = 1.0,
         bright: float = 1.0) -> np.ndarray:
    """The falloff over `rect` (screen coordinates) at 1/_SCALE: the glow's opacity 0..1 per pixel (float32), every
    glowing edge of the screen counted (so a strip's corners match its neighbours'); edges: (top, bottom, left,
    right)."""
    w, h = -(-rect.width() // _SCALE), -(-rect.height() // _SCALE)
    xs = rect.left() - screen.left() + (np.arange(w) + 0.5) * _SCALE
    ys = rect.top() - screen.top() + (np.arange(h) + 0.5) * _SCALE
    X, Y = np.meshgrid(xs, ys)
    keep = np.ones_like(X)
    for on, dist in zip(edges, (Y, screen.height() - Y, X, screen.width() - X)):
        if on:
            keep *= 1 - _profile(dist, strength, depth, bright)
    return np.clip(1 - keep, 0, 1).astype(np.float32)


_LUT = ((1 - np.linspace(0, 1, 1024)) ** 2.4).astype(np.float32)   # the falloff's shape, looked up per pixel


def _falloff(dist: np.ndarray, reach, gain) -> np.ndarray:
    """_profile through the table: reach (px) and gain (opacity) may be arrays that broadcast with dist."""
    i = np.minimum(dist / reach, np.float32(1.0)) * np.float32(1023)
    return _LUT[i.astype(np.intp)] * gain


def geometry(screen: QRect, rect: QRect, edges) -> dict:
    """Per pixel of a strip at 1/_SCALE (screen coordinates): for each glowing edge within reach (top, bottom,
    left, right) the part of the strip near it with the distance to it and the position along it; the nearest
    edge's distance, and the place around the screen's perimeter (clockwise from the top-left corner)."""
    w, h = -(-rect.width() // _SCALE), -(-rect.height() // _SCALE)
    xs = rect.left() - screen.left() + (np.arange(w) + 0.5) * _SCALE
    ys = rect.top() - screen.top() + (np.arange(h) + 0.5) * _SCALE
    X, Y = np.meshgrid(xs, ys)
    W, H = screen.width(), screen.height()
    top, bottom, left, right = edges
    sides = []   # (distance, along, perimeter place)
    if top:
        sides.append((Y, X, X))
    if right:
        sides.append((W - X, Y, W + Y))
    if bottom:
        sides.append((H - Y, W - X, W + H + (W - X)))
    if left:
        sides.append((X, H - Y, 2 * W + H + (H - Y)))
    D = np.stack([d for d, _, _ in sides])
    near = D.argmin(0)
    cutoff = min(rect.width(), rect.height()) + _SCALE   # the strip's depth: nothing reaches further in
    close = []
    for dist, along, _ in sides:
        rows, cols = np.nonzero(dist < cutoff)
        if len(rows):   # only that part of the strip: in the top strip the left edge matters near the corner
            sl = (slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1))
            a = along[sl]
            a = a[:1, :] if np.all(a == a[:1, :]) else a[:, :1]   # along an edge: one row or one column
            close.append((sl, dist[sl].astype(np.float32), a.astype(np.float32)))
    P = np.choose(near, [pp for _, _, pp in sides])
    return {"w": w, "h": h, "sides": close, "dmin": D.min(0).astype(np.float32),
            "Pi": (P // _SCALE).astype(np.intp), "L": 2 * (W + H)}


def comet_speed(st: Style, level: float) -> float:
    """流星's heads, in laps of the screen per second: faster with the voice."""
    return (0.08 + st.turn * 0.4) * (1 + 0.6 * level)


def motion_mask(geo: dict, motion: str, st: Style, t: float, level: float, lap: float = 0.0) -> np.ndarray:
    """A strip's falloff for a moving glow at t seconds, level 0..1 (the voice): 波浪 rolls the glow's inner edge
    along the screen's edges in waves that grow with the voice; 流星 sends two bright heads with tails around the
    screen over a faint glow, `lap` the laps they have run (comet_speed summed over the frames: computed from t
    times the speed, a change of voice moved them t times as far at once, so they leapt about while speaking)."""
    strength = np.float32(0.45 + 0.55 * min(1.0, level))
    reach = np.float32(DEPTH * st.depth)
    bright = np.float32(st.bright)
    if motion == "wave":
        keep = np.ones((geo["h"], geo["w"]), np.float32)
        amp = 0.32 + 0.4 * level
        for sl, dist, along in geo["sides"]:
            mod = (1 + amp * np.sin(along / 40.0 - t * 2.6)) * (1 + 0.18 * np.sin(along / 97.0 + t * 1.3))
            sm = strength * mod
            keep[sl] *= 1 - _falloff(dist, reach * sm, np.minimum((0.35 + 0.6 * sm) * bright, 1.0))
        a = 1 - keep
    elif motion == "comet":
        L = geo["L"]
        P = np.arange(L // _SCALE + 2) * _SCALE   # the band along the perimeter, then looked up per pixel
        band = np.zeros(len(P))
        for k in range(2):
            behind = ((lap % 1.0) * L + k * L / 2 - P) % L   # px behind the head
            tail = np.exp(-np.minimum(behind, L * 0.3) / (L * 0.05)) * (behind < L * 0.3)
            front = np.exp(-np.minimum((L - behind) / 70.0, 6.0) ** 2)   # the head fades in ahead of it
            band = np.maximum(band, tail + front)
        band = band.astype(np.float32)[geo["Pi"]]
        sb = strength * (np.float32(0.5) + np.float32(0.95) * band)
        a = _falloff(geo["dmin"], reach * sb, np.minimum((np.float32(0.35) + np.float32(0.6) * sb) * bright, 1.0)) \
            * (np.float32(0.3) + np.float32(0.9) * band)
    else:   # ripple
        d = geo["dmin"]
        a = _falloff(d, reach * strength * 0.75, (0.35 + 0.45 * strength) * st.bright * 0.5)
        for k in range(3):
            ph = (t / 1.8 + k / 3) % 1.0
            ring = np.exp(-((d - ph * reach * 0.95) / 14.0) ** 2) * (1 - ph) ** 1.6
            a = np.maximum(a, ring * (0.4 + 0.55 * level) * st.bright)
    return np.clip(a, 0, 1).astype(np.float32, copy=False)


def frame(style: Style, t: float, level: float) -> tuple[int, float]:
    """(mask level, angle of the colors) at t seconds, level 0..1 (the voice)."""
    breathe = 0.5 + 0.5 * math.sin(t * 2.2)
    energy = max(level, style.pulse * 0.35 * breathe)   # quiet: a faint breathing glow
    return min(_LEVELS - 1, round(energy * (_LEVELS - 1))), round(-t * style.turn * 360, 1)


_TURN = 1024   # steps of the colors around the screen


def angles(screen: QRect, rect: QRect) -> np.ndarray:
    """Per pixel of `rect` at 1/_SCALE: where it lies around the screen's center, 0.._TURN - 1, as a conical
    gradient at angle 0 places its colors (counterclockwise from 3 o'clock)."""
    w, h = -(-rect.width() // _SCALE), -(-rect.height() // _SCALE)
    xs = rect.left() + (np.arange(w) + 0.5) * _SCALE - (screen.left() + screen.width() / 2)
    ys = rect.top() + (np.arange(h) + 0.5) * _SCALE - (screen.top() + screen.height() / 2)
    X, Y = np.meshgrid(xs, ys)
    t = (np.degrees(np.arctan2(-Y, X)) / 360.0) % 1.0
    return (t * _TURN).astype(np.int32) % _TURN


def colors_lut(style: Style) -> np.ndarray:
    """(3, _TURN) float32: the style's colors around the screen (its stops evenly spaced, the last = the first)."""
    stops = [QColor(c) for c in style.colors]
    at = np.linspace(0, 1, len(stops))
    x = np.arange(_TURN) / _TURN
    return np.stack([np.interp(x, at, [getattr(c, ch)() for c in stops]) for ch in ("red", "green", "blue")]
                    ).astype(np.float32)


def render(lut: np.ndarray, turn_at: np.ndarray, alpha: np.ndarray, angle: float) -> QImage:
    """A strip at 1/_SCALE: its colors (lut, placed by `angles`) turned to angle (degrees, as QConicalGradient's
    start angle), its opacity alpha. Looked up with numpy: a conical gradient painted by Qt took 4ms a frame for the
    four strips, most of the glow's own time (2026-10-16)."""
    shift = int(round(angle / 360.0 * _TURN))
    idx = (turn_at - shift) & (_TURN - 1)
    a = alpha * np.float32(255)
    r, g, b = (lut[i][idx] * alpha for i in range(3))
    argb = np.ascontiguousarray((a.astype(np.uint32) << 24) | (r.astype(np.uint32) << 16)
                                | (g.astype(np.uint32) << 8) | b.astype(np.uint32))
    h, w = alpha.shape
    return QImage(argb.tobytes(), w, h, w * 4, QImage.Format_ARGB32_Premultiplied).copy()


def _click_through(widget):
    import ctypes
    hwnd = int(widget.winId())
    GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TRANSPARENT, WS_EX_TOPMOST = -20, 0x08000000, 0x20, 0x8
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOPMOST)


class _Strip(QWidget):
    """One edge's window: shows its rendered part of the glow, scaled up."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.image: QImage | None = None
        self.masks: list = []          # 柔光: the falloff per level
        self.geo: dict | None = None   # the other motions: what motion_mask needs
        self.turn_at = None            # where each pixel lies around the screen (angles)
        self.on = False                # its edge glows

    def paintEvent(self, _):
        if self.image is None:
            return
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(self.rect(), self.image)
        p.end()


class EdgeGlow:
    def __init__(self, level_source):
        self._level_source = level_source   # callable -> float 0..1
        self._strips = [_Strip() for _ in range(4)]
        self._style: Style | None = None
        self._screen = QRect()
        self._level = 0.0
        self._t0 = time.monotonic()
        self._lap, self._lap_t = 0.0, 0.0   # 流星: laps run, and when they were counted (seconds since _t0)
        self._timer = QTimer(interval=1000 // _FPS, timeout=self._tick)
        self.fps = _FPS
        self.lite = True
        self._fades = []
        for s in self._strips:
            fade = QPropertyAnimation(s, b"windowOpacity", duration=FADE_MS)
            fade.finished.connect(lambda s=s, f=fade: s.hide() if f.endValue() == 0.0 else None)
            self._fades.append(fade)
        self._on = False
        self._shown = None   # the frame drawn last (frame())
        self._masks = {}     # (x, y, w, h, edges, depth, bright) of a screen -> each strip's masks
        self._ticks = 0
        self.edges = "all"
        self.motion = "soft"

    @property
    def style(self) -> "Style | None":
        return self._style

    def set_style(self, style: "Style | None"):
        """A Style (style_for), or None for no glow; shown at once in the new style when on."""
        old, self._style = self._style, style
        self._lut = colors_lut(style) if style is not None else None
        self._shown = None
        if style is None:
            self.hide_now()
        elif old is None or (old.depth, old.bright) != (style.depth, style.bright):
            screen = QGuiApplication.screenAt(self._screen.center()) if self._on else None
            self._screen = QRect()   # the masks depend on them: placed again
            if self._on:
                self._place(screen)
                self._render()
                for s in self._strips:
                    s.update()

    def set_lite(self, lite: bool):
        """節流模式: every motion at _FPS frames a second; without it the moving ones at FINE_FPS."""
        self.lite = lite
        self._set_fps()

    def _set_fps(self):
        self.fps = _FPS if self.lite or self.motion == "soft" else FINE_FPS
        self._timer.setInterval(1000 // self.fps)

    def set_edges(self, edges: str):
        if edges not in EDGES:
            edges = "all"
        if edges != self.edges:
            self.edges = edges
            self._screen = QRect()   # placed again at the next show
            self.hide_now()

    def set_motion(self, motion: str):
        if motion not in MOTIONS:
            motion = "soft"
        if motion != self.motion:
            self.motion = motion
            self._set_fps()
            self._screen = QRect()   # strips of another depth: placed again at the next show
            if self._on:
                screen = QGuiApplication.screenAt(QCursor.pos())
                self._place(screen)
                self._shown = None
                self._render()
                for s in self._strips:
                    s.update()

    def show(self, screen=None):
        if self._style is None or self._on:
            return
        self._on = True
        self._place(screen)
        self._t0 = time.monotonic()
        self._lap, self._lap_t = 0.0, 0.0
        self._level = 0.0
        self._shown = None
        self._render()
        for s, fade in zip(self._strips, self._fades):
            if not s.on:
                continue   # an edge that does not glow
            s.setWindowOpacity(0.0)
            s.show()
            _click_through(s)
            fade.stop()
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.start()
        self._timer.start()

    def move(self, screen):
        """While shown: to another screen at once (the pointer went there, 2026-10-15)."""
        if self._on and screen is not None and screen.geometry() != self._screen:
            self._place(screen)
            self._shown = None
            self._render()
            for s in self._strips:
                s.update()

    def _place(self, screen):
        """The strips along `screen`'s edges, with their masks (made once per screen size and place)."""
        g = (screen or QGuiApplication.primaryScreen()).geometry()
        if g == self._screen:
            return
        self._screen = g
        st = self._style or STYLES[0]
        d = min(round(DEPTH * st.depth * _REACH[self.motion]), g.height() // 4, g.width() // 4)
        _, top, bottom, left, right = EDGES[self.edges]
        side_top, side_h = g.top() + (d if top else 0), g.height() - (d if top else 0) - (d if bottom else 0)
        rects = [QRect(g.left(), g.top(), g.width(), d) if top else None,
                 QRect(g.left(), g.bottom() - d + 1, g.width(), d) if bottom else None,
                 QRect(g.left(), side_top, d, side_h) if left else None,
                 QRect(g.right() - d + 1, side_top, d, side_h) if right else None]
        edges = (top, bottom, left, right)
        soft = self.motion == "soft"
        key = (g.x(), g.y(), g.width(), g.height(), self.edges, st.depth, st.bright)
        if soft and key not in self._masks:
            while len(self._masks) >= 6:   # a slider dragged makes one set per value: the oldest go
                self._masks.pop(next(iter(self._masks)))
            self._masks[key] = [[mask(g, r, _strength(k), edges, st.depth, st.bright) for k in range(_LEVELS)]
                                if r is not None else [] for r in rects]
        for i, (s, r) in enumerate(zip(self._strips, rects)):
            s.on = r is not None
            if r is not None:
                s.setGeometry(r)
            else:
                s.hide()
            s.masks = self._masks[key][i] if soft else []
            s.geo = geometry(g, r, edges) if r is not None and not soft else None
            s.turn_at = angles(g, r) if r is not None else None

    def hide(self):
        if not self._on:
            return
        self._on = False
        for s, fade in zip(self._strips, self._fades):
            fade.stop()
            fade.setStartValue(s.windowOpacity())
            fade.setEndValue(0.0)
            fade.start()
        QTimer.singleShot(260, lambda: None if self._on else self._timer.stop())

    def hide_now(self):
        """Hidden at once (before a terminal edit: a fading window over the point UI Automation reads froze it)."""
        self._on = False
        self._timer.stop()
        for s, fade in zip(self._strips, self._fades):
            fade.stop()
            s.hide()

    def _tick(self):
        # the pointer on another screen takes the glow there (the user's request, 2026-10-15; the indicator did it
        # until it was removed 2026-10-16)
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is not None and screen.geometry() != self._screen:
            self.move(screen)
        target = min(1.0, max(0.0, self._level_source()) * 1.6)
        # fast up, slow down, like a level meter
        k = 0.5 if target > self._level else 0.08   # per frame at _FPS: the same speed at any frame rate
        self._level += (target - self._level) * (1 - (1 - k) ** (_FPS / self.fps))
        self._ticks += 1
        if self._level < 0.05 and self._ticks % 2 and self.motion == "soft":   # quiet: half the frames
            return
        if self._render():
            for s in self._strips:
                s.update()

    def _render(self) -> bool:
        """False when the frame would look as the last one did (a still style, the same level)."""
        t = time.monotonic() - self._t0
        k, angle = frame(self._style, t, self._level)
        self._lap += max(0.0, t - self._lap_t) * comet_speed(self._style, self._level)
        self._lap_t = t
        if self.motion == "soft":
            if (k, angle) == self._shown:
                return False
            self._shown = (k, angle)
        for s in self._strips:
            if not s.on:
                continue
            m = s.masks[k] if self.motion == "soft" else motion_mask(s.geo, self.motion, self._style, t,
                                                                      self._level, self._lap)
            s.image = render(self._lut, s.turn_at, m, angle)
        return True
