"""A question asked inside the settings window (2026-10-21, the user's pick over Windows' message box): the window
dims and a card in its style rises in the middle. Esc or a click on the dimmed part is 取消."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .kit import T, button, calm
from .wizard import TextLink

CARD_W = 440


class _Card(QWidget):
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(T("tile"))
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)


class Sheet(QWidget):
    """title, body, an optional link (`link_text`, `linked`) and 取消 / the action (`accepted`)."""
    accepted = Signal()
    linked = Signal()

    def __init__(self, win, title: str, body: str, action: str, link_text: str = ""):
        super().__init__(win)
        self.setGeometry(win.rect())
        self.setFocusPolicy(Qt.StrongFocus)
        self.card = _Card(self)
        v = QVBoxLayout(self.card)
        v.setContentsMargins(28, 26, 28, 22)
        v.setSpacing(0)
        t = QLabel(title)
        t.setFont(theme.font(18, 700))
        v.addWidget(t)
        v.addSpacing(10)
        b = QLabel(body)
        b.setFont(theme.font(13.5))
        b.setWordWrap(True)
        b.setProperty("muted", True)
        v.addWidget(b)
        v.addSpacing(18)
        row = QHBoxLayout()
        row.setSpacing(8)
        if link_text:
            link = TextLink(link_text)
            link.clicked.connect(self.linked.emit)
            row.addWidget(link)
        row.addStretch(1)
        cancel = button("取消", self.close_sheet)
        ok = button(action, self._accept, pri=True)
        for w in (cancel, ok):
            w.setMinimumHeight(36)
            row.addWidget(w)
        v.addLayout(row)
        self.card.setFixedWidth(CARD_W)
        self.card.adjustSize()
        self.card.move((self.width() - CARD_W) // 2, (self.height() - self.card.height()) // 2 - 10)
        self._fx = QGraphicsOpacityEffect(self, opacity=0.0)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self, duration=160, easingCurve=QEasingCurve.OutCubic)
        cancel.setFocus()

    def open(self):
        self.show()
        self.raise_()
        self.setFocus()
        if calm():
            self._fx.setOpacity(1.0)
            return
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def close_sheet(self):
        self.hide()
        self.deleteLater()

    def _accept(self):
        self.close_sheet()
        self.accepted.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_sheet()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if not self.card.geometry().contains(e.position().toPoint()):
            self.close_sheet()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 115))
