"""Custom-painted widgets: timer ring, session dots, bar chart, segmented navigation, line icons."""
import math
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QToolTip, QVBoxLayout, QWidget)

from uzkit import app as appmod
from uzkit.theme import PALETTES

from .timer import FOCUS, LONG, SHORT

TIMER_FONT = "Bahnschrift"
PHASE_COLORS = {FOCUS: None, SHORT: "#4b8fc0", LONG: "#8a72c8"}   # None -> accent


def accent() -> str:
    return appmod.META.get("accent", "#3f8f6b")


def phase_color(phase: str) -> QColor:
    return QColor(PHASE_COLORS.get(phase) or accent())


def is_dark() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().window().color().lightness() < 128


def pal() -> dict:
    mode = "dark" if is_dark() else "light"
    p = dict(PALETTES[mode])
    p.update((appmod.META.get("palette", {}) or {}).get(mode, {}))
    return p


# ---------------------------------------------------------------------- line icons
_ICONS = {
    "play": '<path d="M8 5.5v13l10.5-6.5z" fill="{c}" stroke="{c}" stroke-linejoin="round" stroke-width="1.6"/>',
    "pause": '<path d="M8.5 5.5v13M15.5 5.5v13" stroke="{c}" stroke-width="2.6" stroke-linecap="round"/>',
    "skip": '<path d="M6 5.5v13l9-6.5z" fill="none" stroke="{c}" stroke-width="1.8" stroke-linejoin="round"/>'
            '<path d="M18 5.5v13" stroke="{c}" stroke-width="1.8" stroke-linecap="round"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="none" stroke="{c}" stroke-width="1.8"/>',
    "plus": '<path d="M12 5v14M5 12h14" stroke="{c}" stroke-width="1.8" stroke-linecap="round"/>',
    "minus": '<path d="M5 12h14" stroke="{c}" stroke-width="1.8" stroke-linecap="round"/>',
    "list": '<path d="M9 7h10M9 12h10M9 17h10" stroke="{c}" stroke-width="1.8" stroke-linecap="round"/>'
            '<circle cx="5" cy="7" r="1.2" fill="{c}"/><circle cx="5" cy="12" r="1.2" fill="{c}"/>'
            '<circle cx="5" cy="17" r="1.2" fill="{c}"/>',
    "lock": '<rect x="5.5" y="10.5" width="13" height="9" rx="2" fill="none" stroke="{c}" stroke-width="1.8"/>'
            '<path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" fill="none" stroke="{c}" stroke-width="1.8"/>',
    "sound": '<path d="M5 10v4h3l4 3.5v-11L8 10z" fill="none" stroke="{c}" stroke-width="1.7" '
             'stroke-linejoin="round"/><path d="M15.5 9a4 4 0 0 1 0 6M17.8 6.8a7 7 0 0 1 0 10.4" fill="none" '
             'stroke="{c}" stroke-width="1.7" stroke-linecap="round"/>',
}


def line_icon(name: str, color: str, size: int = 20) -> QIcon:
    from PySide6.QtSvg import QSvgRenderer
    body = _ICONS[name].replace("{c}", color)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'
    r = QSvgRenderer(QByteArray(svg.encode()))
    icon = QIcon()
    for s in (size, size * 2):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p)
        p.end()
        icon.addPixmap(pm)
    return icon


