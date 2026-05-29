"""Taskbar-adjacent animated companion bar."""
from __future__ import annotations

import ctypes
import importlib
import math
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from .activity_monitor import ActivityMonitor, State

BAR_WIDTH = 280
BAR_HEIGHT = 52
FRAME_MS = 90
MARGIN = 10
BREAK_ALERT_MS = 25_000
ALERT_SCALE = 2.0
CAT_REFERENCE_IMAGE = Path(__file__).resolve().parents[2] / "original-56E660C0-97DD-451E-B666-C1AD0DF69B82.jpeg"


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class BarSnapshot:
    state: State
    work_seconds: float
    work_threshold_sec: int
    paused: bool

    @classmethod
    def from_monitor(cls, monitor: ActivityMonitor, state: State) -> "BarSnapshot":
        return cls(
            state=state,
            work_seconds=monitor.work_seconds,
            work_threshold_sec=monitor.work_threshold_sec,
            paused=monitor.paused,
        )


@dataclass(frozen=True)
class BarStyle:
    label: str
    detail: str
    accent: str


@dataclass(frozen=True)
class CatPalette:
    fur: str
    shadow: str
    muzzle: str
    stripe: str


DEFAULT_CAT_PALETTE = CatPalette(fur="#7a6248", shadow="#593f26", muzzle="#cac4b4", stripe="#866f5c")


class _WinRect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, remainder = divmod(total, 60)
    return f"{minutes}m {remainder:02d}s"


def bar_style_for_snapshot(snapshot: BarSnapshot, break_active: bool = False) -> BarStyle:
    if break_active:
        return BarStyle("MOVE!", "stretch break", "#ff6b8a")
    if snapshot.paused or snapshot.state == State.PAUSED:
        return BarStyle("SNOOZED", "timer parked", "#ffb86b")
    if snapshot.state == State.IDLE:
        return BarStyle("AWAY", "clock reset", "#8ea0ad")
    return BarStyle("WORKING", "chair time", "#4de7b0")


def bar_detail_for_snapshot(
    snapshot: BarSnapshot,
    style: BarStyle,
    break_worked_min: int = 0,
    break_active: bool = False,
) -> str:
    if break_active:
        return f"{style.detail} {break_worked_min}m done"
    if snapshot.state == State.WORKING and not snapshot.paused:
        return f"{style.detail} {format_duration(snapshot.work_seconds)} / {format_duration(snapshot.work_threshold_sec)}"
    return f"{style.detail} {format_duration(snapshot.work_seconds)}"


def cat_pose_for_snapshot(snapshot: BarSnapshot, break_active: bool = False) -> str:
    if break_active:
        return "exercise"
    if snapshot.paused or snapshot.state == State.PAUSED:
        return "meeting"
    return "working"


def _rgb_to_hex(color: tuple[int, int, int]) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def _luminance(color: tuple[int, int, int]) -> float:
    red, green, blue = color
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def cat_palette_from_photo(path: Path) -> CatPalette:
    try:
        image_module = importlib.import_module("PIL.Image")
        with image_module.open(path) as image:
            colors = image.convert("RGB").resize((80, 80)).quantize(colors=6).convert("RGB").getcolors(6400)
    except (ImportError, OSError):
        return DEFAULT_CAT_PALETTE

    if not colors:
        return DEFAULT_CAT_PALETTE

    ranked = [color for _count, color in sorted(colors, reverse=True)]
    fur = ranked[0]
    shadow = min(ranked, key=_luminance)
    muzzle = max(ranked, key=_luminance)
    stripe = ranked[2] if len(ranked) > 2 else fur
    return CatPalette(_rgb_to_hex(fur), _rgb_to_hex(shadow), _rgb_to_hex(muzzle), _rgb_to_hex(stripe))


def bar_position(
    screen_width: int,
    screen_height: int,
    work_area: Rect,
    width: int = BAR_WIDTH,
    height: int = BAR_HEIGHT,
    margin: int = MARGIN,
) -> tuple[int, int]:
    usable_right = min(screen_width, work_area.right)
    usable_bottom = min(screen_height, work_area.bottom)
    x = usable_right - width - margin
    y = usable_bottom - height - margin
    return max(work_area.left + margin, x), max(work_area.top + margin, y)


def clamp_bar_position(
    x: int,
    y: int,
    work_area: Rect,
    width: int = BAR_WIDTH,
    height: int = BAR_HEIGHT,
    margin: int = MARGIN,
) -> tuple[int, int]:
    min_x = work_area.left + margin
    min_y = work_area.top + margin
    max_x = work_area.right - width - margin
    max_y = work_area.bottom - height - margin
    return min(max(x, min_x), max_x), min(max(y, min_y), max_y)


