"""Top-level overlays: blocked-app warning and full-screen break reminder."""
from typing import List

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from uzkit.i18n import tr

from .ui import TIMER_FONT, accent, phase_color


class WarningOverlay(QWidget):
    """Small always-on-top panel near the top of the primary screen."""

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 18)
        lay.setSpacing(4)
        self.title = QLabel(tr("warn_title"))
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.count = QLabel()
        base = "background: transparent; color: #f2f4f3;"
        self.title.setStyleSheet(base + "font-size: 12pt; font-weight: 600;")
        self.body.setStyleSheet(base + "font-size: 10.5pt; color: #c9d3ce;")
        self.count.setStyleSheet(base + f'font-family: "{TIMER_FONT}"; font-size: 22pt; font-weight: 300;')
        lay.addWidget(self.title)
        lay.addWidget(self.body)
        lay.addWidget(self.count)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(24, 28, 26, 238))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        p.setBrush(QColor(accent()))
        p.drawRoundedRect(QRectF(0, 0, 5, self.height()).adjusted(1, 8, 1, -8), 2, 2)
        p.end()

    def show_items(self, items: List[tuple], seconds_left: int):
        """items: [(app name, action text)]"""
        lines = [f"{name}: {act}" for name, act in items]
        self.body.setText("\n".join(lines))
        self.count.setText(tr("warn_in", s=max(0, seconds_left)))
        self.adjustSize()
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.top() + 28)
        if not self.isVisible():
            self.show()
        self.raise_()


class _BreakScreen(QWidget):
    skip = Signal()
    hide_all = Signal()

    def __init__(self, geometry, primary: bool):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(geometry)
        self.primary = primary
        self.phase = "short"
        self.time_text = ""
        self.message = ""
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        if primary:
            row = QHBoxLayout()
            row.addStretch(1)
            self.btn_skip = QPushButton(tr("break_skip"))
            self.btn_hide = QPushButton(tr("break_hide"))
            for b in (self.btn_skip, self.btn_hide):
                b.setCursor(Qt.PointingHandCursor)
                b.setMinimumWidth(150)
                b.setStyleSheet("QPushButton { color: #eef2ef; background: rgba(255,255,255,0.10); "
                                "border: 1px solid rgba(255,255,255,0.28); border-radius: 18px; padding: 8px 18px; }"
                                "QPushButton:hover { background: rgba(255,255,255,0.18); }")
                row.addWidget(b)
            row.addStretch(1)
            lay.addLayout(row)
            lay.addSpacing(int(geometry.height() * 0.12))
            self.btn_skip.clicked.connect(self.skip.emit)
            self.btn_hide.clicked.connect(self.hide_all.emit)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide_all.emit()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(14, 18, 17, 222))
        if not self.primary:
            p.end()
            return
        h = self.height()
        r = self.rect()
        col = phase_color(self.phase)
        f = QFont(self.font())
        f.setPixelSize(max(14, int(h * 0.024)))
        f.setWeight(QFont.DemiBold)
        f.setLetterSpacing(QFont.PercentageSpacing, 112)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(0, h * 0.25, r.width(), h * 0.05), Qt.AlignCenter, tr(f"phase_{self.phase}").upper())
        ft = QFont(TIMER_FONT)
        ft.setWeight(QFont.Light)
        ft.setPixelSize(max(48, int(h * 0.16)))
        p.setFont(ft)
        p.setPen(QColor("#f2f4f3"))
        p.drawText(QRectF(0, h * 0.31, r.width(), h * 0.2), Qt.AlignCenter, self.time_text)
        fm = QFont(self.font())
        fm.setPixelSize(max(14, int(h * 0.022)))
        p.setFont(fm)
        p.setPen(QColor(220, 228, 224))
        p.drawText(QRectF(r.width() * 0.2, h * 0.53, r.width() * 0.6, h * 0.12),
                   Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, self.message)
        hint = QFont(self.font())
        hint.setPixelSize(max(11, int(h * 0.014)))
        p.setFont(hint)
        p.setPen(QColor(160, 172, 166))
        p.drawText(QRectF(0, h - 48, r.width(), 24), Qt.AlignCenter, tr("break_esc"))
        p.end()


class BreakOverlay:
    """One translucent window per screen; the primary one has text and buttons."""

    MESSAGES = ("break_msg_1", "break_msg_2", "break_msg_3", "break_msg_4")

    def __init__(self, on_skip):
        self.on_skip = on_skip
        self.screens: List[_BreakScreen] = []
        self._msg_i = 0

    @property
    def visible(self) -> bool:
        return bool(self.screens)

    def show(self, phase: str):
        self.hide()
        prim = QGuiApplication.primaryScreen()
        msg = tr(self.MESSAGES[self._msg_i % len(self.MESSAGES)])
        self._msg_i += 1
        for scr in QGuiApplication.screens():
            w = _BreakScreen(scr.geometry(), scr is prim)
            w.phase = phase
            w.message = msg
            w.skip.connect(self._skip)
            w.hide_all.connect(self.hide)
            w.show()
            self.screens.append(w)
        for w in self.screens:
            if w.primary:
                w.activateWindow()
                w.raise_()
                w.setFocus()

    def update(self, time_text: str):
        for w in self.screens:
            if w.time_text != time_text:
                w.time_text = time_text
                w.update()

    def _skip(self):
        self.hide()
        self.on_skip()

    def hide(self):
        for w in self.screens:
            try:
                w.close()
                w.deleteLater()
            except RuntimeError:
                pass
        self.screens = []
