"""Playback sources for Emby and Remote media-player entities."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import Settings
from core_client import CoreApiError, CoreClient
from models import PlaybackSnapshot

_LOG = logging.getLogger(__name__)
_STREAMING_APPS = {
    "netflix": "Netflix",
    "prime video": "Prime Video",
    "amazon prime video": "Prime Video",
    "amazon video": "Prime Video",
}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _ticks(value: Any) -> float | None:
    number = _number(value)
    return None if number is None else number / 10_000_000


class EmbySource:
    """Read the currently playing item directly from Emby Server."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.emby_url.strip().rstrip("/")
        self._key = settings.emby_api_key.strip()
        self._device_filter = settings.emby_device_filter.strip().casefold()

    @property
    def configured(self) -> bool:
        return bool(self._url and self._key)

    async def current(self) -> PlaybackSnapshot | None:
        if not self.configured:
            return None
        sessions_path = (
            "/Sessions" if self._url.casefold().endswith("/emby") else "/emby/Sessions"
        )
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(
                    f"{self._url}{sessions_path}",
                    headers={"X-Emby-Token": self._key},
                )
            response.raise_for_status()
            sessions = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            _LOG.exception("Cannot read Emby sessions")
            return None

        candidates: list[dict[str, Any]] = []
        for session in sessions if isinstance(sessions, list) else []:
            now_playing = session.get("NowPlayingItem")
            if not isinstance(now_playing, dict):
                continue
            searchable = " ".join(
                str(session.get(key, ""))
                for key in ("DeviceName", "Client", "DeviceId")
            ).casefold()
            if self._device_filter and self._device_filter not in searchable:
                continue
            candidates.append(session)
        if not candidates:
            return None

        session = next(
            (
                item
                for item in candidates
                if not item.get("PlayState", {}).get("IsPaused", False)
            ),
            candidates[0],
        )
        item = session["NowPlayingItem"]
        play_state = session.get("PlayState", {})
        paused = bool(play_state.get("IsPaused", False))
        title = str(item.get("Name") or item.get("OriginalTitle") or "Emby")
        return PlaybackSnapshot(
            provider="Emby",
            item_id=str(item.get("Id", "")),
            title=title,
            state="PAUSED" if paused else "PLAYING",
            position=_ticks(play_state.get("PositionTicks")),
            duration=_ticks(item.get("RunTimeTicks")),
            app="Emby",
        )


class CoreMediaSource:
    """Read a media-player entity exposed by Remote Core."""

    def __init__(self, client: CoreClient, entity_id: str, provider: str) -> None:
        self._client = client
        self._entity_id = entity_id.strip()
        self._provider = provider

    @property
    def configured(self) -> bool:
        return bool(self._entity_id)

    async def current(self) -> PlaybackSnapshot | None:
        if not self.configured:
            return None
        try:
            entity = await self._client.get_entity(self._entity_id)
        except CoreApiError:
            _LOG.exception("Cannot read media entity %s", self._entity_id)
            return None
        attrs = entity.get("attributes", {})
        if not isinstance(attrs, dict):
            return None
        app = str(attrs.get("source", ""))
        title = str(attrs.get("media_title", ""))
        return PlaybackSnapshot(
            provider=self._provider,
            item_id=str(attrs.get("media_id", "")),
            title=title,
            state=str(attrs.get("state", "UNKNOWN")),
            position=_number(attrs.get("media_position")),
            duration=_number(attrs.get("media_duration")),
            app=app,
        )


class PlaybackResolver:
    """Pick the currently active supported playback source."""

    def __init__(self, settings: Settings, client: CoreClient) -> None:
        self._emby = EmbySource(settings)
        self._emby_entity = CoreMediaSource(client, settings.emby_entity_id, "Emby")
        self._shield = CoreMediaSource(client, settings.shield_entity_id, "Shield")

    async def current(self) -> PlaybackSnapshot | None:
        # The direct Emby API has an actual item id and is therefore preferred.
        emby = await self._emby.current()
        if emby and emby.is_playing:
            return emby

        emby_entity = await self._emby_entity.current()
        if emby_entity and emby_entity.is_playing:
            haystack = f"{emby_entity.app} {emby_entity.title}".casefold()
            if "emby" in haystack:
                emby_entity.provider = "Emby"
                return emby_entity

        shield = await self._shield.current()
        if shield and shield.is_playing:
            haystack = f"{shield.app} {shield.title}".strip().casefold()
            for marker, label in _STREAMING_APPS.items():
                if marker in haystack:
                    shield.provider = label
                    return shield
        return None
