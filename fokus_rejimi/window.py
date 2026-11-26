"""Main window: timer-centred layout with a segmented page switcher, tray icon and overlays."""
import atexit
import logging
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMenu, QStackedWidget, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from uzkit import app as appmod
from uzkit.i18n import register, tr
from uzkit.paths import data_dir, resource
from uzkit.widgets import ask, error, is_admin, relaunch_as_admin, warn
from uzkit.window import BaseMainWindow

from . import system
from .blocker import (ACTION_CLOSE, Blocker, DryRunExecutor, RealExecutor, current_username, list_processes)
from .config import Config
from .hosts import SYSTEM_HOSTS, DryRunHosts, HostsManager, expand
from .overlays import BreakOverlay, WarningOverlay
from .pages import BlockPage, PhraseDialog, SettingsPage, StatsPage, TimerPage, fmt_minutes
from .sounds import Player, ensure_sounds
from .stats import StatsDB, fill_demo
from .strings import STRINGS
from .timer import (EV_PHASE_DONE, EV_PHASE_START, EV_STOPPED, FOCUS, LONG, PAUSED, RUNNING, SHORT, PomodoroTimer,
                    fmt_mmss)
from .ui import Segmented, line_icon, pal, tray_pixmap

register(STRINGS)
_log = logging.getLogger("fokus")

TIMER_KEYS = {"focus_min", "short_min", "long_min", "long_every", "auto_start_breaks", "auto_start_focus"}


