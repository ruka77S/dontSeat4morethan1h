"""System tray UI with animated cartoon icon."""
from __future__ import annotations
import threading
import time
import tkinter as tk
from tkinter import ttk

import pystray
from pystray import MenuItem as Item, Menu

from . import config as cfg_mod
from . import icons
from .activity_monitor import ActivityMonitor, State
from .taskbar_bar import BarSnapshot, TaskbarCompanionBar

TICK_SEC = 1.0
ANIM_INTERVAL_SEC = 0.4
SETTINGS_WORK_MIN_MIN = 1
SETTINGS_WORK_MIN_MAX = 240
SETTINGS_IDLE_MIN_MIN = 1
SETTINGS_IDLE_MIN_MAX = 30


def clamp_setting_minutes(value: object, minimum: int, maximum: int) -> int:
    try:
        minutes = int(str(value).strip())
    except ValueError:
        minutes = minimum
    return min(max(minutes, minimum), maximum)


class TrayApp:
    def __init__(self):
        self.cfg = cfg_mod.load()
        self.monitor = ActivityMonitor(
            work_threshold_sec=self.cfg.work_threshold_sec,
            idle_reset_sec=self.cfg.idle_reset_sec,
        )
        self._working_frames = icons.working_frames()
        self._paused_frames = icons.paused_frames()
        self._idle_img = icons.idle_frame()
        self._frame_idx = 0
        self._state: State = State.IDLE
        self._stop = threading.Event()
        bar_position = None if self.cfg.bar_x is None or self.cfg.bar_y is None else (self.cfg.bar_x, self.cfg.bar_y)
        self.bar = TaskbarCompanionBar(initial_position=bar_position, on_position_changed=self._on_bar_position_changed)

        self.icon = pystray.Icon(
            "dont_seat_1h",
            self._working_frames[0],
            "Don't Seat 1h",
            menu=self._build_menu(),
        )

    # ---------- menu ----------
    def _status_text(self, _item) -> str:
        secs = int(self.monitor.work_seconds)
        m, s = secs // 60, secs % 60
        tag = "[Snoozed] " if self.monitor.paused else ""
        return f"{tag}Chair time: {m}m {s}s"

    def _pause_text(self, _item) -> str:
        return "Resume the Nudge" if self.monitor.paused else "Snooze the Nudge"

    def _build_menu(self) -> Menu:
        return Menu(
            Item(self._status_text, None, enabled=False),
            Menu.SEPARATOR,
            Item(self._pause_text, self._on_toggle_pause),
            Item("Tweak the Timer...", self._on_settings),
            Menu.SEPARATOR,
            Item("Make a Graceful Exit", self._on_quit),
        )

    # ---------- actions ----------
    def _on_toggle_pause(self, _icon, _item):
        paused = self.monitor.toggle_pause()
        self._state = State.PAUSED if paused else State.WORKING
        self.bar.update(BarSnapshot.from_monitor(self.monitor, self._state))
        self.icon.update_menu()

    def _on_quit(self, _icon, _item):
        self._stop.set()
        self.bar.stop()
        self.icon.stop()

    def _on_settings(self, _icon, _item):
        threading.Thread(target=self._open_settings_window, daemon=True).start()

    def _on_bar_position_changed(self, x: int, y: int) -> None:
        self.cfg.bar_x = x
        self.cfg.bar_y = y
        cfg_mod.save(self.cfg)

    def _apply_settings(self, work_min: int, idle_min: int) -> None:
        self.cfg.work_threshold_min = work_min
        self.cfg.idle_reset_min = idle_min
        cfg_mod.save(self.cfg)
        self.monitor.set_thresholds(self.cfg.work_threshold_sec, self.cfg.idle_reset_sec)
        self.monitor.reset()
        self.bar.update(BarSnapshot.from_monitor(self.monitor, self._state))
        self.icon.update_menu()

    def _open_settings_window(self):
        root = tk.Tk()
        root.title("Timer Tinkering - Don't Seat 1h")
        root.geometry("420x180")
        root.resizable(False, False)

        ttk.Label(root, text="Chair jail limit (minutes):").grid(row=0, column=0, padx=10, pady=12, sticky="w")
        work_var = tk.IntVar(value=self.cfg.work_threshold_min)
        work_spinbox = ttk.Spinbox(root, from_=SETTINGS_WORK_MIN_MIN, to=SETTINGS_WORK_MIN_MAX, textvariable=work_var, width=8)
        work_spinbox.grid(row=0, column=1)

        ttk.Label(root, text="Escape counts after (minutes):").grid(row=1, column=0, padx=10, pady=12, sticky="w")
        idle_var = tk.IntVar(value=self.cfg.idle_reset_min)
        idle_spinbox = ttk.Spinbox(root, from_=SETTINGS_IDLE_MIN_MIN, to=SETTINGS_IDLE_MIN_MAX, textvariable=idle_var, width=8)
        idle_spinbox.grid(row=1, column=1)

        status = ttk.Label(root, text="", foreground="green")
        status.grid(row=2, column=0, columnspan=2)

        def save():
            work_min = clamp_setting_minutes(work_spinbox.get(), SETTINGS_WORK_MIN_MIN, SETTINGS_WORK_MIN_MAX)
            idle_min = clamp_setting_minutes(idle_spinbox.get(), SETTINGS_IDLE_MIN_MIN, SETTINGS_IDLE_MIN_MAX)
            self._apply_settings(work_min, idle_min)
            work_var.set(work_min)
            idle_var.set(idle_min)
            status.config(text=f"Applied: work {work_min}m / away {idle_min}m. Timer restarted.")
            root.after(1200, root.destroy)

        root.bind("<Return>", lambda _event: save())
        ttk.Button(root, text="Apply Now", command=save).grid(row=3, column=0, columnspan=2, pady=10)
        root.mainloop()

    # ---------- loops ----------
    def _animation_loop(self):
        while not self._stop.is_set():
            if self._state == State.WORKING:
                self._frame_idx = (self._frame_idx + 1) % len(self._working_frames)
                self.icon.icon = self._working_frames[self._frame_idx]
            elif self._state == State.PAUSED:
                self._frame_idx = (self._frame_idx + 1) % len(self._paused_frames)
                self.icon.icon = self._paused_frames[self._frame_idx]
            else:  # IDLE
                self.icon.icon = self._idle_img
            self._stop.wait(ANIM_INTERVAL_SEC)

    def _monitor_loop(self):
        while not self._stop.is_set():
            state, notify = self.monitor.tick()
            self._state = state
            self.bar.update(BarSnapshot.from_monitor(self.monitor, state))
            if notify:
                worked = self.cfg.work_threshold_min
                self.bar.show_break(worked)
            self.icon.update_menu()
            self._stop.wait(TICK_SEC)

    def run(self):
        self.bar.start()
        self.bar.update(BarSnapshot.from_monitor(self.monitor, self._state))
        threading.Thread(target=self._animation_loop, daemon=True).start()
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        self.icon.run()
