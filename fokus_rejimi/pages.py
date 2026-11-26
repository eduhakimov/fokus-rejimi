"""Pages of the main window: timer, blocking, statistics, settings."""
from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSlider, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from uzkit.i18n import language, tr
from uzkit.widgets import is_admin, primary_button

from .blocker import ACTION_CLOSE, ACTION_MINIMIZE, is_protected, normalize_name, user_app_names
from .hosts import normalize_domain
from .timer import FOCUS, LONG, SHORT, fmt_mmss
from .ui import BarChart, GoalBar, SessionDots, TimerRing, line_icon, pal


def section(title: str) -> QLabel:
    l = QLabel(title)
    l.setObjectName("Section")
    return l


def muted(text: str = "", wrap: bool = True) -> QLabel:
    l = QLabel(text)
    l.setObjectName("Muted")
    l.setWordWrap(wrap)
    return l


def panel() -> QFrame:
    f = QFrame()
    f.setObjectName("Panel")
    return f


def fmt_minutes(m: float) -> str:
    m = int(round(m))
    h, mm = divmod(m, 60)
    if h:
        return tr("fmt_hm", h=h, m=mm) if mm else tr("fmt_h", h=h)
    return tr("fmt_m", m=mm)


# ====================================================================== phrase dialog
class NoPasteEdit(QLineEdit):
    """The phrase has to be typed, not pasted."""

    def __init__(self):
        super().__init__()
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setAcceptDrops(False)

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Paste) or (e.key() == Qt.Key_Insert and e.modifiers() & Qt.ShiftModifier):
            return
        super().keyPressEvent(e)


class PhraseDialog(QDialog):
    """Strict mode: the user has to type the phrase exactly to go on."""

    def __init__(self, phrase: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("strict_title"))
        self.setMinimumWidth(460)
        self.phrase = phrase
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel(tr("strict_prompt")))
        q = QLabel(phrase)
        q.setObjectName("Phrase")
        q.setWordWrap(True)
        q.setTextInteractionFlags(Qt.NoTextInteraction)
        lay.addWidget(q)
        self.edit = NoPasteEdit()
        lay.addWidget(self.edit)
        bb = QDialogButtonBox()
        self.ok = bb.addButton(tr("strict_confirm"), QDialogButtonBox.AcceptRole)
        bb.addButton(tr("cancel"), QDialogButtonBox.RejectRole)
        self.ok.setEnabled(False)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.edit.textChanged.connect(self._check)

    @staticmethod
    def matches(typed: str, phrase: str) -> bool:
        norm = lambda s: " ".join((s or "").split()).casefold()
        return bool(phrase.strip()) and norm(typed) == norm(phrase)

    def _check(self, t):
        self.ok.setEnabled(self.matches(t, self.phrase))