def center_position(work_area: Rect, width: int, height: int) -> tuple[int, int]:
    x = work_area.left + (work_area.right - work_area.left - width) // 2
    y = work_area.top + (work_area.bottom - work_area.top - height) // 2
    return x, y


def alert_geometry(
    work_area: Rect,
    width: int = BAR_WIDTH,
    height: int = BAR_HEIGHT,
    scale: float = ALERT_SCALE,
) -> tuple[int, int, int, int]:
    alert_width = int(width * scale)
    alert_height = int(height * scale)
    x, y = center_position(work_area, alert_width, alert_height)
    return alert_width, alert_height, x, y


def _system_work_area(screen_width: int, screen_height: int) -> Rect:
    rect = _WinRect()
    ok = ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
    if not ok:
        return Rect(0, 0, screen_width, screen_height)
    return Rect(rect.left, rect.top, rect.right, rect.bottom)


def _put_latest(items: queue.Queue[BarSnapshot], snapshot: BarSnapshot) -> None:
    try:
        items.put_nowait(snapshot)
    except queue.Full:
        try:
            items.get_nowait()
        except queue.Empty:
            pass
        items.put_nowait(snapshot)


def _rounded_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, fill: str) -> None:
    canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill)
    canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=fill)
    canvas.create_oval(x1, y1, x1 + radius * 2, y1 + radius * 2, fill=fill, outline=fill)
    canvas.create_oval(x2 - radius * 2, y1, x2, y1 + radius * 2, fill=fill, outline=fill)
    canvas.create_oval(x1, y2 - radius * 2, x1 + radius * 2, y2, fill=fill, outline=fill)
    canvas.create_oval(x2 - radius * 2, y2 - radius * 2, x2, y2, fill=fill, outline=fill)