# ---------------------------------------------------------------------- segmented navigation
class Segmented(QFrame):
    """Horizontal page switcher. Exposes count() so it works as uzkit's _nav."""
    changed = Signal(int)

    def __init__(self, titles: Sequence[str], parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: List[QPushButton] = []
        for i, t in enumerate(titles):
            b = QPushButton(t)
            b.setObjectName("SegButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            bf = QFont(b.font())
            bf.setBold(True)
            from PySide6.QtGui import QFontMetrics
            b.setMinimumWidth(QFontMetrics(bf).horizontalAdvance(t) + 44)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        if self.buttons:
            self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.changed.emit)

    def count(self) -> int:
        return len(self.buttons)

    def set_current(self, i: int):
        if 0 <= i < len(self.buttons):
            self.buttons[i].setChecked(True)


# ---------------------------------------------------------------------- timer ring
class TimerRing(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.progress = 0.0
        self.time_text = "25:00"
        self.phase = FOCUS
        self.phase_text = ""
        self.sub_text = ""
        self.running = False

    def set_state(self, progress: float, time_text: str, phase: str, phase_text: str, sub_text: str,
                  running: bool):
        changed = (abs(progress - self.progress) > 1e-4 or time_text != self.time_text or phase != self.phase
                   or phase_text != self.phase_text or sub_text != self.sub_text or running != self.running)
        self.progress, self.time_text, self.phase = progress, time_text, phase
        self.phase_text, self.sub_text, self.running = phase_text, sub_text, running
        if changed:
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        P = pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 16
        side = max(side, 120)
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        stroke = max(8.0, side * 0.045)
        inner = rect.adjusted(stroke, stroke, -stroke, -stroke)
        col = phase_color(self.phase)

        # minute ticks
        c = rect.center()
        r_out = side / 2
        tick_col = QColor(P["muted"])
        tick_col.setAlphaF(0.35)
        for i in range(60):
            a = math.radians(i * 6 - 90)
            long_tick = i % 5 == 0
            r1 = r_out - (side * 0.012)
            r2 = r1 - (side * (0.035 if long_tick else 0.018))
            pen = QPen(tick_col, 1.6 if long_tick else 1.0)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(c.x() + r1 * math.cos(a), c.y() + r1 * math.sin(a)),
                       QPointF(c.x() + r2 * math.cos(a), c.y() + r2 * math.sin(a)))

        ring = inner.adjusted(side * 0.05, side * 0.05, -side * 0.05, -side * 0.05)
        track = QColor(P["border"])
        pen = QPen(track, stroke)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.drawEllipse(ring)
        if self.progress > 0.0005:
            pen = QPen(col, stroke)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            # remaining part shown as the coloured arc, shrinking clockwise
            span = -int((1.0 - self.progress) * 360 * 16)
            p.drawArc(ring, 90 * 16, span)
            # end knob
            a = math.radians(90 - (1.0 - self.progress) * 360)
            rr = ring.width() / 2
            knob = QPointF(c.x() + rr * math.cos(a), c.y() - rr * math.sin(a))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(P["surface"]))
            p.drawEllipse(knob, stroke * 0.32, stroke * 0.32)
        else:
            pen = QPen(col, stroke)
            p.setPen(pen)
            p.drawEllipse(ring)

        # texts
        p.setPen(QColor(P["text"]))
        f = QFont(TIMER_FONT)
        f.setWeight(QFont.Light)
        f.setPixelSize(max(28, int(side * 0.2)))
        p.setFont(f)
        p.drawText(QRectF(rect.left(), c.y() - side * 0.14, rect.width(), side * 0.26), Qt.AlignCenter,
                   self.time_text)
        f2 = QFont(self.font())
        f2.setPixelSize(max(11, int(side * 0.05)))
        f2.setWeight(QFont.DemiBold)
        f2.setLetterSpacing(QFont.PercentageSpacing, 108)
        p.setFont(f2)
        p.setPen(col)
        p.drawText(QRectF(rect.left(), c.y() - side * 0.25, rect.width(), side * 0.1), Qt.AlignCenter,
                   self.phase_text.upper())
        f3 = QFont(self.font())
        f3.setPixelSize(max(11, int(side * 0.046)))
        p.setFont(f3)
        p.setPen(QColor(P["muted"]))
        p.drawText(QRectF(rect.left() + side * 0.15, c.y() + side * 0.13, rect.width() - side * 0.3, side * 0.1),
                   Qt.AlignCenter, self.sub_text)
        p.end()


# ---------------------------------------------------------------------- session dots
class SessionDots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.total = 4
        self.done = 0
        self.setFixedHeight(18)
        self.setMinimumWidth(80)

    def set_value(self, done: int, total: int):
        self.done, self.total = done, max(1, total)
        self.update()

    def paintEvent(self, _):
        P = pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d, gap = 10, 10
        w = self.total * d + (self.total - 1) * gap
        x = (self.width() - w) / 2
        y = (self.height() - d) / 2
        for i in range(self.total):
            r = QRectF(x + i * (d + gap), y, d, d)
            if i < self.done:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(accent()))
            else:
                p.setPen(QPen(QColor(P["border"]), 1.6))
                p.setBrush(Qt.NoBrush)
            p.drawEllipse(r)
        p.end()


