r"""Feasibility spike for showing the draft as if selected (2026-10-16, the user's request): a click-through overlay
drawn at the UI Automation rectangles of text, never touching the document.

  .venv\Scripts\python.exe dev\highlight_spike.py <out dir> chrome|term

chrome: opens dev/highlight_spike.html in a new Chrome window (a textarea and a contenteditable box), finds a phrase in
each, and also the 8 characters before a caret placed with UIA (TextRange.Select, no keys), draws the highlight for 2s,
saves screenshots and timings, and closes the window. term: the characters before Windows Terminal's cursor (the
focused window), where wide characters count as two cells.
"""
import ctypes
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from artvoiceinput import selection  # noqa: E402

OUT = Path(sys.argv[1])
MODE = sys.argv[2] if len(sys.argv) > 2 else "chrome"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PAGE = Path(__file__).resolve().parent / "highlight_spike.html"


def to_logical(x, y):
    for s in QGuiApplication.screens():
        g, r = s.geometry(), s.devicePixelRatio()
        if g.x() <= x < g.x() + g.width() * r and g.y() <= y < g.y() + g.height() * r:
            return s, QPoint(g.x() + int((x - g.x()) / r), g.y() + int((y - g.y()) / r)), r
    return QGuiApplication.primaryScreen(), QPoint(x, y), 1.0


class Mark(QWidget):
    """One highlighted rectangle: click-through, on top, never activated."""

    def __init__(self, rect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        x, y, w, h = rect
        _, p, r = to_logical(int(x), int(y))
        self.setGeometry(QRect(p.x(), p.y(), max(1, round(w / r)), max(1, round(h / r))))

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(51, 144, 255, 90))
        p.end()


def rects_of(rng):
    flat = list(rng.GetBoundingRectangles() or [])
    return [tuple(flat[i:i + 4]) for i in range(0, len(flat), 4)]


def show_and_shoot(app, rects, name):
    marks = [Mark(r) for r in rects]
    for m in marks:
        m.show()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.03)
    if rects:
        x0 = min(r[0] for r in rects) - 40
        y0 = min(r[1] for r in rects) - 20
        x1 = max(r[0] + r[2] for r in rects) + 40
        y1 = max(r[1] + r[3] for r in rects) + 20
        screen, p, ratio = to_logical(int(x0), int(y0))
        g = screen.geometry()
        screen.grabWindow(0, p.x() - g.x(), p.y() - g.y(), int((x1 - x0) / ratio), int((y1 - y0) / ratio)).save(
            str(OUT / f"{name}.png"))
    time.sleep(1.5)
    for m in marks:
        m.close()
    app.processEvents()


def timed(fn, n=20):
    t0 = time.perf_counter()
    for _ in range(n):
        out = fn()
    return out, (time.perf_counter() - t0) / n * 1000


def find_window(title, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        hwnd = ctypes.windll.user32.FindWindowW("Chrome_WidgetWin_1", title + " - Google Chrome")
        if hwnd:
            return hwnd
        time.sleep(0.2)
    return 0


def chrome(app):
    uia, U = selection._uia()
    subprocess.Popen([CHROME, "--new-window", PAGE.as_uri()])
    hwnd = find_window("HL spike")
    if not hwnd:
        print("Chrome window not found")
        return
    time.sleep(1.5)
    root = uia.ElementFromHandle(hwnd)
    report = []
    try:
        for name, ctype in (("textarea", U.UIA_EditControlTypeId), ("editable", U.UIA_EditControlTypeId)):
            cond = uia.CreateAndCondition(uia.CreatePropertyCondition(U.UIA_ControlTypePropertyId, ctype),
                                          uia.CreatePropertyCondition(U.UIA_AutomationIdPropertyId, name))
            el = root.FindFirst(U.TreeScope_Descendants, cond)
            if not el:
                report.append(f"{name}: not found")
                continue
            tp = el.GetCurrentPattern(U.UIA_TextPatternId).QueryInterface(U.IUIAutomationTextPattern)
            rng = tp.DocumentRange.FindText("草稿在這裡 draft text", 0, 0)
            if not rng:
                report.append(f"{name}: phrase not found")
                continue
            rects, ms = timed(lambda: rects_of(rng))
            report.append(f"{name}: phrase {rng.GetText(-1)!r} rects {[tuple(round(v) for v in r) for r in rects]} "
                          f"{ms:.2f} ms")
            show_and_shoot(app, rects, f"chrome_{name}_phrase")
            # a caret after the phrase, put there by UIA, and the 8 characters before it (a draft)
            caret = rng.Clone()
            caret.MoveEndpointByRange(U.TextPatternRangeEndpoint_Start, caret, U.TextPatternRangeEndpoint_End)
            caret.Select()
            time.sleep(0.2)

            def draft():
                sel = tp.GetSelection()
                r = sel.GetElement(0).Clone()
                r.MoveEndpointByUnit(U.TextPatternRangeEndpoint_Start, U.TextUnit_Character, -8)
                return r.GetText(-1), rects_of(r)
            (text, rects), ms = timed(draft)
            report.append(f"{name}: 8 before the caret {text!r} rects {[tuple(round(v) for v in r) for r in rects]} "
                          f"{ms:.2f} ms")
            show_and_shoot(app, rects, f"chrome_{name}_draft")
    finally:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
    print("\n".join(report))


def term(app):
    uia, U = selection._uia()
    el = uia.GetFocusedElement()
    tp = el.GetCurrentPattern(U.UIA_TextPatternId).QueryInterface(U.IUIAutomationTextPattern)

    def draft():
        r = tp.GetSelection().GetElement(0).Clone()
        r.MoveEndpointByUnit(U.TextPatternRangeEndpoint_Start, U.TextUnit_Character, -12)
        return r.GetText(-1), rects_of(r)
    (text, rects), ms = timed(draft)
    print(f"term: {text!r} rects {[tuple(round(v) for v in r) for r in rects]} {ms:.2f} ms")
    show_and_shoot(app, rects, "term_draft")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    qapp = QApplication([])
    (chrome if MODE == "chrome" else term)(qapp)
