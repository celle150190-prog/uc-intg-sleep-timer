"""Setup flow for the Sleep Timer integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import Any

import ucapi

from config import ConfigStore, Settings, TargetAction
from core_client import CoreApiError, CoreClient

_LOG = logging.getLogger(__name__)

_store: ConfigStore | None = None
_on_updated: Callable[[Settings], Awaitable[None]] | None = None
_pending_url = "http://127.0.0.1:8080"
_pending_key = ""
_pending_actions: dict[str, TargetAction] = {}
_MAX_TARGETS = 6
_TARGET_TYPES = "activity,light,macro,media_player,remote,switch"


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
                            "en": (
                                "Create a Remote Core API key. Power-capable devices "
                                "and macros can be selected during setup."
                            ),
                            "de": (
                                "Lege einen Remote-Core-API-Schlüssel an. Geräte mit "
                                "Ausschaltfunktion und Makros können im Setup gewählt werden."
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
    if "target_1" in values or "target_entity_id" in values:
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
                # The SDK redacts setup values whose id is password.
                "id": "password",
                "label": {
                    "en": "Core API key (required on first setup)",
                    "de": "Core-API-Schlüssel (beim ersten Setup erforderlich)",
                },
                "field": {"password": {"value": ""}},
            },
        ]
    )
    return ucapi.RequestUserInput(
        {"en": "Connect to Remote Core", "de": "Mit Remote Core verbinden"},
        fields,
    )


async def _load_entities(values: dict[str, str]) -> ucapi.SetupAction:
    global _pending_url, _pending_key, _pending_actions
    current = _store.settings if _store else Settings()
    _pending_url = values.get("core_url", "").strip()
    _pending_key = (
        values.get("password", "").strip()
        or values.get("core_api_key", "").strip()
        or current.core_api_key
    )
    if not _pending_url:
        return _credentials_screen("Die Remote-Core-URL ist erforderlich.")
    if not _pending_key:
        return _credentials_screen(
            "Beim ersten Setup ist ein Core-API-Schlüssel erforderlich."
        )
    client = CoreClient(_pending_url, _pending_key)
    try:
        entities = await client.list_entities(_TARGET_TYPES)
    except CoreApiError as error:
        if error.status_code in {401, 403}:
            return _credentials_screen("API-Schlüssel wurde abgelehnt.")
        return _credentials_screen(f"Remote Core nicht erreichbar: {error}")

    media = [item for item in entities if item.get("entity_type") == "media_player"]
    action_pairs = [
        (item, action)
        for item in entities
        if (action := _target_action(item)) is not None
    ]
    if not action_pairs:
        return _credentials_screen(
            "Es wurden keine Geräte mit Ausschaltfunktion und keine Makros gefunden."
        )
    _pending_actions = {action.entity_id: action for _, action in action_pairs}

    empty = {"id": "", "label": {"de": "Nicht verwenden", "en": "Do not use"}}
    media_items = [empty, *(_dropdown_item(item) for item in media)]
    target_items = [
        empty,
        *sorted(
            (_target_dropdown_item(item, action) for item, action in action_pairs),
            key=lambda item: str(item["label"]["de"]).casefold(),
        ),
    ]
    selected = [
        action.entity_id
        for action in current.resolved_target_actions()
        if action.entity_id in _pending_actions
    ]

    fields: list[dict[str, Any]] = [
        {
            "id": "target_info",
            "label": {"en": "Off actions", "de": "Ausschaltaktionen"},
            "field": {
                "label": {
                    "value": {
                        "en": (
                            "The active Remote activity is turned off first. "
                            "Then all selected actions are run in order."
                        ),
                        "de": (
                            "Zuerst wird die aktive Remote-Aktivität beendet. "
                            "Danach werden alle gewählten Aktionen ausgeführt."
                        ),
                    }
                }
            },
        },
        {
            "id": "turn_off_active_activity",
            "label": {
                "en": "Turn off active Remote activity",
                "de": "Aktive Remote-Aktivität beenden",
            },
            "field": {
                "dropdown": {
                    "value": "true" if current.turn_off_active_activity else "false",
                    "items": [
                        {
                            "id": "true",
                            "label": {"en": "Yes", "de": "Ja"},
                        },
                        {
                            "id": "false",
                            "label": {"en": "No", "de": "Nein"},
                        },
                    ],
                }
            },
        },
    ]
    for index in range(_MAX_TARGETS):
        fields.append(
            {
                "id": f"target_{index + 1}",
                "label": {
                    "en": f"Off target {index + 1}",
                    "de": f"Ausschaltziel {index + 1}",
                },
                "field": {
                    "dropdown": {
                        "value": selected[index] if index < len(selected) else "",
                        "items": target_items,
                    }
                },
            }
        )
    fields.extend(
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
                "id": "emby_url",
                "label": {
                    "en": "Emby Server URL (recommended)",
                    "de": "Emby-Server-URL (empfohlen)",
                },
                "field": {"text": {"value": current.emby_url}},
            },
            {
                # The SDK redacts setup values whose id is token.
                "id": "token",
                "label": {
                    "en": "Emby API key (leave blank to keep existing)",
                    "de": "Emby-API-Schlüssel (leer = vorhandenen behalten)",
                },
                "field": {"password": {"value": ""}},
            },
            {
                "id": "emby_device_filter",
                "label": {
                    "en": "Emby device name filter (optional)",
                    "de": "Emby-Gerätename als Filter (optional)",
                },
                "field": {"text": {"value": current.emby_device_filter}},
            },
        ]
    )
    return ucapi.RequestUserInput(
        {"en": "Sources and off actions", "de": "Quellen und Ausschaltaktionen"},
        fields,
    )


async def _finish(values: dict[str, str]) -> ucapi.SetupAction:
    if _store is None or _on_updated is None:
        return ucapi.SetupError()

    selected_ids = [
        values.get(f"target_{index}", "").strip()
        for index in range(1, _MAX_TARGETS + 1)
    ]
    # Accept the old setup payload during a rolling upgrade.
    legacy_target = values.get("target_entity_id", "").strip()
    if legacy_target and not any(selected_ids):
        selected_ids.append(legacy_target)

    actions: list[TargetAction] = []
    seen: set[str] = set()
    current = _store.settings
    current_actions = {
        action.entity_id: action for action in current.resolved_target_actions()
    }
    for entity_id in selected_ids:
        if not entity_id or entity_id in seen:
            continue
        action = _pending_actions.get(entity_id) or current_actions.get(entity_id)
        if action is None and entity_id == legacy_target:
            action = TargetAction(entity_id, "macro.start")
        if action is not None:
            seen.add(entity_id)
            actions.append(action)

    if not actions:
        return ucapi.SetupError(error_type=ucapi.IntegrationSetupError.NOT_FOUND)

    first = actions[0]
    settings = Settings(
        core_url=_pending_url,
        core_api_key=_pending_key,
        target_entity_id=first.entity_id,
        target_command_id=first.command_id,
        target_actions=actions,
        turn_off_active_activity=(
            values.get("turn_off_active_activity", "true").strip().casefold() != "false"
        ),
        emby_url=values.get("emby_url", "").strip(),
        emby_api_key=(
            values.get("token", "").strip()
            or values.get("emby_api_key", "").strip()
            or current.emby_api_key
        ),
        emby_device_filter=values.get("emby_device_filter", "").strip(),
        emby_entity_id=values.get("emby_entity_id", "").strip(),
        shield_entity_id=values.get("shield_entity_id", "").strip(),
        poll_interval=current.poll_interval,
        end_tolerance=current.end_tolerance,
        stopped_grace=current.stopped_grace,
        ui_schema_version=current.ui_schema_version,
    )
    if not _store.save(settings):
        return ucapi.SetupError()
    await _on_updated(settings)
    return ucapi.SetupComplete()


def _target_action(entity: dict[str, Any]) -> TargetAction | None:
    entity_id = str(entity.get("entity_id", "")).strip()
    entity_type = str(entity.get("entity_type", "")).strip()
    features = {
        str(feature).casefold() for feature in entity.get("features", []) if feature
    }
    if not entity_id:
        return None
    if entity_type == "macro":
        return TargetAction(entity_id, "macro.start", _entity_name(entity))
    if entity_type == "activity" and "on_off" in features:
        return TargetAction(entity_id, "activity.off", _entity_name(entity))
    if entity_type in {"light", "switch"}:
        return TargetAction(entity_id, f"{entity_type}.off", _entity_name(entity))
    if entity_type in {"media_player", "remote"} and "on_off" in features:
        return TargetAction(entity_id, f"{entity_type}.off", _entity_name(entity))
    return None


def _target_dropdown_item(
    entity: dict[str, Any], action: TargetAction
) -> dict[str, Any]:
    entity_type = str(entity.get("entity_type", ""))
    type_names = {
        "activity": ("Aktivität", "Activity"),
        "light": ("Licht", "Light"),
        "macro": ("Makro", "Macro"),
        "media_player": ("Mediengerät", "Media device"),
        "remote": ("Fernbedienung", "Remote"),
        "switch": ("Schalter", "Switch"),
    }
    type_de, type_en = type_names.get(entity_type, (entity_type, entity_type))
    name = action.name
    if not name or name == action.entity_id:
        suffix = action.entity_id[-8:]
        name = f"Unbenannt ({suffix})"
    if entity_type == "macro":
        de = f"{name} – {type_de} starten"
        en = f"{name} – start {type_en.lower()}"
    else:
        de = f"{name} – {type_de} ausschalten"
        en = f"{name} – turn off {type_en.lower()}"
    return {"id": action.entity_id, "label": {"de": de, "en": en}}


def _dropdown_item(entity: dict[str, Any]) -> dict[str, Any]:
    entity_id = str(entity.get("entity_id", ""))
    label = _entity_name(entity) or entity_id
    return {
        "id": entity_id,
        "label": {"de": f"{label} [{entity_id}]", "en": f"{label} [{entity_id}]"},
    }


def _entity_name(entity: dict[str, Any]) -> str:
    return _localized_text(entity.get("name"))


def _localized_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in ("de", "en", "value", "name"):
        if key in value:
            text = _localized_text(value[key])
            if text:
                return text
    for item in value.values():
        text = _localized_text(item)
        if text:
            return text
    return ""
