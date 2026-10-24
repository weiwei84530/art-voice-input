"""The settings window (the 2026-10 redesign, the user's picks): a frameless 960x640 window. Home: the orange brand
block on the left (logo, 阿特語音輸入法, version) and six tiles, each with its icon bled large into the corner. A tile
opens its page: the block shrinks to a 56px strip that leads back home, the tile's icon flies to the page title
(transition 1, Fly), the page fades in."""
import ctypes
import time

from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen, QTransform
from PySide6.QtWidgets import (QAbstractButton, QApplication, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
                               QLabel, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .. import __version__, paths
from . import theme
from .kit import T, Hub, Tip, TipRouter, calm, dark_frame, draw_icon, logo_renderer

W, H = 960, 640
ORG_HOME, ORG_PAGE = 380, 56
VERSION_PX, VERSION_WEIGHT = 44, 500   # the version on the brand block (was 56 bold)
TILE_X, TILE_Y, TILE_W, TILE_H, TILE_GAP = 404, 40, 532, 86, 8
FLY_END = (84, 18, 40)          # the page title's icon: x, y, size
HEADER = 76


def bezier(x1, y1, x2, y2):
    """CSS cubic-bezier(x1, y1, x2, y2) as a function of 0..1."""
    def f(x):
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        lo, hi = 0.0, 1.0
        for _ in range(30):
            t = (lo + hi) / 2
            bx = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t * t * x2 + t ** 3
            if bx < x:
                lo = t
            else:
                hi = t
        t = (lo + hi) / 2
        return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t * t * y2 + t ** 3
    return f


SWIFT = bezier(.7, 0, .25, 1)      # the block and the flying icon
SOFT = bezier(.2, 0, .2, 1)        # the page rising, the bled icons
LINEAR = lambda x: min(max(x, 0.0), 1.0)   # noqa: E731


def seg(ms: float, start: float, dur: float, ease=LINEAR) -> float:
    return ease(min(max((ms - start) / dur, 0.0), 1.0))


def lerp(a, b, k):
    return a + (b - a) * k


class Brand(QWidget):
    """The orange block: a large faint logo bleeding off the bottom right, the status, the logo, the name and the
    version. `fade` 0..1 hides the text and logo (sliding left) as the block shrinks. The logo and the names
    carry the same solid shadow (three dark red silhouettes, a little larger each, shifted down: from design H5, the
    user's pick 2026-10-20; the version, the lines below it and the status line have none); the status dot pulses (a
    ring of light spreading out) while ready."""
    PULSE_S = 1.8                  # one ring
    SHADOW = QColor("#780A00")

    def __init__(self, parent):
        super().__init__(parent)
        self.fade = 0.0
        self.status = "就緒"
        self._logo = logo_renderer()
        self._logo_shadow = logo_renderer("#780A00")
        self._shadows = {}         # (text, font, rect, shift, grow) -> the three silhouettes, made once
        self._pulse = QTimer(self, interval=33)
        self._pulse.timeout.connect(self._tick)
        self._t0 = time.monotonic()
        # the dot at the middle of the status text's ink (Chinese sits below the line box's middle: 28)
        fm = QFontMetricsF(theme.font(12.5, 500))
        self._dot_y = 28 + (fm.ascent() - fm.descent()) / 2 + fm.tightBoundingRect("就緒").center().y()

    def showEvent(self, e):
        self._pulse.start()

    def hideEvent(self, e):
        self._pulse.stop()

    def _tick(self):
        if self.fade < 1 and self.status == "就緒" and self.window().isVisible() and not calm():
            self.update(QRect(34 + 3 - 14, round(self._dot_y) - 14, 28, 28))   # only the dot

    def _text(self, p, rect: QRectF, align, text: str, shift: float = 0, grow: float = 0):
        """Text, over its solid shadow when shift is given."""
        if shift:
            f = p.font()
            key = (text, f.key(), rect.getRect(), int(align), shift, grow)
            layers = self._shadows.get(key)
            if layers is None:
                fm = QFontMetricsF(f)
                if align & Qt.AlignBottom:
                    base = rect.bottom() - fm.descent()
                else:
                    base = rect.center().y() + (fm.ascent() - fm.descent()) / 2
                path = QPainterPath()
                path.addText(QPointF(rect.x(), base), f, text)
                layers = []
                for d in (14, 12, 10):
                    st = QPainterPathStroker()
                    st.setWidth(2 * grow * d / 14)
                    st.setJoinStyle(Qt.RoundJoin)
                    layers.append(st.createStroke(path).united(path).translated(0, shift))
                self._shadows[key] = layers
            p.save()
            a = p.opacity()
            p.setOpacity(a * 0.06)
            for layer in layers:
                p.fillPath(layer, self.SHADOW)
            p.restore()
        p.drawText(rect, align, text)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.ACCENT))
        # the bled logo stays where it is while the block shrinks (cut by the block's edge)
        p.setOpacity(0.14)
        self._logo.render(p, QRectF(ORG_HOME + 210 - 520, H + 150 - 520, 520, 520))
        a = 1 - self.fade
        if a <= 0:
            return
        p.setOpacity(a)
        p.translate(-40 * SWIFT(self.fade), 0)
        x = 34
        white = QColor("#FFFFFF")
        dot = QPointF(x + 3.5, self._dot_y)
        p.setPen(Qt.NoPen)
        if self.status == "就緒" and not calm():
            k = ((time.monotonic() - self._t0) / self.PULSE_S) % 1.0
            p.setBrush(QColor(255, 255, 255, round(110 * (1 - k) ** 1.6)))
            r = 3.5 + 7.5 * SOFT(k)
            p.drawEllipse(dot, r, r)
        else:
            p.setBrush(QColor(255, 255, 255, 77))
            p.drawEllipse(dot, 6.5, 6.5)
        p.setBrush(white)
        p.drawEllipse(dot, 3.5, 3.5)
        p.setPen(white)
        p.setFont(theme.font(12.5, 500))
        text = "就緒，隨時可以開始說話" if self.status == "就緒" else self.status
        p.drawText(QRectF(x + 15, 18, ORG_HOME - x - 30, 20), Qt.AlignVCenter | Qt.AlignLeft, text)
        # bottom-up: footnote, version, English name, name, logo
        p.setFont(theme.font(13))
        p.setOpacity(a * 0.92)
        self._text(p, QRectF(x, 572, 330, 20), Qt.AlignLeft | Qt.AlignVCenter, "語音在這台電腦上辨識，不會上傳")
        p.setOpacity(a)
        # the version lighter and smaller than the name (2026-10-20, the user's request: only the name stands out);
        # 版本's ink ends where the digits' does
        p.setFont(theme.font(VERSION_PX, VERSION_WEIGHT, num=True))
        fm = QFontMetricsF(p.font())
        vw = fm.horizontalAdvance(__version__)
        bottom = 550                                     # the digits' ink ends here
        base = bottom - fm.tightBoundingRect(__version__).bottom()
        p.setOpacity(a * 0.9)   # as 版本 (2026-10-21, the user's request)
        p.drawText(QPointF(x, base), __version__)
        p.setFont(theme.font(13))
        fm = QFontMetricsF(p.font())
        p.drawText(QPointF(x + vw + 8, bottom - fm.tightBoundingRect("版本").bottom()), "版本")
        p.setOpacity(a)
        if not paths.FROZEN:   # a development copy says so (2026-10-24, the user's request): a white pill after 版本
            p.setFont(theme.font(13, 700))   # 12.5 at 600 read blurry (the user's report)
            pw = QFontMetricsF(p.font()).horizontalAdvance("開發版") + 20
            pill = QRectF(x + vw + 8 + fm.horizontalAdvance("版本") + 12, bottom - 21, pw, 24)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#FFFFFF"))
            p.drawRoundedRect(pill, 12, 12)
            p.setPen(QColor(theme.ACCENT))   # the brand block's own red (the user's request)
            p.drawText(pill, Qt.AlignCenter, "開發版")
            p.setPen(white)
        p.setFont(theme.font(22, 600, num=True))
        self._text(p, QRectF(x, 438, 330, 30), Qt.AlignLeft | Qt.AlignVCenter, "Art VoiceInput", 3, 1.5)
        p.setFont(theme.font(34, 700))
        f = p.font()
        f.setLetterSpacing(f.SpacingType.PercentageSpacing, 104)
        p.setFont(f)
        self._text(p, QRectF(x, 394, 340, 44), Qt.AlignLeft | Qt.AlignVCenter, "阿特語音輸入法", 4, 2)
        # the logo with its solid shadow
        for d in (14, 12, 10):
            p.setOpacity(a * 0.06)
            # 8px down (10 until 2026-10-21: it read too thick, the user's request)
            self._logo_shadow.render(p, QRectF(x - 14 - d / 4, 254 + 8 - d / 4, 132 + d / 2, 132 + d / 2))
        p.setOpacity(a)
        self._logo.render(p, QRectF(x - 14, 254, 132, 132))


