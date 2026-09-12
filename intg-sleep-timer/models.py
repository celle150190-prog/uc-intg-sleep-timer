"""Shared data models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TimerMode(StrEnum):
    """Available timer modes."""

    OFF = "off"
    DEADLINE = "deadline"
    CURRENT_ITEM = "current_item"


@dataclass(slots=True)
class PlaybackSnapshot:
    """Normalized state of a playing media item."""

    provider: str
    item_id: str
    title: str
    state: str
    position: float | None = None
    duration: float | None = None
    app: str = ""

    @property
    def is_playing(self) -> bool:
        return self.state.casefold() in {"playing", "paused", "buffering"}

    @property
    def remaining(self) -> float | None:
        if self.position is None or self.duration is None or self.duration <= 0:
            return None
        return max(0.0, self.duration - self.position)

    @property
    def identity(self) -> str:
        """Return the strongest available identity of the current item."""
        if self.item_id:
            return f"id:{self.item_id}"
        generic = {
            "emby",
            "netflix",
            "prime video",
            "amazon prime video",
            "amazon video",
        }
        normalized = self.title.strip().casefold()
        if normalized and normalized not in generic:
            return f"title:{normalized}"
        return ""


@dataclass(slots=True)
class TimerView:
    """State displayed by the Remote entities."""

    mode: TimerMode = TimerMode.OFF
    status: str = "Aus"
    remaining_seconds: int | None = None
    source: str = ""
    title: str = ""
