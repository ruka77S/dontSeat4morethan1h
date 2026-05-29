"""Persistent JSON config in %APPDATA%/dont_seat_1h/config.json."""
from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_WORK_MIN = 60
DEFAULT_IDLE_MIN = 5


@dataclass
class Config:
    work_threshold_min: int = DEFAULT_WORK_MIN
    idle_reset_min: int = DEFAULT_IDLE_MIN
    bar_x: int | None = None
    bar_y: int | None = None

    @property
    def work_threshold_sec(self) -> int:
        return self.work_threshold_min * 60

    @property
    def idle_reset_sec(self) -> int:
        return self.idle_reset_min * 60


def _config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "dont_seat_1h"


def config_path() -> Path:
    return _config_dir() / "config.json"


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def load() -> Config:
    p = config_path()
    if not p.exists():
        return Config()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return Config(
            work_threshold_min=int(data.get("work_threshold_min", DEFAULT_WORK_MIN)),
            idle_reset_min=int(data.get("idle_reset_min", DEFAULT_IDLE_MIN)),
            bar_x=_optional_int(data.get("bar_x")),
            bar_y=_optional_int(data.get("bar_y")),
        )
    except (json.JSONDecodeError, TypeError, ValueError, OSError):
        return Config()


def save(cfg: Config) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