class TaskbarCompanionBar:
    def __init__(
        self,
        width: int = BAR_WIDTH,
        height: int = BAR_HEIGHT,
        frame_ms: int = FRAME_MS,
        initial_position: tuple[int, int] | None = None,
        on_position_changed: Callable[[int, int], None] | None = None,
    ):
        self.width = width
        self.height = height
        self.frame_ms = frame_ms
        self._snapshots: queue.Queue[BarSnapshot] = queue.Queue(maxsize=2)
        self._break_alerts: queue.Queue[int] = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._root: tk.Tk | None = None
        self._snapshot = BarSnapshot(State.IDLE, 0.0, 3600, False)
        self._cat_palette = cat_palette_from_photo(CAT_REFERENCE_IMAGE)
        self._custom_position = initial_position
        self._on_position_changed = on_position_changed
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._break_frames_remaining = 0
        self._break_worked_min = 0
        self._alert_mode = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="DontSeatTaskbarBar")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def update(self, snapshot: BarSnapshot) -> None:
        _put_latest(self._snapshots, snapshot)

    def show_break(self, worked_min: int) -> None:
        try:
            self._break_alerts.put_nowait(worked_min)
        except queue.Full:
            try:
                self._break_alerts.get_nowait()
            except queue.Empty:
                pass
            self._break_alerts.put_nowait(worked_min)

    def _run(self) -> None:
        root = tk.Tk()
        self._root = root
        root.title("Don't Seat 1h")
        root.overrideredirect(True)
        root.resizable(False, False)
        root.configure(bg="#101418")
        root.attributes("-topmost", True)
        for attr, value in (("-alpha", 0.96), ("-toolwindow", True)):
            try:
                root.attributes(attr, value)
            except tk.TclError:
                pass

        canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#101418", highlightthickness=0, bd=0)
        canvas.pack()
        canvas.bind("<ButtonPress-1>", lambda event: self._begin_drag(root, event))
        canvas.bind("<B1-Motion>", lambda event: self._drag(root, event))
        canvas.bind("<ButtonRelease-1>", lambda event: self._end_drag(root, event))
        self._position(root)

        def animate(frame: int = 0) -> None:
            if self._stop.is_set():
                root.destroy()
                return
            self._drain_snapshots()
            self._drain_break_alerts()
            if frame % 120 == 0 and self._custom_position is None:
                self._position(root)
            self._draw(canvas, frame)
            root.after(self.frame_ms, animate, frame + 1)

        root.after(0, animate)
        root.mainloop()
        self._root = None

    def _position(self, root: tk.Tk) -> None:
        root.update_idletasks()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        work_area = _system_work_area(screen_width, screen_height)
        if self._custom_position is None:
            x, y = bar_position(screen_width, screen_height, work_area, self.width, self.height)
        else:
            x, y = clamp_bar_position(*self._custom_position, work_area, self.width, self.height)
            self._custom_position = (x, y)
        root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def _begin_drag(self, root: tk.Tk, event: tk.Event) -> None:
        self._drag_origin = (event.x_root, event.y_root, root.winfo_x(), root.winfo_y())

    def _drag(self, root: tk.Tk, event: tk.Event) -> None:
        if self._drag_origin is None:
            return
        start_mouse_x, start_mouse_y, start_x, start_y = self._drag_origin
        self._move_to(root, start_x + event.x_root - start_mouse_x, start_y + event.y_root - start_mouse_y)

    def _end_drag(self, _root: tk.Tk, _event: tk.Event) -> None:
        self._drag_origin = None
        if self._custom_position and self._on_position_changed:
            self._on_position_changed(*self._custom_position)

    def _move_to(self, root: tk.Tk, x: int, y: int) -> None:
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        work_area = _system_work_area(screen_width, screen_height)
        self._custom_position = clamp_bar_position(x, y, work_area, self.width, self.height)
        root.geometry(f"{self.width}x{self.height}+{self._custom_position[0]}+{self._custom_position[1]}")

    def _drain_snapshots(self) -> None:
        while True:
            try:
                self._snapshot = self._snapshots.get_nowait()
            except queue.Empty:
                return

    def _drain_break_alerts(self) -> None:
        while True:
            try:
                self._break_worked_min = self._break_alerts.get_nowait()
                self._break_frames_remaining = max(1, BREAK_ALERT_MS // self.frame_ms)
            except queue.Empty:
                return

    def _set_alert_mode(self, root: tk.Tk, canvas: tk.Canvas, enabled: bool) -> None:
        if self._alert_mode == enabled:
            return
        self._alert_mode = enabled
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        work_area = _system_work_area(screen_width, screen_height)
        if enabled:
            width, height, x, y = alert_geometry(work_area, self.width, self.height)
        else:
            width, height = self.width, self.height
            if self._custom_position is None:
                x, y = bar_position(screen_width, screen_height, work_area, self.width, self.height)
            else:
                x, y = clamp_bar_position(*self._custom_position, work_area, self.width, self.height)
        canvas.configure(width=width, height=height)
        root.geometry(f"{width}x{height}+{x}+{y}")

    def _draw(self, canvas: tk.Canvas, frame: int) -> None:
        canvas.delete("all")
        snapshot = self._snapshot
        break_active = self._break_frames_remaining > 0
        self._set_alert_mode(canvas.winfo_toplevel(), canvas, break_active)
        progress = min(1.0, max(0.0, snapshot.work_seconds / max(1, snapshot.work_threshold_sec)))
        style = bar_style_for_snapshot(snapshot, break_active=break_active)

        _rounded_rect(canvas, 0, 0, self.width, self.height, 14, "#101418")
        _rounded_rect(canvas, 4, 4, self.width - 4, self.height - 4, 12, "#162026")

        streak_offset = (frame * 3) % 34
        for i in range(7):
            x = 98 + i * 32 - streak_offset
            canvas.create_line(x, 9, x + 22, 9, fill="#24333a", width=2)
            canvas.create_line(x + 7, 43, x + 29, 43, fill="#1f2a30", width=2)

        pose = cat_pose_for_snapshot(snapshot, break_active=break_active)
        if pose == "exercise":
            self._draw_exercise_cat(canvas, frame, style.accent)
        elif pose == "meeting":
            self._draw_meeting_cat(canvas, frame, style.accent)
        else:
            self._draw_worker(canvas, frame, style.accent)

        label_font = ("Segoe UI", 14 if break_active else 9, "bold")
        detail_font = ("Segoe UI", 12 if break_active else 9)
        canvas.create_text(92, 15, text=style.label, fill=style.accent, anchor="w", font=label_font)
        detail = bar_detail_for_snapshot(snapshot, style, self._break_worked_min, break_active)
        canvas.create_text(92, 28, text=detail, fill="#d8e6ea", anchor="w", font=detail_font)

        track_x, track_y, track_w, track_h = 92, 36, 172, 7
        _rounded_rect(canvas, track_x, track_y, track_x + track_w, track_y + track_h, 3, "#273137")
        if progress > 0:
            fill_w = max(7, int(track_w * progress))
            _rounded_rect(canvas, track_x, track_y, track_x + fill_w, track_y + track_h, 3, style.accent)

        pulse = int(48 + 24 * (1 + math.sin(frame * 0.25)))
        canvas.create_oval(self.width - 20, 15, self.width - 9, 26, fill=style.accent, outline="#11181d", width=2)
        canvas.create_oval(self.width - 17, 18, self.width - 12, 23, fill=f"#{pulse:02x}{pulse:02x}{pulse:02x}", outline="")
        if break_active:
            canvas.scale("all", 0, 0, ALERT_SCALE, ALERT_SCALE)
        if break_active:
            self._break_frames_remaining -= 1

    def _draw_worker(self, canvas: tk.Canvas, frame: int, accent: str) -> None:
        palette = self._cat_palette
        paw_motion = math.sin(frame * 0.85)
        blink = frame % 42 in (0, 1)

        canvas.create_rectangle(13, 36, 72, 40, fill="#6a4b35", outline="#2b211c")
        canvas.create_rectangle(18, 18, 42, 34, fill="#18242b", outline="#51636c", width=2)
        canvas.create_rectangle(21, 21, 39, 30, fill="#55d6ff", outline="")
        for y in (23, 26, 29):
            canvas.create_line(23, y, 35 + (y % 2) * 3, y, fill="#12222a", width=1)

        canvas.create_oval(47, 27, 72, 48, fill=palette.shadow, outline="#201713", width=1)
        canvas.create_polygon(49, 14, 52, 5, 58, 15, fill=palette.fur, outline="#201713")
        canvas.create_polygon(62, 14, 68, 5, 69, 17, fill=palette.fur, outline="#201713")
        canvas.create_polygon(52, 13, 53, 9, 56, 14, fill=palette.muzzle, outline="")
        canvas.create_polygon(64, 13, 67, 9, 67, 15, fill=palette.muzzle, outline="")
        canvas.create_oval(48, 11, 70, 33, fill=palette.fur, outline="#201713", width=1)
        canvas.create_arc(50, 9, 68, 21, start=180, extent=180, fill=palette.shadow, outline=palette.shadow)
        canvas.create_line(56, 12, 54, 17, fill=palette.stripe, width=1)
        canvas.create_line(60, 11, 60, 17, fill=palette.stripe, width=1)
        canvas.create_line(64, 12, 66, 17, fill=palette.stripe, width=1)
        if blink:
            canvas.create_line(54, 19, 57, 19, fill="#1f1714", width=1)
            canvas.create_line(61, 19, 64, 19, fill="#1f1714", width=1)
        else:
            canvas.create_oval(54, 18, 57, 21, fill="#1f1714", outline="")
            canvas.create_oval(61, 18, 64, 21, fill="#1f1714", outline="")
        canvas.create_oval(56, 21, 64, 29, fill=palette.muzzle, outline="")
        canvas.create_polygon(59, 22, 61, 22, 60, 24, fill="#1f1714", outline="")
        canvas.create_arc(56, 23, 60, 28, start=280, extent=150, fill="", outline="#1f1714", width=1)
        canvas.create_arc(60, 23, 64, 28, start=110, extent=150, fill="", outline="#1f1714", width=1)
        for offset in (-2, 1, 4):
            canvas.create_line(56, 24, 47, 22 + offset, fill=palette.muzzle, width=1)
            canvas.create_line(64, 24, 74, 22 + offset, fill=palette.muzzle, width=1)

        canvas.create_oval(39, 33 + paw_motion, 49, 40 + paw_motion, fill=palette.fur, outline="#201713")
        canvas.create_oval(66, 33 - paw_motion, 76, 40 - paw_motion, fill=palette.fur, outline="#201713")
        canvas.create_rectangle(37, 36, 76, 39, fill="#d8e6ea", outline="#40525c")
        canvas.create_line(42, 38, 73, 38, fill=accent, width=1)
        canvas.create_line(45, 39, 47, 39, fill=accent, width=1)
        canvas.create_line(68, 39, 70, 39, fill=accent, width=1)

    def _draw_meeting_cat(self, canvas: tk.Canvas, frame: int, accent: str) -> None:
        palette = self._cat_palette
        nod = math.sin(frame * 0.28)
        tail = math.sin(frame * 0.36)

        canvas.create_rectangle(10, 37, 78, 43, fill="#3a2f2a", outline="#171210")
        canvas.create_rectangle(12, 43, 76, 47, fill="#6a4b35", outline="#201713")
        canvas.create_rectangle(17, 14, 38, 31, fill="#172229", outline="#51636c", width=1)
        canvas.create_line(20, 26, 35, 18, fill=accent, width=2)
        canvas.create_line(20, 26, 20, 18, fill="#2a3940", width=1)
        canvas.create_oval(62, 22 + tail, 76, 34 + tail, outline=palette.fur, width=3)

        head_y = 16 + nod
        canvas.create_polygon(46, head_y + 2, 50, head_y - 8, 55, head_y + 3, fill=palette.fur, outline="#201713")
        canvas.create_polygon(61, head_y + 3, 68, head_y - 8, 68, head_y + 6, fill=palette.fur, outline="#201713")
        canvas.create_oval(45, head_y, 69, head_y + 24, fill=palette.fur, outline="#201713", width=1)
        canvas.create_arc(47, head_y - 3, 67, head_y + 11, start=180, extent=180, fill=palette.shadow, outline=palette.shadow)
        canvas.create_line(53, head_y + 2, 51, head_y + 8, fill=palette.stripe, width=1)
        canvas.create_line(57, head_y + 1, 57, head_y + 9, fill=palette.stripe, width=1)
        canvas.create_line(62, head_y + 2, 64, head_y + 8, fill=palette.stripe, width=1)
        canvas.create_line(51, head_y + 12, 55, head_y + 12, fill="#1f1714", width=1)
        canvas.create_line(61, head_y + 12, 65, head_y + 12, fill="#1f1714", width=1)
        canvas.create_oval(54, head_y + 14, 62, head_y + 21, fill=palette.muzzle, outline="")
        canvas.create_polygon(57, head_y + 15, 60, head_y + 15, 58, head_y + 18, fill="#1f1714", outline="")

        canvas.create_line(50, head_y + 25, 42, 37, fill=palette.fur, width=4, capstyle="round")
        canvas.create_line(64, head_y + 25, 73, 37, fill=palette.fur, width=4, capstyle="round")
        canvas.create_oval(37, 34, 48, 42, fill=palette.fur, outline="#201713")
        canvas.create_oval(68, 34, 79, 42, fill=palette.fur, outline="#201713")
        canvas.create_text(27, 9, text="Q3", fill="#d8e6ea", anchor="center", font=("Segoe UI", 5, "bold"))
        canvas.create_text(58, 45, text="...", fill=accent, anchor="center", font=("Segoe UI", 7, "bold"))

    def _draw_exercise_cat(self, canvas: tk.Canvas, frame: int, accent: str) -> None:
        palette = self._cat_palette
        bounce = math.sin(frame * 0.45)
        arm = math.sin(frame * 0.9)
        body_y = 28 + bounce * 2

        canvas.create_oval(36, body_y, 70, body_y + 20, fill=palette.shadow, outline="#201713", width=1)
        canvas.create_polygon(43, body_y - 7, 47, body_y - 17, 53, body_y - 6, fill=palette.fur, outline="#201713")
        canvas.create_polygon(58, body_y - 6, 66, body_y - 17, 66, body_y - 3, fill=palette.fur, outline="#201713")
        canvas.create_oval(42, body_y - 9, 67, body_y + 16, fill=palette.fur, outline="#201713", width=1)
        canvas.create_arc(45, body_y - 11, 64, body_y + 2, start=180, extent=180, fill=palette.shadow, outline=palette.shadow)
        canvas.create_oval(49, body_y - 2, 52, body_y + 1, fill="#1f1714", outline="")
        canvas.create_oval(59, body_y - 2, 62, body_y + 1, fill="#1f1714", outline="")
        canvas.create_oval(52, body_y + 1, 60, body_y + 9, fill=palette.muzzle, outline="")
        canvas.create_polygon(55, body_y + 2, 58, body_y + 2, 56, body_y + 5, fill="#1f1714", outline="")
        canvas.create_line(45, body_y + 17, 35, body_y + 28 + arm * 3, fill=palette.fur, width=4, capstyle="round")
        canvas.create_line(64, body_y + 17, 76, body_y + 28 - arm * 3, fill=palette.fur, width=4, capstyle="round")
        canvas.create_line(45, body_y + 5, 31, body_y - 5 - arm * 4, fill=palette.fur, width=4, capstyle="round")
        canvas.create_line(64, body_y + 5, 78, body_y - 5 + arm * 4, fill=palette.fur, width=4, capstyle="round")
        canvas.create_arc(23, 8, 84, 48, start=205, extent=130, outline=accent, width=2)
        canvas.create_line(78, 16, 85, 16, fill=accent, width=2)
        canvas.create_line(78, 16, 81, 10, fill=accent, width=2)