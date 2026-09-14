"""Persistent sleep-timer state machine."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import logging
import math
import time

from config import Settings
from core_client import CoreClient
from models import PlaybackSnapshot, TimerMode, TimerView
from playback import PlaybackResolver

_LOG = logging.getLogger(__name__)

ViewCallback = Callable[[TimerView], None]


class TimerController:
    """Run fixed timers and watch the current media item."""

    def __init__(self, settings: Settings, on_view: ViewCallback) -> None:
        self._settings = settings
        self._on_view = on_view
        self._client = CoreClient(settings.core_url, settings.core_api_key)
        self._resolver = PlaybackResolver(settings, self._client)
        self._mode = TimerMode.OFF
        self._deadline: datetime | None = None
        self._armed_item: PlaybackSnapshot | None = None
        self._missing_since: float | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._last_status = ""

    @property
    def view(self) -> TimerView:
        if self._mode == TimerMode.DEADLINE and self._deadline:
            remaining = max(
                0, math.ceil((self._deadline - datetime.now(UTC)).total_seconds())
            )
            return TimerView(
                mode=self._mode,
                status=f"Noch {self._format_duration(remaining)}",
                remaining_seconds=remaining,
            )
        if self._mode == TimerMode.CURRENT_ITEM and self._armed_item:
            remaining = self._armed_item.remaining
            suffix = (
                f" – noch ca. {self._format_duration(int(remaining))}"
                if remaining is not None
                else ""
            )
            return TimerView(
                mode=self._mode,
                status=f"Nach aktuellem Element{suffix}",
                remaining_seconds=math.ceil(remaining)
                if remaining is not None
                else None,
                source=self._armed_item.provider,
                title=self._armed_item.title,
            )
        return TimerView(mode=TimerMode.OFF, status=self._last_status or "Aus")

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="sleep-timer")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def set_minutes(self, minutes: int) -> bool:
        if minutes <= 0:
            return False
        async with self._lock:
            self._mode = TimerMode.DEADLINE
            self._deadline = datetime.now(UTC) + timedelta(minutes=minutes)
            self._armed_item = None
            self._missing_since = None
            self._last_status = ""
            self._publish()
        return True

    async def add_minutes(self, minutes: int) -> bool:
        async with self._lock:
            if self._mode != TimerMode.DEADLINE or self._deadline is None:
                if minutes > 0:
                    self._mode = TimerMode.DEADLINE
                    self._deadline = datetime.now(UTC) + timedelta(minutes=minutes)
                    self._last_status = ""
                    self._publish()
                    return True
                return False
            self._deadline += timedelta(minutes=minutes)
            if self._deadline <= datetime.now(UTC):
                self._cancel_locked("Aus")
            self._publish()
        return True

    async def arm_current(self) -> bool:
        snapshot = await self._resolver.current()
        if snapshot is None or not snapshot.is_playing:
            self._last_status = "Keine unterstützte Wiedergabe erkannt"
            self._publish()
            return False
        # Netflix and Prime on Shield are only safe if the entity exposes an item
        # identity or position/duration. App-only metadata cannot identify an episode.
        if not snapshot.identity and snapshot.remaining is None:
            self._last_status = f"{snapshot.provider}: keine Enddaten verfügbar"
            self._publish()
            return False
        async with self._lock:
            self._mode = TimerMode.CURRENT_ITEM
            self._deadline = None
            self._armed_item = snapshot
            self._missing_since = None
            self._last_status = ""
            self._publish()
        return True

    async def cancel(self) -> None:
        async with self._lock:
            self._cancel_locked("Abgebrochen")
            self._publish()

    async def trigger_now(self) -> bool:
        async with self._lock:
            return await self._fire_locked()

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.sleep(max(1.0, self._settings.poll_interval))
                async with self._lock:
                    if self._mode == TimerMode.DEADLINE:
                        if self._deadline and datetime.now(UTC) >= self._deadline:
                            await self._fire_locked()
                        else:
                            self._publish()
                    elif self._mode == TimerMode.CURRENT_ITEM:
                        await self._poll_current_locked()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOG.exception("Sleep timer polling failed")

    async def _poll_current_locked(self) -> None:
        armed = self._armed_item
        if armed is None:
            self._cancel_locked("Fehler: Startelement fehlt")
            self._publish()
            return
        current = await self._resolver.current()
        if current is None:
            if self._missing_since is None:
                self._missing_since = time.monotonic()
            elif time.monotonic() - self._missing_since >= self._settings.stopped_grace:
                await self._fire_locked()
            return
        self._missing_since = None

        if armed.identity and current.identity and armed.identity != current.identity:
            await self._fire_locked()
            return
        if armed.provider != current.provider:
            await self._fire_locked()
            return
        if current.remaining is not None:
            self._armed_item = current
            if current.remaining <= self._settings.end_tolerance:
                await self._fire_locked()
                return
        self._publish()

    async def _fire_locked(self) -> bool:
        actions = self._settings.resolved_target_actions()
        if not actions:
            self._last_status = "Keine Ausschaltaktion konfiguriert"
            self._reset_after_fire()
            self._publish()
            return False

        ended_activities, activity_failures = await self._turn_off_active_activities()
        failures = 0
        for action in actions:
            if action.entity_id in ended_activities and action.command_id in {
                "activity.off",
                "off",
            }:
                continue
            try:
                await self._client.execute(action.entity_id, action.command_id)
            except Exception:
                failures += 1
                _LOG.exception(
                    "Cannot execute sleep action for entity %s", action.entity_id
                )

        if failures:
            self._last_status = (
                f"{failures} von {len(actions)} Ausschaltaktionen fehlgeschlagen"
            )
        elif len(actions) == 1:
            self._last_status = "Ausschaltaktion ausgeführt"
        else:
            self._last_status = f"{len(actions)} Ausschaltaktionen ausgeführt"

        if activity_failures:
            self._last_status += "; Aktivität nicht beendet"
        elif ended_activities:
            suffix = "Aktivität beendet"
            if len(ended_activities) > 1:
                suffix = f"{len(ended_activities)} Aktivitäten beendet"
            self._last_status += f"; {suffix}"

        self._reset_after_fire()
        self._publish()
        return failures == 0 and activity_failures == 0

    async def _turn_off_active_activities(self) -> tuple[set[str], int]:
        if not self._settings.turn_off_active_activity:
            return set(), 0
        try:
            activities = await self._client.list_active_activities()
        except Exception:
            _LOG.exception("Cannot determine the active Remote activity")
            return set(), 1

        ended: set[str] = set()
        failures = 0
        for activity in activities:
            entity_id = str(activity.get("entity_id", "")).strip()
            if not entity_id:
                continue
            try:
                await self._client.execute(entity_id, "activity.off")
                ended.add(entity_id)
            except Exception:
                failures += 1
                _LOG.exception("Cannot turn off active activity %s", entity_id)
        return ended, failures

    def _reset_after_fire(self) -> None:
        self._mode = TimerMode.OFF
        self._deadline = None
        self._armed_item = None
        self._missing_since = None

    def _cancel_locked(self, status: str) -> None:
        self._reset_after_fire()
        self._last_status = status

    def _publish(self) -> None:
        self._on_view(self.view)

    @staticmethod
    def _format_duration(seconds: int) -> str:
        minutes = max(0, math.ceil(seconds / 60))
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d} h" if hours else f"{minutes} min"
