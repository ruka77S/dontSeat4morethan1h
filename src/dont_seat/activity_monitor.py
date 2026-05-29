"""Track continuous active time via Windows GetLastInputInfo."""
from __future__ import annotations
import ctypes
import time
from ctypes import wintypes
from enum import Enum


class State(Enum):
    WORKING = "working"
    IDLE = "idle"
    PAUSED = "paused"


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def get_idle_seconds() -> float:
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    millis = _kernel32.GetTickCount() - info.dwTime
    return max(0.0, millis / 1000.0)


class ActivityMonitor:
    """Accumulates continuous working seconds; resets on long idle."""

    def __init__(self, work_threshold_sec: int, idle_reset_sec: int,
                 idle_fn=get_idle_seconds, time_fn=time.monotonic):
        self.work_threshold_sec = work_threshold_sec
        self.idle_reset_sec = idle_reset_sec
        self._idle_fn = idle_fn
        self._time_fn = time_fn
        self._last_tick = time_fn()
        self.work_seconds = 0.0
        self.paused = False

    def set_thresholds(self, work_sec: int, idle_sec: int) -> None:
        self.work_threshold_sec = work_sec
        self.idle_reset_sec = idle_sec

    def reset(self) -> None:
        self.work_seconds = 0.0
        self._last_tick = self._time_fn()

    def toggle_pause(self) -> bool:
        self.paused = not self.paused
        if not self.paused:
            self._last_tick = self._time_fn()
        return self.paused

    def tick(self) -> tuple[State, bool]:
        """Advance state. Returns (current_state, should_notify)."""
        now = self._time_fn()
        elapsed = now - self._last_tick
        self._last_tick = now

        if self.paused:
            return State.PAUSED, False

        idle = self._idle_fn()
        if idle >= self.idle_reset_sec:
            self.work_seconds = 0.0
            return State.IDLE, False

        self.work_seconds += elapsed
        if self.work_seconds >= self.work_threshold_sec:
            self.work_seconds = 0.0
            return State.WORKING, True
        return State.WORKING, False