class Tile(QAbstractButton):
    """A home tile: the icon in an orange square, the name and a line about the page's settings, and the icon bled
    large into the bottom right (tilted 5°); the pointer over it lifts the big icon up and right, turning it."""

    def __init__(self, parent, key: str, name: str):
        super().__init__(parent)
        self.key, self.name, self.desc = key, name, ""
        self.hide_icon = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)   # a click doesn't leave a focused (outlined) tile behind
        self.setFixedSize(TILE_W, TILE_H)
        self.setAccessibleName(name)
        self._over = False         # the outline follows the pointer at once, not the 500ms hover animation
        self._h = 0.0
        self._anim = QVariantAnimation(self, duration=500)
        self._anim.valueChanged.connect(self._hover)

    def _hover(self, v):
        self._h = float(v)
        self.update()

    def _go(self, end: float):
        self._anim.stop()
        if calm():
            self._hover(end)
            return
        self._anim.setStartValue(self._h)
        self._anim.setEndValue(end)
        self._anim.start()

    def enterEvent(self, e):
        self._over = True
        self._go(1.0)

    def leaveEvent(self, e):
        self._over = False
        self._go(0.0)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = SOFT(self._h)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.fillPath(path, T("tile"))
        p.save()
        p.setClipPath(path)
        # the bled icon: 136px, right 28px, 58px below the bottom edge
        size = 136
        cx, cy = self.width() - 28 - size / 2, self.height() + 58 - size / 2
        tr = QTransform()
        tr.translate(cx + 10 * h, cy - 20 * h)
        tr.rotate(5 + 12 * h)
        tr.scale(1 + 0.16 * h, 1 + 0.16 * h)
        p.setTransform(tr, True)
        muted, acc = T("muted"), T("acc")
        c = QColor(round(lerp(muted.red(), acc.red(), h)), round(lerp(muted.green(), acc.green(), h)),
                   round(lerp(muted.blue(), acc.blue(), h)))
        c.setAlphaF(lerp(0.16, 0.30, h))
        draw_icon(p, self.key, QRectF(-size / 2, -size / 2, size, size), c, 1.5)
        p.restore()
        p.setPen(QPen(T("acc") if self._over or self.hasFocus() else T("line"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 6, 6)
        # the small icon
        if not self.hide_icon:
            s = 34 * (1 + 0.08 * h)
            ir = QRectF(22 + 17 - s / 2, self.height() / 2 - s / 2, s, s)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(ir, 6, 6)
            draw_icon(p, self.key, ir.adjusted(s * 0.21, s * 0.21, -s * 0.21, -s * 0.21), QColor("#FFFFFF"))
        p.setPen(T("ink"))
        p.setFont(theme.font(17, 700))
        p.drawText(QRectF(70, 16, self.width() - 110, 26), Qt.AlignLeft | Qt.AlignBottom, self.name)
        p.setPen(T("muted"))
        p.setFont(theme.font(13))
        fm = p.fontMetrics()
        p.drawText(QRectF(70, 45, self.width() - 110, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(self.desc, Qt.ElideRight, self.width() - 110))


class Strip(QAbstractButton):
    """The block shrunk on a page: a click goes home. A white round arrow in the middle, 回首頁 beside it while the
    pointer is there, three lines at the bottom."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("回首頁")
        self.setToolTip("回首頁")   # after a second's rest (kit.TipRouter)
        self.setGeometry(0, 0, ORG_PAGE, H)
        self.opacity = 0.0
        self._h = 0.0              # the pointer over it, eased 0..1
        self._anim = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._hover)

    def _hover(self, v):
        self._h = float(v)
        self.update()

    def _go(self, end: float):
        self._anim.stop()
        if calm():
            self._hover(end)
            return
        self._anim.setStartValue(self._h)
        self._anim.setEndValue(end)
        self._anim.start()

    def enterEvent(self, e):
        self._go(1.0)

    def leaveEvent(self, e):
        self._go(0.0)

    def paintEvent(self, _):
        if self.opacity <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.opacity)
        h = self._h
        if h > 0:
            p.fillRect(self.rect(), QColor(0, 0, 0, round(20 * h)))
        c = QPointF(ORG_PAGE / 2 - 3 * h, H / 2)
        rad = 17 * (1 + 0.06 * h)
        for i, a in enumerate((26, 18, 10)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(120, 10, 0, a))
            p.drawEllipse(c + QPointF(0, 4 + i), rad + 3 - i, rad + 3 - i)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(c, rad, rad)
        draw_icon(p, "back", QRectF(c.x() - 9, c.y() - 9, 18, 18), QColor(theme.ACCENT), 2.4)
        p.setPen(QPen(QColor(255, 255, 255, 140), 2, Qt.SolidLine, Qt.RoundCap))
        for i in range(3):
            y = H - 22 - 2 - i * 6
            p.drawLine(QPointF(ORG_PAGE / 2 - 9, y), QPointF(ORG_PAGE / 2 + 9, y))


class FlyIcon(QWidget):
    """The tile's icon on its way to the page title, and resting there. Its soft orange shadow fades in on the way
    to the title and out on the way back (the tile's icon has none)."""
    SHADOW = 80                # the shadow's alpha at the title

    def __init__(self, parent):
        super().__init__(parent)
        self.key = "mic"
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.fx = QGraphicsDropShadowEffect(self, blurRadius=14, offset=QPointF(0, 4), color=QColor(255, 69, 58, 0))
        self.setGraphicsEffect(self.fx)

    def set_lift(self, k: float):
        """0 at the tile, 1 at the title."""
        self.fx.setColor(QColor(255, 69, 58, round(self.SHADOW * k)))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.width()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(0, 0, s, s), 8 * s / 40, 8 * s / 40)
        m = s * 0.2
        draw_icon(p, self.key, QRectF(m, m, s - 2 * m, s - 2 * m), QColor("#FFFFFF"))


class WinButton(QAbstractButton):
    """Minimize and close, drawn like Windows' own."""

    def __init__(self, parent, kind: str):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(46, 36)
        self.setAccessibleName("關閉" if kind == "x" else "最小化")
        self._over = False

    def enterEvent(self, e):
        self._over = True
        self.update()

    def leaveEvent(self, e):
        self._over = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if self._over:
            p.fillRect(self.rect(), QColor("#C42B1C") if self.kind == "x" else T("tile2"))
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#FFFFFF") if self._over and self.kind == "x" else T("ink"), 1))
        cx, cy = self.width() / 2, self.height() / 2
        if self.kind == "x":
            p.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))
            p.drawLine(QPointF(cx + 5, cy - 5), QPointF(cx - 5, cy + 5))
        else:
            p.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))