# ---------------------------------------------------------------------- bar chart
class BarChart(QWidget):
    """Daily focus minutes. values = [(label, minutes, tooltip)]."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values: List[Tuple[str, float, str]] = []
        self.goal = 0.0
        self.highlight_last = True
        self.empty_text = ""
        self.unit = ""
        self.setMinimumHeight(130)
        self.setMouseTracking(True)
        self._bars: List[Tuple[QRectF, str]] = []

    def set_data(self, values, goal: float, empty_text: str = ""):
        self.values, self.goal, self.empty_text = list(values), float(goal or 0), empty_text
        self.update()

    def mouseMoveEvent(self, e):
        for r, tip in self._bars:
            if r.adjusted(-2, -400, 2, 0).contains(e.position()):
                QToolTip.showText(e.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()

    def paintEvent(self, _):
        P = pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        left, right, top, bottom = 44, 8, 10, 24
        area = QRectF(left, top, max(10, self.width() - left - right), max(10, self.height() - top - bottom))
        mx = max([v for _, v, _ in self.values] + [self.goal, 60.0])
        step = 30 if mx <= 150 else 60 if mx <= 360 else 120
        mx = math.ceil(mx / step) * step
        small = QFont(self.font())
        small.setPixelSize(11)
        p.setFont(small)
        grid = QColor(P["border"])
        # horizontal grid + labels (hours)
        v = 0
        while v <= mx:
            y = area.bottom() - v / mx * area.height()
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(QColor(P["muted"]))
            lab = f"{v // 60}" if v % 60 == 0 else f"{v / 60:.1f}"
            if v + step > mx and self.unit:
                lab = f"{lab} {self.unit}"
            p.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, lab)
            v += step
        n = len(self.values)
        self._bars = []
        if n:
            slot = area.width() / n
            bw = max(3.0, min(34.0, slot * 0.62))
            acc = QColor(accent())
            label_every = 1 if n <= 10 else 5
            for i, (lab, val, tip) in enumerate(self.values):
                x = area.left() + i * slot + (slot - bw) / 2
                h = val / mx * area.height() if mx else 0
                r = QRectF(x, area.bottom() - h, bw, h)
                col = QColor(acc)
                if not (self.highlight_last and i == n - 1):
                    col.setAlphaF(0.55)
                if h > 0.5:
                    rad = min(4.0, bw / 2)
                    p.save()
                    p.setClipRect(QRectF(x - 1, area.top() - 1, bw + 2, area.height() + 1))
                    p.setPen(Qt.NoPen)
                    p.setBrush(col)
                    p.drawRoundedRect(QRectF(x, r.top(), bw, h + rad * 2), rad, rad)
                    p.restore()
                self._bars.append((QRectF(x, area.top(), bw, area.height()), tip))
                if i % label_every == 0 or i == n - 1:
                    p.setPen(QColor(P["muted"]))
                    p.drawText(QRectF(area.left() + i * slot - 10, area.bottom() + 4, slot + 20, 16),
                               Qt.AlignHCenter | Qt.AlignTop, lab)
        if self.goal > 0:
            y = area.bottom() - self.goal / mx * area.height()
            pen = QPen(QColor(P["text"]), 1.2, Qt.DashLine)
            pen.setDashPattern([4, 4])
            c = QColor(P["text"])
            c.setAlphaF(0.5)
            pen.setColor(c)
            p.setPen(pen)
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        if not any(v for _, v, _ in self.values) and self.empty_text:
            p.setPen(QColor(P["muted"]))
            p.drawText(area, Qt.AlignCenter, self.empty_text)
        p.end()


# ---------------------------------------------------------------------- goal bar
class GoalBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.setFixedHeight(8)

    def set_value(self, frac: float):
        self.value = max(0.0, min(1.0, frac))
        self.update()

    def paintEvent(self, _):
        P = pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(P["surface2"]))
        p.drawRoundedRect(r, 4, 4)
        if self.value > 0:
            p.setBrush(QColor(accent()))
            p.drawRoundedRect(QRectF(0, 0, max(8.0, r.width() * self.value), r.height()), 4, 4)
        p.end()


# ---------------------------------------------------------------------- tray icon image
def tray_pixmap(progress: float, phase: str, running: bool, size: int = 64) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    col = phase_color(phase)
    s = size
    w = s * 0.16
    rect = QRectF(w / 2 + 2, w / 2 + 2, s - w - 4, s - w - 4)
    track = QColor(col)
    track.setAlphaF(0.28)
    p.setPen(QPen(track, w))
    p.drawEllipse(rect)
    if running or progress > 0:
        pen = QPen(col, w)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.drawArc(rect, 90 * 16, -int((1.0 - progress) * 360 * 16) if progress > 0 else -360 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    d = s * 0.22
    p.drawEllipse(QRectF((s - d) / 2, (s - d) / 2, d, d))
    p.end()
    return pm
