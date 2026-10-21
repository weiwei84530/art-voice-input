"""Colors and fonts of the settings window and the 選字 menu (the 2026-10 redesign, style C): an orange brand on silver
white (light) or dark gray (dark). config.theme picks light, dark or the Windows setting (system)."""
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication

ACCENT = "#FF453A"
FONT = "Noto Sans TC"            # Windows 11's optional font; Microsoft JhengHei UI stands in
FONT_FALLBACK = "Microsoft JhengHei UI"
NUM_FONT = "Bahnschrift SemiCondensed"   # version number, counts, keys (Barlow Semi Condensed in the mockups)
# for a style-sheet-sized widget (its font-size resets the family): numbers in NUM_FONT, the rest falls to FONT
NUM_FAMILY = f"font-family: '{NUM_FONT}', '{FONT}', '{FONT_FALLBACK}';"

LIGHT = {"bg": "#F1F2F4", "tile": "#FFFFFF", "tile2": "#F6F7F8", "ink": "#15171A", "muted": "#5E646C",
         "line": "#E0E2E6", "acc": ACCENT, "acct": "#C5261C", "accbg": "rgba(255,69,58,23)",
         "shade": "rgba(21,23,26,31)", "wall0": "#D3D9E1", "wall1": "#F3F5F7", "wall2": "#DEE3E9",
         "ins": "#1D7F37", "dark": False}
DARK = {"bg": "#1A1C1F", "tile": "#24272B", "tile2": "#2C2F34", "ink": "#EEF0F2", "muted": "#A1A7AF",
        "line": "#33373C", "acc": ACCENT, "acct": "#FF6B61", "accbg": "rgba(255,69,58,33)",
        "shade": "rgba(0,0,0,102)", "wall0": "#101215", "wall1": "#23262B", "wall2": "#17191C",
        "ins": "#62D683", "dark": True}
MODES = [("light", "亮色"), ("dark", "暗色"), ("system", "跟隨系統")]
_DOWN = (Path(__file__).parent / "down.svg").as_posix()   # the drop-down's arrow
_CHECK = (Path(__file__).parent / "check.svg").as_posix()  # the check box's tick


def system_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


class Theme(QObject):
    """The tokens in use; `changed` when the mode or, under system, Windows' setting changes."""
    changed = Signal()

    def __init__(self, mode: str = "system"):
        super().__init__()
        self.mode = mode
        self.t = DARK if self._dark() else LIGHT
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda _: self._update())

    def _dark(self) -> bool:
        return self.mode == "dark" or (self.mode == "system" and system_dark())

    def set_mode(self, mode: str):
        self.mode = mode
        self._update()

    def _update(self):
        t = DARK if self._dark() else LIGHT
        if t is not self.t:
            self.t = t
            self.changed.emit()

    def __getitem__(self, key):
        return self.t[key]

    def color(self, key: str, alpha: float | None = None) -> QColor:
        c = qcolor(self.t[key])
        if alpha is not None:
            c.setAlphaF(alpha)
        return c


def qcolor(s: str) -> QColor:
    """#RRGGBB or rgba(r,g,b,a 0-255)."""
    if s.startswith("rgba("):
        r, g, b, a = (int(x) for x in s[5:-1].split(","))
        return QColor(r, g, b, a)
    return QColor(s)


def font(px: float, weight: int = 400, num: bool = False) -> QFont:
    f = QFont()
    f.setFamilies([NUM_FONT, FONT, FONT_FALLBACK] if num else [FONT, FONT_FALLBACK])
    f.setPixelSize(round(px))
    f.setWeight(QFont.Weight(weight))
    return f


