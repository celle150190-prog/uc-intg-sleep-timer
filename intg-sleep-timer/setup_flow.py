"""Setup flow for the Sleep Timer integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import Any

import ucapi

from config import ConfigStore, Settings
from core_client import CoreApiError, CoreClient

_LOG = logging.getLogger(__name__)

_store: ConfigStore | None = None
_on_updated: Callable[[Settings], Awaitable[None]] | None = None
_pending_url = "http://127.0.0.1:8080"
_pending_key = ""


def initialize(
    store: ConfigStore,
    on_updated: Callable[[Settings], Awaitable[None]],
) -> None:
    """Provide setup-flow dependencies."""
    global _store, _on_updated
    _store = store
    _on_updated = on_updated


def setup_data_schema() -> dict[str, Any]:
    """Return the first setup screen shown by Remote."""
    return {
        "title": {"en": "Sleep Timer setup", "de": "Sleep-Timer-Einrichtung"},
        "settings": [
            {
                "id": "info",
                "label": {"en": "Requirements", "de": "Voraussetzungen"},
                "field": {
                    "label": {
                        "value": {
                            "en": "Create a Remote Core API key and an off macro before continuing.",
                            "de": (
                                "Lege vor dem Fortfahren einen Remote-Core-API-Schlüssel "
                                "und ein Ausschalt-Makro an."
                            ),
                        }
                    }
                },
            }
        ],
    }


async def driver_setup_handler(msg: ucapi.SetupDriver) -> ucapi.SetupAction:
    """Handle the dynamic setup flow."""
    if isinstance(msg, ucapi.DriverSetupRequest):
        return _credentials_screen()
    if not isinstance(msg, ucapi.UserDataResponse):
        return ucapi.SetupError()

    values = msg.input_values
    if "target_entity_id" in values:
        return await _finish(values)
    if "core_url" in values:
        return await _load_entities(values)
    return ucapi.SetupError()


def _credentials_screen(error: str = "") -> ucapi.RequestUserInput:
    settings = _store.settings if _store else Settings()
    fields: list[dict[str, Any]] = []
    if error:
        fields.append(
            {
                "id": "error",
                "label": {"en": "Connection error", "de": "Verbindungsfehler"},
                "field": {"label": {"value": {"en": error, "de": error}}},
            }
        )
    fields.extend(
        [
            {
                "id": "core_url",
                "label": {"en": "Remote Core URL", "de": "Remote-Core-URL"},
                "field": {
                    "text": {"value": settings.core_url or "http://127.0.0.1:8080"}
                },
            },
            {
                "id": "core_api_key",
                "label": {
                    "en": "Core API key (leave blank to keep existing)",
                    "de": "Core-API-Schlüssel (leer = vorhandenen behalten)",
                },
                "field": {"text": {"value": ""}},
            },
        ]
    )
    return ucapi.RequestUserInput(
        {"en": "Connect to Remote Core", "de": "Mit Remote Core verbinden"},
        fields,
    )


async def _load_entities(values: dict[str, str]) -> ucapi.SetupAction:
    global _pending_url, _pending_key
    current = _store.settings if _store else Settings()
    _pending_url = values.get("core_url", "").strip()
    _pending_key = values.get("core_api_key", "").strip() or current.core_api_key
    client = CoreClient(_pending_url, _pending_key)
    try:
        entities = await client.list_entities("media_player,macro")
    except CoreApiError as error:
        if error.status_code in {401, 403}:
            return _credentials_screen("API-Schlüssel wurde abgelehnt.")
        return _credentials_screen(f"Remote Core nicht erreichbar: {error}")

    media = [item for item in entities if item.get("entity_type") == "media_player"]
    macros = [item for item in entities if item.get("entity_type") == "macro"]
    if not macros:
        return _credentials_screen(
            "Es wurde kein Makro gefunden. Lege auf der Remote zuerst ein Ausschalt-Makro an."
        )

    empty = {"id": "", "label": {"de": "Nicht verwenden", "en": "Do not use"}}
    media_items = [empty, *(_dropdown_item(item) for item in media)]
    macro_items = [_dropdown_item(item) for item in macros]
    return ucapi.RequestUserInput(
        {"en": "Sources and off action", "de": "Quellen und Ausschaltaktion"},
        [
            {
                "id": "emby_entity_id",
                "label": {
                    "en": "Emby media entity (optional)",
                    "de": "Emby-Medien-Entity (optional)",
                },
                "field": {
                    "dropdown": {"value": current.emby_entity_id, "items": media_items}
                },
            },
            {
                "id": "shield_entity_id",
                "label": {
                    "en": "Nvidia Shield media entity",
                    "de": "Nvidia-Shield-Medien-Entity",
                },
                "field": {
                    "dropdown": {
                        "value": current.shield_entity_id,
                        "items": media_items,
                    }
                },
            },
            {
                "id": "target_entity_id",
                "label": {"en": "Macro to run at the end", "de": "Makro nach Ablauf"},
                "field": {
                    "dropdown": {
                        "value": current.target_entity_id,
                        "items": macro_items,
                    }
                },
            },
            {
                "id": "emby_url",
                "label": {
                    "en": "Emby Server URL (recommended)",
                    "de": "Emby-Server-URL (empfohlen)",
                },
                "field": {"text": {"value": current.emby_url}},
            },
            {
                "id": "emby_api_key",
                "label": {
                    "en": "Emby API key (leave blank to keep existing)",
                    "de": "Emby-API-Schlüssel (leer = vorhandenen behalten)",
                },
                "field": {"text": {"value": ""}},
            },
            {
                "id": "emby_device_filter",
                "label": {
                    "en": "Emby device name filter (optional)",
                    "de": "Emby-Gerätename als Filter (optional)",
                },
                "field": {"text": {"value": current.emby_device_filter}},
            },
        ],
    )


async def _finish(values: dict[str, str]) -> ucapi.SetupAction:
    if _store is None or _on_updated is None:
        return ucapi.SetupError()
    target = values.get("target_entity_id", "").strip()
    if not target:
        return ucapi.SetupError(error_type=ucapi.IntegrationSetupError.NOT_FOUND)
    current = _store.settings
    settings = Settings(
        core_url=_pending_url,
        core_api_key=_pending_key,
        target_entity_id=target,
        target_command_id="macro.start",
        emby_url=values.get("emby_url", "").strip(),
        emby_api_key=values.get("emby_api_key", "").strip() or current.emby_api_key,
        emby_device_filter=values.get("emby_device_filter", "").strip(),
        emby_entity_id=values.get("emby_entity_id", "").strip(),
        shield_entity_id=values.get("shield_entity_id", "").strip(),
    )
    if not _store.save(settings):
        return ucapi.SetupError()
    await _on_updated(settings)
    return ucapi.SetupComplete()


def _dropdown_item(entity: dict[str, Any]) -> dict[str, Any]:
    entity_id = str(entity.get("entity_id", ""))
    name = entity.get("name", {})
    if isinstance(name, dict):
        label = str(name.get("de") or name.get("en") or entity_id)
    else:
        label = str(name or entity_id)
    return {
        "id": entity_id,
        "label": {"de": f"{label} [{entity_id}]", "en": f"{label} [{entity_id}]"},
    }
