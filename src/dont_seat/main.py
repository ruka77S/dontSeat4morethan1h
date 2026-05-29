"""Application assembly for Don't Seat 1h."""
from __future__ import annotations

from .tray_app import TrayApp


def main() -> None:
    TrayApp().run()