# ====================================================================== timer page
class TimerPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(22)

        # left: ring and controls
        left = QVBoxLayout()
        left.setSpacing(12)
        self.ring = TimerRing()
        left.addWidget(self.ring, 1)
        self.dots = SessionDots()
        left.addWidget(self.dots)
        ctr = QHBoxLayout()
        ctr.setSpacing(12)
        ctr.addStretch(1)
        self.btn_stop = QPushButton()
        self.btn_skip = QPushButton()
        for b, tip in ((self.btn_stop, "stop_tip"), (self.btn_skip, "skip_tip")):
            b.setObjectName("RoundButton")
            b.setFixedSize(46, 46)
            b.setToolTip(tr(tip))
            b.setCursor(Qt.PointingHandCursor)
        self.btn_main = primary_button(tr("start"))
        self.btn_main.setObjectName("BigPrimary")
        self.btn_main.setMinimumWidth(170)
        self.btn_main.setFixedHeight(46)
        ctr.addWidget(self.btn_stop)
        ctr.addWidget(self.btn_main)
        ctr.addWidget(self.btn_skip)
        ctr.addStretch(1)
        left.addLayout(ctr)
        left.addSpacing(4)
        root.addLayout(left, 1)

        # right: task, today, protection
        side = QVBoxLayout()
        side.setSpacing(12)
        p1 = panel()
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(16, 14, 16, 16)
        l1.addWidget(section(tr("task")))
        self.task = QLineEdit()
        self.task.setPlaceholderText(tr("task_ph"))
        self.task.setMaxLength(120)
        l1.addWidget(self.task)
        self.next_lbl = muted()
        l1.addWidget(self.next_lbl)
        side.addWidget(p1)

        p2 = panel()
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(16, 14, 16, 16)
        l2.setSpacing(8)
        l2.addWidget(section(tr("today")))
        self.today_big = QLabel()
        self.today_big.setObjectName("BigNumber")
        l2.addWidget(self.today_big)
        self.goal_bar = GoalBar()
        l2.addWidget(self.goal_bar)
        self.today_sub = muted()
        l2.addWidget(self.today_sub)
        side.addWidget(p2)

        p3 = panel()
        l3 = QVBoxLayout(p3)
        l3.setContentsMargins(16, 14, 16, 16)
        l3.setSpacing(6)
        l3.addWidget(section(tr("protection")))
        self.prot_apps = QLabel()
        self.prot_sites = QLabel()
        self.prot_apps.setWordWrap(True)
        self.prot_sites.setWordWrap(True)
        l3.addWidget(self.prot_apps)
        l3.addWidget(self.prot_sites)
        self.strict = QCheckBox(tr("strict_mode"))
        self.strict.setToolTip(tr("strict_tip"))
        l3.addSpacing(4)
        l3.addWidget(self.strict)
        side.addWidget(p3)
        side.addStretch(1)
        sidew = QWidget()
        sidew.setLayout(side)
        sidew.setFixedWidth(300)
        root.addWidget(sidew)

        self.btn_main.clicked.connect(win.toggle_timer)
        self.ring.clicked.connect(win.toggle_timer)
        self.btn_stop.clicked.connect(win.stop_timer)
        self.btn_skip.clicked.connect(win.skip_phase)
        self.task.setText(win.cfg["task"])
        self.task.editingFinished.connect(lambda: win.cfg.set("task", self.task.text().strip()))
        self.strict.setChecked(bool(win.cfg["strict"]))
        self.strict.toggled.connect(win.set_strict)
        self.refresh_icons()

    def refresh_icons(self):
        P = pal()
        self.btn_stop.setIcon(line_icon("stop", P["text"]))
        self.btn_skip.setIcon(line_icon("skip", P["text"]))

    def update_view(self):
        w = self.win
        t = w.timer
        phase_name = tr(f"phase_{t.phase}")
        if t.state == "running":
            sub = tr("state_running")
            main_txt, icon = tr("pause"), "pause"
        elif t.state == "paused":
            sub = tr("state_paused")
            main_txt, icon = tr("resume"), "play"
        else:
            sub = tr("state_idle")
            main_txt, icon = tr("start"), "play"
        if t.phase == FOCUS and w.cfg["task"] and t.state != "idle":
            sub = w.cfg["task"]
        self.ring.set_state(t.progress(), fmt_mmss(t.remaining()), t.phase, phase_name, sub, t.state == "running")
        if self.btn_main.text() != main_txt:
            self.btn_main.setText(main_txt)
            self.btn_main.setIcon(line_icon(icon, "#ffffff"))
        n = max(1, int(w.timer.cfg.long_every))
        done = t.completed_focus % n
        if t.completed_focus and done == 0 and t.phase == LONG:
            done = n
        self.dots.set_value(done, n)
        self.btn_stop.setEnabled(t.active or t.phase != FOCUS)
        if t.phase == FOCUS:
            # which break follows this focus session
            n_after = t.completed_focus + 1
            nb = LONG if n_after % n == 0 else SHORT
            self.next_lbl.setText(tr("next_is", what=tr(f"phase_{nb}"), m=int(t.cfg.duration(nb) // 60)))
        else:
            self.next_lbl.setText(tr("next_is", what=tr("phase_focus"), m=int(t.cfg.duration(FOCUS) // 60)))

    def update_today(self, summary: dict, goal: float, streak: int):
        m = summary["minutes"]
        self.today_big.setText(fmt_minutes(m))
        self.goal_bar.set_value(m / goal if goal else 0)
        self.today_sub.setText(tr("today_sub", goal=fmt_minutes(goal), n=summary["completed"], s=streak))

    def update_protection(self, apps_on: bool, n_apps: int, sites_on: bool, n_sites: int, sites_state: str):
        self.prot_apps.setText(tr("prot_apps_on", n=n_apps) if apps_on and n_apps else tr("prot_apps_off"))
        if not sites_on:
            self.prot_sites.setText(tr("prot_sites_off"))
        elif sites_state == "need_admin":
            self.prot_sites.setText(tr("prot_sites_admin"))
        else:
            self.prot_sites.setText(tr("prot_sites_on", n=n_sites))


# ====================================================================== running apps picker
class AppPicker(QDialog):
    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("pick_title"))
        self.resize(380, 460)
        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("search"))
        lay.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for n in names:
            self.list.addItem(n)
        lay.addWidget(self.list, 1)
        if not names:
            lay.addWidget(muted(tr("pick_empty")))
        bb = QDialogButtonBox()
        bb.addButton(tr("add"), QDialogButtonBox.AcceptRole)
        bb.addButton(tr("cancel"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.filter.textChanged.connect(self._filter)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())

    def _filter(self, t):
        t = t.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text())

    def selected(self):
        return [it.text() for it in self.list.selectedItems()]


# ====================================================================== blocking page
class BlockPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        cfg = win.cfg
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        # apps
        pa = panel()
        la = QVBoxLayout(pa)
        la.setContentsMargins(18, 16, 18, 18)
        la.setSpacing(10)
        la.addWidget(section(tr("apps_title")))
        self.apps_on = QCheckBox(tr("apps_on"))
        self.apps_on.setChecked(bool(cfg["block_apps"]))
        la.addWidget(self.apps_on)
        la.addWidget(muted(tr("apps_hint")))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("col_app"), tr("col_action"), ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 44)
        self.table.verticalHeader().setDefaultSectionSize(46)
        la.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.app_edit = QLineEdit()
        self.app_edit.setPlaceholderText(tr("app_ph"))
        self.btn_add_app = QPushButton(tr("add"))
        self.btn_pick = QPushButton(tr("pick_running"))
        row.addWidget(self.app_edit, 1)
        row.addWidget(self.btn_add_app)
        row.addWidget(self.btn_pick)
        la.addLayout(row)
        wr = QHBoxLayout()
        wr.addWidget(QLabel(tr("warn_delay")))
        self.warn = QSpinBox()
        self.warn.setRange(3, 120)
        self.warn.setSuffix(" " + tr("sec"))
        self.warn.setValue(int(cfg["warn_seconds"]))
        wr.addWidget(self.warn)
        wr.addStretch(1)
        la.addLayout(wr)
        root.addWidget(pa, 3)

        # sites
        ps = panel()
        ls = QVBoxLayout(ps)
        ls.setContentsMargins(18, 16, 18, 18)
        ls.setSpacing(10)
        ls.addWidget(section(tr("sites_title")))
        self.sites_on = QCheckBox(tr("sites_on"))
        self.sites_on.setChecked(bool(cfg["block_sites"]))
        ls.addWidget(self.sites_on)
        self.sites_note = muted()
        ls.addWidget(self.sites_note)
        self.sites = QListWidget()
        ls.addWidget(self.sites, 1)
        r2 = QHBoxLayout()
        self.site_edit = QLineEdit()
        self.site_edit.setPlaceholderText(tr("site_ph"))
        self.btn_add_site = QPushButton(tr("add"))
        self.btn_del_site = QPushButton(tr("delete"))
        r2.addWidget(self.site_edit, 1)
        r2.addWidget(self.btn_add_site)
        r2.addWidget(self.btn_del_site)
        ls.addLayout(r2)
        root.addWidget(ps, 2)

        self._load()
        self.apps_on.toggled.connect(lambda v: (cfg.set("block_apps", bool(v)), win.protection_changed()))
        self.warn.valueChanged.connect(lambda v: (cfg.set("warn_seconds", int(v)), win.protection_changed()))
        self.btn_add_app.clicked.connect(self._add_app)
        self.app_edit.returnPressed.connect(self._add_app)
        self.btn_pick.clicked.connect(self._pick)
        self.sites_on.toggled.connect(self._sites_toggled)
        self.btn_add_site.clicked.connect(self._add_site)
        self.site_edit.returnPressed.connect(self._add_site)
        self.btn_del_site.clicked.connect(self._del_site)
        self.update_note()

    # ---------------------------------------------------------------- apps
    def _load(self):
        self.table.setRowCount(0)
        for r in self.win.cfg["apps"]:
            self._add_row(r)
        self.sites.clear()
        for s in self.win.cfg["sites"]:
            self.sites.addItem(s)

    def _add_row(self, rule: dict):
        i = self.table.rowCount()
        self.table.insertRow(i)
        cb = QCheckBox(rule.get("name", ""))
        cb.setChecked(bool(rule.get("enabled", True)))
        cb.toggled.connect(self._save_apps)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(8, 0, 4, 0)
        hl.addWidget(cb)
        self.table.setCellWidget(i, 0, holder)
        combo = QComboBox()
        combo.addItem(tr("act_close"), ACTION_CLOSE)
        combo.addItem(tr("act_minimize"), ACTION_MINIMIZE)
        combo.setCurrentIndex(1 if rule.get("action") == ACTION_MINIMIZE else 0)
        combo.currentIndexChanged.connect(self._save_apps)
        combo.setMinimumWidth(130)
        ch = QWidget()
        cl = QHBoxLayout(ch)
        cl.setContentsMargins(6, 4, 6, 4)
        cl.addWidget(combo)
        self.table.setCellWidget(i, 1, ch)
        rm = QPushButton()
        rm.setObjectName("IconButton")
        rm.setToolTip(tr("delete"))
        rm.setIcon(line_icon("minus", pal()["muted"]))
        rm.setCursor(Qt.PointingHandCursor)
        rm.clicked.connect(lambda _=False, b=rm: self._remove_row(b))
        self.table.setCellWidget(i, 2, rm)

    def _rules(self):
        out = []
        for i in range(self.table.rowCount()):
            holder = self.table.cellWidget(i, 0)
            cb = holder.findChild(QCheckBox) if holder else None
            ch = self.table.cellWidget(i, 1)
            combo = ch.findChild(QComboBox) if ch else None
            if cb is None or combo is None:
                continue
            out.append({"name": cb.text(), "enabled": cb.isChecked(), "action": combo.currentData()})
        return out

    def _save_apps(self, *_):
        self.win.cfg.set("apps", self._rules())
        self.win.protection_changed()

    def _remove_row(self, btn):
        for i in range(self.table.rowCount()):
            if self.table.cellWidget(i, 2) is btn:
                self.table.removeRow(i)
                break
        self._save_apps()

    def add_names(self, names):
        existing = {r["name"] for r in self._rules()}
        bad = []
        for raw in names:
            n = normalize_name(raw)
            if not n:
                continue
            if is_protected(n):
                bad.append(n)
                continue
            if n in existing:
                continue
            existing.add(n)
            self._add_row({"name": n, "enabled": True, "action": ACTION_CLOSE})
        self._save_apps()
        if bad:
            self.win.status(tr("protected_app", name=", ".join(bad)), 7000)

    def _add_app(self):
        t = self.app_edit.text().strip()
        if not t:
            return
        self.add_names([t])
        self.app_edit.clear()

    def _pick(self):
        try:
            names = user_app_names(self.win.process_lister)
        except Exception:
            names = []
        existing = {r["name"] for r in self._rules()}
        dlg = AppPicker([n for n in names if n not in existing], self)
        if dlg.exec() == QDialog.Accepted:
            self.add_names(dlg.selected())

    # ---------------------------------------------------------------- sites
    def _save_sites(self):
        self.win.cfg.set("sites", [self.sites.item(i).text() for i in range(self.sites.count())])
        self.win.protection_changed()

    def _add_site(self):
        raw = self.site_edit.text()
        added = 0
        for part in raw.replace(",", " ").split():
            d = normalize_domain(part)
            if not d:
                self.win.status(tr("bad_domain", d=part), 6000)
                continue
            if not self.sites.findItems(d, Qt.MatchExactly):
                self.sites.addItem(d)
                added += 1
        if added:
            self.site_edit.clear()
            self._save_sites()

    def _del_site(self):
        for it in self.sites.selectedItems():
            self.sites.takeItem(self.sites.row(it))
        self._save_sites()

    def _sites_toggled(self, v):
        if v and not self.win.ensure_admin_for_sites():
            self.sites_on.blockSignals(True)
            self.sites_on.setChecked(False)
            self.sites_on.blockSignals(False)
            v = False
        self.win.cfg.set("block_sites", bool(v))
        self.update_note()
        self.win.protection_changed()

    def update_note(self):
        if is_admin():
            self.sites_note.setText(tr("sites_note_admin"))
        else:
            self.sites_note.setText(tr("sites_note"))

    def set_locked(self, locked: bool):
        for w in (self.apps_on, self.table, self.app_edit, self.btn_add_app, self.btn_pick, self.warn,
                  self.sites_on, self.sites, self.site_edit, self.btn_add_site, self.btn_del_site):
            w.setEnabled(not locked)


# ====================================================================== statistics page
class StatsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.days = 7
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self.kpi = {}
        for key in ("kpi_today", "kpi_pomodoros", "kpi_streak", "kpi_interrupted"):
            f = panel()
            l = QVBoxLayout(f)
            l.setContentsMargins(16, 12, 16, 14)
            l.setSpacing(2)
            cap = muted(tr(key), wrap=False)
            val = QLabel("0")
            val.setObjectName("KpiValue")
            l.addWidget(cap)
            l.addWidget(val)
            self.kpi[key] = val
            kpis.addWidget(f, 1)
        root.addLayout(kpis)

        chart_p = panel()
        cl = QVBoxLayout(chart_p)
        cl.setContentsMargins(18, 14, 18, 14)
        head = QHBoxLayout()
        head.addWidget(section(tr("chart_title")))
        head.addStretch(1)
        self.goal_lbl = muted(wrap=False)
        head.addWidget(self.goal_lbl)
        head.addSpacing(12)
        self.b7 = QPushButton(tr("days_7"))
        self.b30 = QPushButton(tr("days_30"))
        for b in (self.b7, self.b30):
            b.setCheckable(True)
            b.setObjectName("Chip")
            b.setCursor(Qt.PointingHandCursor)
            head.addWidget(b)
        self.b7.setChecked(True)
        cl.addLayout(head)
        self.chart = BarChart()
        cl.addWidget(self.chart, 1)
        root.addWidget(chart_p, 5)

        tp = panel()
        tl = QVBoxLayout(tp)
        tl.setContentsMargins(18, 14, 18, 14)
        tl.addWidget(section(tr("recent")))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("col_when"), tr("col_task"), tr("col_length"), tr("col_result")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setDefaultSectionSize(30)
        tl.addWidget(self.table, 1)
        self.empty = muted(tr("stats_empty"))
        tl.addWidget(self.empty)
        tp.setMinimumHeight(170)
        root.addWidget(tp, 4)
        self.b7.clicked.connect(lambda: self._set_days(7))
        self.b30.clicked.connect(lambda: self._set_days(30))

    def _set_days(self, n):
        self.days = n
        self.b7.setChecked(n == 7)
        self.b30.setChecked(n == 30)
        self.refresh()

    def refresh(self):
        db = self.win.db
        if db is None:
            return
        today = date.today()
        s = db.day_summary(today)
        self.kpi["kpi_today"].setText(fmt_minutes(s["minutes"]))
        self.kpi["kpi_pomodoros"].setText(str(s["completed"]))
        self.kpi["kpi_streak"].setText(tr("n_days", n=db.streak(today)))
        self.kpi["kpi_interrupted"].setText(str(s["interrupted"]))
        goal = float(self.win.cfg["daily_goal_min"])
        self.goal_lbl.setText(tr("goal_line", g=fmt_minutes(goal)))
        vals = []
        for d, m in db.daily_minutes(self.days, today):
            lab = self._day_label(d) if self.days <= 10 else d.strftime("%d.%m")
            vals.append((lab, m, f"{d.strftime('%d.%m.%Y')}: {fmt_minutes(m)}"))
        self.chart.unit = tr("h_unit")
        self.chart.set_data(vals, goal, tr("chart_empty"))
        rows = db.recent(60)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            try:
                when = datetime.fromisoformat(r["started"]).strftime("%d.%m  %H:%M")
            except ValueError:
                when = r["started"]
            items = [when, r["task"] or "", fmt_minutes(r["actual_s"] / 60.0),
                     tr("res_done") if r["completed"] else tr("res_stopped")]
            for j, txt in enumerate(items):
                it = QTableWidgetItem(txt)
                if j == 3 and not r["completed"]:
                    it.setForeground(Qt.gray)
                self.table.setItem(i, j, it)
        self.empty.setVisible(not rows)
        self.table.setVisible(bool(rows))

    @staticmethod
    def _day_label(d: date) -> str:
        names = {"uz": ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"], "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
                 "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
        return names.get(language(), names["en"])[d.weekday()]


# ====================================================================== settings page
class SettingsPage(QScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        cfg = win.cfg
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("ScrollBody")
        self.setWidget(body)
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)

        def spin(lo, hi, val, suffix):
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(int(val))
            s.setSuffix(" " + suffix)
            s.setMinimumWidth(130)
            return s

        def form(panel_):
            f_ = QFormLayout(panel_)
            f_.setContentsMargins(18, 14, 18, 16)
            f_.setVerticalSpacing(10)
            f_.setHorizontalSpacing(14)
            f_.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            f_.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
            return f_

        # timer
        p = panel()
        f = form(p)
        f.addRow(section(tr("set_timer")))
        self.focus = spin(1, 180, cfg["focus_min"], tr("min"))
        self.short = spin(1, 60, cfg["short_min"], tr("min"))
        self.long = spin(1, 120, cfg["long_min"], tr("min"))
        self.every = QSpinBox()
        self.every.setRange(1, 12)
        self.every.setValue(int(cfg["long_every"]))
        self.every.setMinimumWidth(130)
        self.every.setSuffix(" " + tr("sessions"))
        self._row(f, tr("phase_focus"), self.focus)
        self._row(f, tr("phase_short"), self.short)
        self._row(f, tr("phase_long"), self.long)
        self._row(f, tr("long_every"), self.every)
        self.auto_b = QCheckBox(tr("auto_breaks"))
        self.auto_f = QCheckBox(tr("auto_focus"))
        self.auto_b.setChecked(bool(cfg["auto_start_breaks"]))
        self.auto_f.setChecked(bool(cfg["auto_start_focus"]))
        f.addRow(self.auto_b)
        f.addRow(self.auto_f)
        grid.addWidget(p, 0, 0)

        # goal + strict
        p2 = panel()
        f2 = form(p2)
        f2.addRow(section(tr("set_goal")))
        self.goal = spin(10, 960, cfg["daily_goal_min"], tr("min"))
        self.goal.setSingleStep(15)
        self._row(f2, tr("daily_goal"), self.goal)
        f2.addRow(section(tr("strict_mode")))
        self.strict = QCheckBox(tr("strict_on"))
        self.strict.setChecked(bool(cfg["strict"]))
        f2.addRow(self.strict)
        self.phrase = QLineEdit(cfg["strict_phrase"] or tr("default_phrase"))
        self.phrase.setMinimumWidth(200)
        self._row(f2, tr("phrase"), self.phrase)
        f2.addRow(muted(tr("strict_explain")))
        grid.addWidget(p2, 0, 1)

        # sound
        p3 = panel()
        f3 = form(p3)
        f3.addRow(section(tr("set_sound")))
        self.sound = QCheckBox(tr("sound_on"))
        self.sound.setChecked(bool(cfg["sound"]))
        f3.addRow(self.sound)
        vr = QHBoxLayout()
        vr.setSpacing(10)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(cfg["volume"]))
        self.volume.setMinimumWidth(180)
        self.test = QPushButton(tr("sound_test"))
        vr.addWidget(self.volume, 1)
        vr.addWidget(self.test)
        self._row(f3, tr("volume"), vr)
        grid.addWidget(p3, 1, 0)

        # behaviour
        p4 = panel()
        f4 = form(p4)
        f4.addRow(section(tr("set_behaviour")))
        self.overlay = QCheckBox(tr("break_overlay"))
        self.overlay.setChecked(bool(cfg["break_overlay"]))
        self.tray = QCheckBox(tr("close_to_tray"))
        self.tray.setChecked(bool(cfg["close_to_tray"]))
        self.autostart = QCheckBox(tr("autostart"))
        self.autostart.setChecked(win.autostart_state())
        for w in (self.overlay, self.tray, self.autostart):
            f4.addRow(w)
        grid.addWidget(p4, 1, 1)
        grid.setRowStretch(2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # wiring
        for key, w in (("focus_min", self.focus), ("short_min", self.short), ("long_min", self.long),
                       ("long_every", self.every), ("daily_goal_min", self.goal), ("volume", self.volume)):
            w.valueChanged.connect(lambda v, k=key: self._set(k, int(v)))
        for key, w in (("auto_start_breaks", self.auto_b), ("auto_start_focus", self.auto_f),
                       ("sound", self.sound), ("break_overlay", self.overlay), ("close_to_tray", self.tray)):
            w.toggled.connect(lambda v, k=key: self._set(k, bool(v)))
        self.strict.toggled.connect(win.set_strict)
        self.phrase.editingFinished.connect(self._phrase)
        self.test.clicked.connect(lambda: win.play("focus_end", force=True))
        self.autostart.toggled.connect(win.set_autostart)

    @staticmethod
    def _row(form, text, field):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h = field.sizeHint().height() if isinstance(field, QWidget) else 0
        if h:
            lbl.setMinimumHeight(h)
        if isinstance(field, QWidget):
            form.addRow(lbl, field)
        else:
            form.addRow(lbl, field)

    def _set(self, k, v):
        self.win.cfg.set(k, v)
        self.win.settings_changed(k)

    def _phrase(self):
        t = " ".join(self.phrase.text().split())
        if len(t) < 6:
            t = tr("default_phrase")
            self.phrase.setText(t)
        self.win.cfg.set("strict_phrase", t)

    def set_locked(self, locked: bool):
        for w in (self.strict, self.phrase, self.focus, self.short, self.long, self.every):
            w.setEnabled(not locked)