def qss(t: dict) -> str:
    """The window's style sheet: standard controls in the theme; custom painted ones read the tokens."""
    return f"""
* {{ color: {t['ink']}; }}
QWidget#page, QWidget#scrollBody, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QLabel {{ background: transparent; }}
QLabel[muted="true"] {{ color: {t['muted']}; }}
QLabel[ok="true"] {{ color: {t['ins']}; }}
QLabel[dim="true"] {{ color: {t['muted']}; font-size: 12px; }}
QLabel[h2="true"] {{ font-size: 24px; font-weight: 700; }}
QLabel[h3="true"] {{ font-size: 15px; font-weight: 700; }}
QLabel[sh="true"] {{ font-size: 13px; font-weight: 700; color: {t['muted']}; }}
QLabel[b14="true"] {{ font-size: 14px; font-weight: 500; }}
QLabel[warn="true"] {{ color: {t['acct']}; font-size: 12.5px; font-weight: 500; }}
QLabel[badge="true"] {{ background: {t['accbg']}; color: {t['acct']}; font-size: 11px; font-weight: 500;
                     border-radius: 4px; padding: 1px 6px; }}
QFrame#card {{ background: {t['tile']}; border: 1px solid {t['line']}; border-radius: 6px; }}
QFrame#card QLabel, QFrame#card QFrame {{ border: none; }}
QFrame#card QFrame#branch {{ border: none; border-left: 2px solid {t['line']}; background: transparent; }}
QFrame#sep {{ background: {t['line']}; border: none; max-height: 1px; min-height: 1px; }}
QPushButton {{ background: {t['tile2']}; border: 1px solid {t['line']}; border-radius: 5px; padding: 0 14px;
              min-height: 30px; font-size: 13px; }}
QPushButton:hover {{ border-color: {t['acc']}; }}
QPushButton:disabled {{ color: {t['muted']}; border-color: {t['line']}; }}
QPushButton[pri="true"] {{ background: {t['acc']}; color: #FFFFFF; border: none; }}
QPushButton[pri="true"]:hover {{ background: #F0392E; }}
QPushButton[wiz="true"] {{ font-size: 15px; font-weight: 500; border-radius: 7px; min-height: 40px; max-height: 40px; }}
QPushButton[danger="true"] {{ color: {t['acct']}; }}
QPushButton[testing="true"] {{ background: {t['accbg']}; color: {t['acct']}; border: 1px solid {t['acc']}; }}
QPushButton[link="true"] {{ background: transparent; border: none; color: {t['acct']}; padding: 0;
              text-decoration: underline; }}
QPushButton[chip="true"] {{ min-height: 28px; max-height: 28px; border-radius: 14px; padding: 0 12px; }}
QPushButton[chip="true"]:checked {{ background: {t['acc']}; color: #FFFFFF; border: 1px solid {t['acc']}; }}
QPushButton[chip="true"][small="true"] {{ min-height: 24px; max-height: 24px; border-radius: 12px; padding: 0 8px;
              font-size: 12.5px; }}
QPushButton[seg="true"] {{ background: transparent; border: none; border-radius: 5px; color: {t['muted']};
              min-height: 30px; padding: 0 12px; }}
QPushButton[seg="true"]:checked {{ color: {t['ink']}; font-weight: 700; }}
QPushButton[seg="true"][big="true"] {{ min-height: 36px; padding: 0 16px; font-size: 13.5px; }}
QFrame#segbox {{ background: {t['tile2']}; border: 1px solid {t['line']}; border-radius: 7px; }}
QPushButton[ib="true"] {{ background: transparent; border: none; min-width: 28px; max-width: 28px; min-height: 28px;
              max-height: 28px; padding: 0; color: {t['muted']}; font-size: 14px; }}
QPushButton[ib="true"]:hover {{ background: {t['tile2']}; color: {t['acct']}; }}
QLineEdit {{ background: {t['tile2']}; border: 1px solid {t['line']}; border-radius: 5px; padding: 0 10px;
            min-height: 30px; font-size: 13.5px; selection-background-color: {t['acc']}; }}
QLineEdit:focus {{ border: 1px solid {t['acc']}; }}
QLineEdit[keys="true"]:focus {{ background: {t['accbg']}; }}
QComboBox {{ background: {t['tile2']}; border: 1px solid {t['line']}; border-radius: 5px; padding: 0 10px;
            min-height: 32px; font-size: 13.5px; }}
QComboBox:hover {{ border-color: {t['acc']}; }}
QComboBox[slim="true"], QLineEdit[slim="true"] {{ min-height: 28px; max-height: 28px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({_DOWN}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t['tile']}; border: 1px solid {t['line']}; outline: none;
            selection-background-color: {t['accbg']}; selection-color: {t['ink']}; padding: 4px; }}
QCheckBox {{ font-size: 14px; font-weight: 500; spacing: 8px; background: transparent; }}
QCheckBox:disabled {{ color: {t['muted']}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1.5px solid {t['muted']};
            background: transparent; }}
QCheckBox::indicator:checked {{ background: {t['acc']}; border-color: {t['acc']}; image: url({_CHECK}); }}
QCheckBox::indicator:disabled {{ border-color: {t['line']}; }}
QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {t['line']}; }}
QSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px; background: {t['acc']}; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: #FFFFFF;
            border: 1px solid {t['line']}; }}
QSlider::handle:horizontal:hover {{ border-color: {t['acc']}; }}
QSlider:disabled {{ }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['line']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QToolTip {{ background: {t['ink']}; color: {t['bg']}; border: none; padding: 7px 10px; font-size: 12px; }}
QMenu {{ background: {t['tile']}; border: 1px solid {t['line']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t['accbg']}; }}
"""