class PageFrame(QWidget):
    """A page: its title (beside the flown icon) and its content in a scroll area."""

    def __init__(self, parent, page):
        super().__init__(parent)
        self.page = page
        self.setObjectName("page")
        self.title = QLabel(page.title, self)
        self.title.setFont(theme.font(24, 700))
        self.title.move(82, (HEADER - 34) // 2)
        self.title.resize(500, 34)
        self.sub = QLabel(getattr(page, "subtitle", ""), self)
        self.sub.setProperty("dim", True)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("scrollBody")
        v = QVBoxLayout(holder)
        v.setContentsMargins(28, 0, 28, 24)
        v.addWidget(page)
        self.scroll.setWidget(holder)

    def resizeEvent(self, e):
        self.scroll.setGeometry(0, HEADER, self.width(), self.height() - HEADER)
        tw = self.title.fontMetrics().horizontalAdvance(self.title.text())
        self.title.resize(tw + 4, 34)
        self.sub.setGeometry(82 + tw + 18, (HEADER - 20) // 2 + 2, self.width() - 82 - tw - 130, 20)


class Shell(QWidget):
    """The window: brand, tiles, strip, pages and the transition between them."""
    FORWARD_MS, BACK_MS = 900, 750

    def __init__(self, theme_obj: theme.Theme):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        Hub.current = self.theme = theme_obj
        self.setFixedSize(W, H)
        self.setWindowTitle("阿特語音輸入法 設定")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFont(theme.font(13))
        # a style sheet rule with a font-size gives its widget the application's font (Segoe UI, Chinese from
        # 正黑體, grainy next to Noto Sans TC): the application's font is ours too
        QApplication.setFont(theme.font(13))
        self.setFocusPolicy(Qt.ClickFocus)
        self.pages = {}            # key -> PageFrame
        self.tiles = {}
        self.current = None        # open page key, None at home
        self._dir = 0              # 1 opening a page, -1 going home, 0 still

        self.stack = QStackedWidget(self)
        self.stack.setGeometry(ORG_PAGE, 0, W - ORG_PAGE, H)
        self.stack.hide()
        self.home = QWidget(self)
        self.home.setGeometry(TILE_X, TILE_Y, TILE_W, 6 * TILE_H + 5 * TILE_GAP)
        self.brand = Brand(self)
        self.brand.setGeometry(0, 0, ORG_HOME, H)
        self.strip = Strip(self)
        self.strip.clicked.connect(self.go_home)
        self.strip.hide()
        self.fly = FlyIcon(self)
        self.fly.hide()
        self.min_button = WinButton(self, "min")
        self.min_button.clicked.connect(self.showMinimized)
        self.close_button = WinButton(self, "x")
        self.close_button.clicked.connect(self.close)
        self.close_button.move(W - 46, 0)
        self.min_button.move(W - 92, 0)

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._frame)
        self._anim.finished.connect(self._done)
        self.theme.changed.connect(self._restyle)
        self._restyle()
        self._tips = TipRouter(self)

    # --- building ---
    def add_page(self, key: str, page):
        frame = PageFrame(self.stack, page)
        self.stack.addWidget(frame)
        self.pages[key] = frame
        tile = Tile(self.home, key, page.title)
        tile.move(0, len(self.tiles) * (TILE_H + TILE_GAP))
        tile.clicked.connect(lambda _=False, k=key: self.open_page(k))
        self.tiles[key] = tile

    def _restyle(self):
        self.setStyleSheet(theme.qss(self.theme.t) + f"Shell {{ background: {self.theme['bg']}; }}")
        dark_frame(self, self.theme["dark"])
        for w in self.findChildren(QWidget):
            w.update()

    def showEvent(self, e):
        super().showEvent(e)
        _round_corners(self)

    # --- moving the window: drag any empty place ---
    # The system move starts once the pointer has moved: started on a plain click, it left Qt's hover state stuck
    # (no ⓘ answered until the pointer left the window).
    _press_at = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_at = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        at = self._press_at
        if at is not None and (e.globalPosition().toPoint() - at).manhattanLength() >= QApplication.startDragDistance():
            self._press_at = None
            if self.windowHandle() is not None:
                self.windowHandle().startSystemMove()

    def mouseReleaseEvent(self, e):
        self._press_at = None

    # --- the transition ---
    def open_page(self, key: str):
        if self.current is not None or self._anim.state() == QVariantAnimation.Running:
            return
        self.current = key
        self._park_focus()
        frame = self.pages[key]
        self.stack.setCurrentWidget(frame)
        frame.scroll.verticalScrollBar().setValue(0)
        if hasattr(frame.page, "shown"):
            frame.page.shown()
        tile = self.tiles[key]
        self._from = (TILE_X + 22, TILE_Y + tile.y() + (TILE_H - 34) // 2, 34)
        tile.hide_icon = True
        tile.update()
        self.fly.key = key
        self.fly.update()
        self._run(1)

    def go_home(self):
        if self.current is None or self._anim.state() == QVariantAnimation.Running:
            return
        Tip.hide_text(self.strip)
        self._park_focus()
        tile = self.tiles[self.current]
        self._from = (TILE_X + 22, TILE_Y + tile.y() + (TILE_H - 34) // 2, 34)
        self.current = None
        self._run(-1)

    def _park_focus(self):
        """Focus on the window itself: the clicked tile (or a page's control) being hidden handed the focus on as if
        Tab was pressed, and the next control (詞庫's first switch) showed its keyboard ring."""
        self.setFocus(Qt.OtherFocusReason)

    def show_home_now(self):
        """Home at once (the window opened again), also from the middle of a transition. Not through _frame: the
        opacity effects it sets were deleted by the last transition's end (it raised there and left the window half
        way, the brand block wide over the page, 2026-10-21)."""
        if self.current is None and self._anim.state() != QVariantAnimation.Running:
            return
        self.current = None
        self._anim.stop()
        self._dir = -1
        self.home.show()
        self._done()

    def _run(self, direction: int):
        self._dir = direction
        self._home_fx = QGraphicsOpacityEffect(self.home)
        self.home.setGraphicsEffect(self._home_fx)
        self._page_fx = QGraphicsOpacityEffect(self.stack)
        self.stack.setGraphicsEffect(self._page_fx)
        # the first frame's state before anything shows: an opacity effect starts at 0.7, and the page was painted
        # so before the animation's first tick (a page's first showing is slow; the user saw it flash, 2026-10-21)
        self._frame(0.0)
        self.home.show()
        self.stack.show()
        self.strip.show()
        self.fly.show()
        if calm():   # 節流模式: straight to the end
            self._frame(1.0)
            self._done()
            return
        self._anim.setDuration(self.FORWARD_MS if direction > 0 else self.BACK_MS)
        self._anim.start()

    def _frame(self, v):
        if self._dir > 0:
            ms = float(v) * self.FORWARD_MS
            org = lerp(ORG_HOME, ORG_PAGE, seg(ms, 0, 600, SWIFT))
            brand = seg(ms, 0, 600)
            home_a = 1 - seg(ms, 0, 300)
            home_x = -60 * seg(ms, 0, 500, SWIFT)
            fly = seg(ms, 40, 600, SWIFT)
            page_a = seg(ms, 300, 350)
            page_y = 14 * (1 - seg(ms, 300, 500, SOFT))
            strip_a = seg(ms, 300, 300)
        else:
            ms = float(v) * self.BACK_MS
            org = lerp(ORG_PAGE, ORG_HOME, seg(ms, 0, 600, SWIFT))
            brand = 1 - seg(ms, 150, 450)
            home_a = seg(ms, 250, 350)
            home_x = -60 * (1 - seg(ms, 150, 500, SWIFT))
            fly = 1 - seg(ms, 0, 600, SWIFT)
            page_a = 1 - seg(ms, 0, 250)
            page_y = 14 * seg(ms, 0, 350, SOFT)
            strip_a = 1 - seg(ms, 0, 200)
        self.brand.resize(round(org), H)
        self.brand.fade = brand
        self.brand.update()
        self._home_fx.setOpacity(home_a)
        self.home.move(round(TILE_X + home_x), TILE_Y)
        self._page_fx.setOpacity(page_a)
        self.stack.move(ORG_PAGE, round(page_y))
        self.strip.opacity = strip_a
        self.strip.update()
        x0, y0, s0 = self._from
        x1, y1, s1 = FLY_END
        s = lerp(s0, s1, fly)
        self.fly.setGeometry(round(lerp(x0, x1, fly)), round(lerp(y0, y1, fly)), round(s), round(s))
        self.fly.set_lift(fly)
        self.fly.update()

    def _done(self):
        self.home.setGraphicsEffect(None)
        self.stack.setGraphicsEffect(None)
        if self._dir > 0:
            self.home.hide()
            self.strip.setEnabled(True)
        else:
            self.stack.hide()
            self.strip.hide()
            self.fly.hide()
            for t in self.tiles.values():
                t.hide_icon = False
                t.update()
            self.home.move(TILE_X, TILE_Y)
            self.brand.resize(ORG_HOME, H)
            self.brand.fade = 0.0
            self.brand.update()
        self._dir = 0
        self.min_button.raise_()
        self.close_button.raise_()


def _round_corners(w):
    """Windows 11 rounds the frameless window's corners and gives it the usual shadow."""
    try:
        hwnd = int(w.winId())
        pref = ctypes.c_int(2)   # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except (AttributeError, OSError):
        pass