class MainWindow(BaseMainWindow):
    def __init__(self):
        super().__init__()
        self.safe = system.safe_mode()
        self.demo = "--screenshot" in sys.argv
        self._quitting = False
        self._tray_hint_shown = False
        QApplication.instance().setQuitOnLastWindowClosed(False)
        self.setMinimumSize(780, 560)
        if not (self.settings and self.settings.get("geometry")):
            self.resize(1040, 700)

        # ------------------------------------------------------------ data and engines
        self.cfg = Config(self.settings, persist=not self.safe)
        if self.safe:
            folder = Path(tempfile.mkdtemp(prefix="fokus_safe_"))
        else:
            folder = data_dir(appmod.META.get("slug", "fokus-rejimi"))
        self.data_folder = folder
        try:
            self.db = StatsDB(folder / "stats.sqlite")
        except Exception as ex:  # noqa
            _log.error("stats db: %s", ex)
            self.db = StatsDB(Path(tempfile.mkdtemp(prefix="fokus_db_")) / "stats.sqlite")
        if self.demo:
            fill_demo(self.db, tasks=tr("demo_tasks").split("|"))
            self.cfg.data.update(task=tr("demo_task"), block_sites=True)
        self.player = Player(ensure_sounds(folder / "sounds"))
        self.timer = PomodoroTimer(self.cfg.timer_config())
        self.process_lister = list_processes
        if self.safe:
            executor, lister = DryRunExecutor(), (lambda: [])
            self.hosts = DryRunHosts()
        else:
            executor, lister = RealExecutor(), list_processes
            self.hosts = HostsManager(SYSTEM_HOSTS, folder / "backups")
        self.blocker = Blocker(lister, executor, user=current_username(),
                               warn_seconds=float(self.cfg["warn_seconds"]))
        self.blocker.set_rules(self.cfg["apps"])
        self.hosts_applied = False
        self.sites_state = "off"
        self._last_scan = 0.0
        self._phase_started_at = datetime.now()
        atexit.register(self._atexit_cleanup)

        # ------------------------------------------------------------ layout
        root = QWidget()
        root.setObjectName("Root")
        v = QVBoxLayout(root)
        v.setContentsMargins(24, 14, 24, 20)
        v.setSpacing(16)
        top = QHBoxLayout()
        brand = QLabel()
        ip = resource("assets", "icon.png")
        if ip.exists():
            brand.setPixmap(QPixmap(str(ip)).scaled(26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        top.addWidget(brand)
        name = QLabel(appmod.app_name())
        name.setObjectName("Brand")
        top.addWidget(name)
        top.addStretch(1)
        self.seg = Segmented([tr("page_timer"), tr("page_block"), tr("page_stats"), tr("page_settings")])
        top.addWidget(self.seg)
        top.addStretch(1)
        self.today_chip = QLabel()
        self.today_chip.setObjectName("TodayChip")
        top.addWidget(self.today_chip)
        v.addLayout(top)
        self.stack = QStackedWidget()
        self.page_timer = TimerPage(self)
        self.page_block = BlockPage(self)
        self.page_stats = StatsPage(self)
        self.page_settings = SettingsPage(self)
        for p in (self.page_timer, self.page_block, self.page_stats, self.page_settings):
            self.stack.addWidget(p)
        v.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self._nav = self.seg               # uzkit/verify tools use _nav.count() and set_page()
        self.seg.changed.connect(self.set_page)

        # File > Exit has to quit even when closing would hide to the tray
        for a in self.menu_file.actions():
            try:
                a.triggered.disconnect()
            except (RuntimeError, TypeError):
                pass
            a.triggered.connect(self.quit_app)

        self.warn_overlay = WarningOverlay()
        self.break_overlay = BreakOverlay(on_skip=lambda: self.skip_phase(from_overlay=True))
        self._build_tray()

        self.ticker = QTimer(self)
        self.ticker.setInterval(250)
        self.ticker.timeout.connect(self._tick)
        self.ticker.start()
        self._last_day = date.today()

        if self.demo:
            self.timer.set_demo(FOCUS, 17 * 60 + 42, 2)
            self.timer.start()
        self.protection_changed()
        self.refresh_today()
        self._update_all()
        if not self.safe:
            QTimer.singleShot(600, self._recover_hosts)
            if "--tray" in sys.argv and self.tray is not None:
                QTimer.singleShot(0, self.hide)

    # ================================================================== navigation
    def set_page(self, i: int):
        if 0 <= i < self.stack.count():
            self.stack.setCurrentIndex(i)
            self.seg.set_current(i)
            if i == 2:
                self.page_stats.refresh()

    # ================================================================== tray
    def _build_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        m = QMenu()
        self.act_show = QAction(tr("tray_show"), self)
        self.act_toggle = QAction(tr("start"), self)
        self.act_skip = QAction(tr("skip_tip"), self)
        self.act_stop = QAction(tr("stop_tip"), self)
        self.act_quit = QAction(tr("exit"), self)
        self.act_show.triggered.connect(self.show_window)
        self.act_toggle.triggered.connect(self.toggle_timer)
        self.act_skip.triggered.connect(self.skip_phase)
        self.act_stop.triggered.connect(self.stop_timer)
        self.act_quit.triggered.connect(self.quit_app)
        for a in (self.act_show, None, self.act_toggle, self.act_skip, self.act_stop, None, self.act_quit):
            if a is None:
                m.addSeparator()
            else:
                m.addAction(a)
        self._tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._tray_activated)
        self._tray_key = None
        self._update_tray()
        if not self.safe:
            self.tray.show()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    def show_window(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def _update_tray(self):
        if self.tray is None:
            return
        t = self.timer
        key = (t.phase, t.state, int(t.progress() * 48))
        if key != self._tray_key:
            self._tray_key = key
            self.tray.setIcon(QIcon(tray_pixmap(t.progress(), t.phase, t.state == RUNNING)))
        state = "" if t.state == RUNNING else f" ({tr('state_paused') if t.state == PAUSED else tr('state_idle')})"
        self.tray.setToolTip(f"{appmod.app_name()}\n{tr('phase_' + t.phase)}: {fmt_mmss(t.remaining())}{state}")
        self.act_toggle.setText(tr("pause") if t.state == RUNNING else (tr("resume") if t.state == PAUSED
                                                                         else tr("start")))

    def notify(self, text: str):
        if self.tray is not None and self.tray.isVisible():
            self.tray.showMessage(appmod.app_name(), text, QSystemTrayIcon.Information, 5000)
        self.status(text, 8000)

    # ================================================================== timer control
    def _strict_ok(self) -> bool:
        """In strict mode an active focus session can only be interrupted with the phrase."""
        t = self.timer
        if not (self.cfg["strict"] and t.phase == FOCUS and t.active):
            return True
        self.show_window()
        dlg = PhraseDialog(self.cfg["strict_phrase"] or tr("default_phrase"), self)
        return dlg.exec() == QDialog.Accepted

    def toggle_timer(self):
        t = self.timer
        if t.state == RUNNING and t.phase == FOCUS and not self._strict_ok():
            return
        if t.state != RUNNING and t.state != PAUSED:
            self._phase_started_at = datetime.now()
        self._handle(t.toggle())

    def stop_timer(self):
        if not self._strict_ok():
            return
        self._handle(self.timer.stop())

    def skip_phase(self, from_overlay: bool = False):
        if not from_overlay and not self._strict_ok():
            return
        self._handle(self.timer.skip())

    def _handle(self, events):
        for ev in events:
            if ev.kind in (EV_PHASE_DONE, EV_STOPPED):
                self._record(ev)
                if ev.phase == FOCUS and ev.completed:
                    self.play("focus_end")
                    nxt = self.timer.phase
                    self.notify(tr("note_focus_done", what=tr("phase_" + nxt)))
                elif ev.phase != FOCUS and ev.kind == EV_PHASE_DONE:
                    if ev.completed:
                        self.play("break_end")
                        self.notify(tr("note_break_done"))
                    self.break_overlay.hide()
            elif ev.kind == EV_PHASE_START:
                self._phase_started_at = datetime.now()
                if ev.phase in (SHORT, LONG):
                    if self.cfg["break_overlay"] and not self.safe:
                        self.break_overlay.show(ev.phase)
                else:
                    self.break_overlay.hide()
        if self.timer.phase == FOCUS or not self.timer.active:
            if self.break_overlay.visible and self.timer.phase == FOCUS:
                self.break_overlay.hide()
        self._sync_protection()
        self._update_all()
        if events:
            self.refresh_today()

    def _record(self, ev):
        if ev.phase != FOCUS or ev.elapsed < 60:
            return
        try:
            end = datetime.now()
            start = end - timedelta(seconds=ev.elapsed) if not ev.started_at else datetime.fromtimestamp(ev.started_at)
            self.db.add(start, end, ev.phase, ev.planned, ev.elapsed, ev.completed, self.cfg["task"])
        except Exception as ex:  # noqa
            _log.error("record failed: %s", ex)

    # ================================================================== tick
    def _tick(self):
        try:
            evs = self.timer.tick()
            if evs:
                self._handle(evs)
            now = time.time()
            if now - self._last_scan >= 1.0:
                self._last_scan = now
                self._scan_apps(now)
                if date.today() != self._last_day:
                    self._last_day = date.today()
                    self.refresh_today()
            if self.break_overlay.visible:
                if self.timer.phase in (SHORT, LONG) and self.timer.active:
                    self.break_overlay.update(fmt_mmss(self.timer.remaining()))
                else:
                    self.break_overlay.hide()
            self._update_all()
        except Exception as ex:  # noqa
            appmod.log_exception(ex)

    def _focus_running(self) -> bool:
        return self.timer.phase == FOCUS and self.timer.state == RUNNING

    def _scan_apps(self, now: float):
        if not (self._focus_running() and self.cfg["block_apps"] and self.blocker.rules):
            if self.warn_overlay.isVisible():
                self.warn_overlay.hide()
            self.blocker.reset()
            return
        res = self.blocker.tick()
        if res["new"]:
            self.play("warning")
        for ex in res["executed"]:
            act = tr("did_close") if ex.action == ACTION_CLOSE else tr("did_minimize")
            self.status(f"{ex.name}: {act}", 6000)
        pend = res["pending"]
        if pend:
            items = [(w.name, tr("act_close_lc") if w.action == ACTION_CLOSE else tr("act_minimize_lc"))
                     for w in pend]
            left = int(round(min(w.deadline for w in pend) - now))
            self.warn_overlay.show_items(items, left)
        elif self.warn_overlay.isVisible():
            self.warn_overlay.hide()

    # ================================================================== protection (apps + hosts)
    def protection_changed(self):
        self.blocker.warn_seconds = float(self.cfg["warn_seconds"])
        self.blocker.set_rules(self.cfg["apps"])
        self._sync_protection()
        self._update_protection_view()

    def _sites(self):
        return list(self.cfg["sites"] or [])

    def _sync_protection(self):
        want = bool(self.cfg["block_sites"]) and self.timer.phase == FOCUS and self.timer.active \
            and bool(expand(self._sites()))
        if want and not self.hosts_applied:
            if self.safe or is_admin():
                try:
                    self.hosts.apply(self._sites())
                    self.hosts_applied = True
                    self.sites_state = "on"
                except Exception as ex:  # noqa
                    _log.error("hosts apply: %s", ex)
                    self.sites_state = "need_admin"
                    self.status(tr("hosts_failed"), 8000)
            else:
                self.sites_state = "need_admin"
        elif not want and self.hosts_applied:
            self._remove_hosts()
        if not self.cfg["block_sites"]:
            self.sites_state = "off"
        elif not (self.safe or is_admin()):
            self.sites_state = "need_admin"
        locked = bool(self.cfg["strict"]) and self.timer.phase == FOCUS and self.timer.active
        self.page_block.set_locked(locked) if hasattr(self, "page_block") else None
        self.page_settings.set_locked(locked) if hasattr(self, "page_settings") else None
        self._update_protection_view()

    def _remove_hosts(self) -> bool:
        try:
            self.hosts.remove()
            self.hosts_applied = False
            return True
        except Exception as ex:  # noqa
            _log.error("hosts remove: %s", ex)
            self.status(tr("hosts_failed"), 8000)
            return False

    def _recover_hosts(self):
        """A block left over from a crash or power loss is removed at start."""
        try:
            if not self.hosts.is_blocked():
                return
        except Exception:
            return
        if self._remove_hosts():
            self.notify(tr("hosts_recovered"))
        else:
            if ask(self, tr("hosts_left"), tr("warning")) and relaunch_as_admin():
                self.quit_app(force=True)

    def _atexit_cleanup(self):
        if self.hosts_applied:
            try:
                self.hosts.remove()
                self.hosts_applied = False
            except Exception:
                pass

    def ensure_admin_for_sites(self):
        """True: go on. False: keep it off. None: the app restarts as administrator."""
        if self.safe or is_admin():
            return True
        if ask(self, tr("sites_need_admin"), tr("sites_title")):
            self.cfg.set("block_sites", True)
            if relaunch_as_admin():
                QTimer.singleShot(0, lambda: self.quit_app(force=True))
                return None
            self.cfg.set("block_sites", False)
            error(self, tr("admin_failed"))
        return False

    def _update_protection_view(self):
        if not hasattr(self, "page_timer"):
            return
        n_apps = len(self.blocker.rules)
        self.page_timer.update_protection(bool(self.cfg["block_apps"]), n_apps, bool(self.cfg["block_sites"]),
                                          len([s for s in self._sites()]), self.sites_state)

    # ================================================================== settings
    def settings_changed(self, key: str):
        if key in TIMER_KEYS:
            self.timer.apply_config(self.cfg.timer_config())
        self._update_all()
        if key == "daily_goal_min":
            self.refresh_today()

    def set_strict(self, value: bool):
        value = bool(value)
        if not value and self.cfg["strict"] and not self._strict_ok():
            value = True
        self.cfg.set("strict", value)
        for cb in (self.page_timer.strict, self.page_settings.strict):
            if cb.isChecked() != value:
                cb.blockSignals(True)
                cb.setChecked(value)
                cb.blockSignals(False)
        self._sync_protection()

    def autostart_state(self) -> bool:
        if self.safe:
            return False
        try:
            return system.autostart_enabled()
        except Exception:
            return False

    def set_autostart(self, value: bool):
        if self.safe:
            return
        try:
            system.set_autostart(bool(value))
        except Exception as ex:  # noqa
            _log.error("autostart: %s", ex)
            error(self, tr("autostart_failed"))

    def play(self, name: str, force: bool = False):
        if not (self.cfg["sound"] or force):
            return
        self.player.volume = max(0.0, min(1.0, float(self.cfg["volume"]) / 100.0))
        self.player.muted = False
        try:
            self.player.play(name)
        except Exception as ex:  # noqa
            _log.warning("sound: %s", ex)

    # ================================================================== views
    def refresh_today(self):
        try:
            today = date.today()
            s = self.db.day_summary(today)
            goal = float(self.cfg["daily_goal_min"] or 0)
            self.page_timer.update_today(s, goal, self.db.streak(today))
            self.today_chip.setText(tr("chip_today", t=fmt_minutes(s["minutes"]), g=fmt_minutes(goal)))
            if self.stack.currentIndex() == 2:
                self.page_stats.refresh()
        except Exception as ex:  # noqa
            _log.error("refresh: %s", ex)

    def _update_all(self):
        self.page_timer.update_view()
        self._update_tray()

    def on_theme_changed(self):
        self.page_timer.refresh_icons()
        for w in (self.page_timer, self.page_block, self.page_stats, self.page_settings):
            w.update()
        self.page_timer.btn_main.setText("")
        self._update_all()

    # ================================================================== closing
    def quit_app(self, force: bool = False):
        if not force and not self._strict_ok():
            return
        self._quitting = True
        self.close()

    def closeEvent(self, e):
        hide_to_tray = (not self._quitting and not self.safe and self.tray is not None and self.tray.isVisible()
                        and (self.timer.active or self.cfg["close_to_tray"]))
        if hide_to_tray:
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(appmod.app_name(), tr("tray_hint"), QSystemTrayIcon.Information, 4000)
            return
        if not self._quitting and not self.safe and self.cfg["strict"] and self.timer.phase == FOCUS \
                and self.timer.active and not self._strict_ok():
            e.ignore()
            return
        self.ticker.stop()
        if self.timer.active:
            self._handle(self.timer.stop())
        if self.hosts_applied:
            self._remove_hosts()
        self.warn_overlay.hide()
        self.warn_overlay.deleteLater()
        self.break_overlay.hide()
        if self.tray is not None:
            self.tray.hide()
        self.db.close()
        if self.safe:
            import shutil
            shutil.rmtree(self.data_folder, ignore_errors=True)
        super().closeEvent(e)
        if not self.safe:
            QTimer.singleShot(0, QApplication.instance().quit)
