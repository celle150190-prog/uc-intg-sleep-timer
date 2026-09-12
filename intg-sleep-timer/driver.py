#!/usr/bin/env python3
"""Unfolded Circle Remote Two/3 Sleep Timer integration."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
import logging
import math
import os
from typing import Any

import ucapi
from ucapi import remote, sensor
from ucapi.ui import Size, UiPage, create_ui_text

from config import ConfigStore, Settings
from core_client import CoreApiError, CoreClient
from models import TimerMode, TimerView
import setup_flow
from timer import TimerController

_LOG = logging.getLogger("driver")
_LOOP = asyncio.get_event_loop()
api = ucapi.IntegrationAPI(_LOOP)

REMOTE_ID = "remote.sleep_timer"
STATUS_ID = "sensor.sleep_timer_status"
REMAINING_ID = "sensor.sleep_timer_remaining"

COMMANDS = [
    "TIMER_15",
    "TIMER_30",
    "TIMER_45",
    "TIMER_60",
    "TIMER_90",
    "TIMER_120",
    "AFTER_CURRENT",
    "ADD_15",
    "SUBTRACT_15",
    "CANCEL",
    "RUN_NOW",
]
EMBEDDED_UI_VERSION = 1

_store: ConfigStore | None = None
_controller: TimerController | None = None
_ui_sync_task: asyncio.Task[None] | None = None


def _ui_pages() -> list[UiPage]:
    page = UiPage("sleep_timer", "Sleep Timer", grid=Size(4, 6))
    for column, (text, command) in enumerate(
        [
            ("15 min", "TIMER_15"),
            ("30 min", "TIMER_30"),
            ("45 min", "TIMER_45"),
            ("60 min", "TIMER_60"),
        ]
    ):
        page.add(create_ui_text(text, column, 0, cmd=command))
    for column, (text, command) in enumerate(
        [
            ("90 min", "TIMER_90"),
            ("120 min", "TIMER_120"),
            ("+15", "ADD_15"),
            ("−15", "SUBTRACT_15"),
        ]
    ):
        page.add(create_ui_text(text, column, 1, cmd=command))
    page.add(
        create_ui_text("Nach aktuellem Element", 0, 3, Size(4, 1), "AFTER_CURRENT")
    )
    page.add(create_ui_text("Abbrechen", 0, 5, Size(2, 1), "CANCEL"))
    page.add(create_ui_text("Jetzt aus", 2, 5, Size(2, 1), "RUN_NOW"))
    return [page]


def _without_none(value: Any) -> Any:
    """Remove optional null fields before sending a UI definition to Core REST."""
    if isinstance(value, dict):
        return {
            key: _without_none(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    return value


def _ui_page_payload() -> dict[str, Any]:
    """Return the embedded page as a Core-API compatible JSON object."""
    return _without_none(asdict(_ui_pages()[0]))


async def command_handler(
    _entity: ucapi.Remote,
    cmd_id: str,
    params: dict[str, Any] | None,
    websocket: Any,
) -> ucapi.StatusCodes:
    """Process commands from the Remote UI, macros, and activities."""
    del websocket
    if _controller is None:
        return ucapi.StatusCodes.SERVICE_UNAVAILABLE
    if cmd_id == remote.Commands.SEND_CMD and params:
        cmd_id = str(params.get("command", ""))
    fixed = {
        "TIMER_15": 15,
        "TIMER_30": 30,
        "TIMER_45": 45,
        "TIMER_60": 60,
        "TIMER_90": 90,
        "TIMER_120": 120,
    }
    if cmd_id in fixed:
        return (
            ucapi.StatusCodes.OK
            if await _controller.set_minutes(fixed[cmd_id])
            else ucapi.StatusCodes.BAD_REQUEST
        )
    if cmd_id == "ADD_15":
        return (
            ucapi.StatusCodes.OK
            if await _controller.add_minutes(15)
            else ucapi.StatusCodes.BAD_REQUEST
        )
    if cmd_id == "SUBTRACT_15":
        return (
            ucapi.StatusCodes.OK
            if await _controller.add_minutes(-15)
            else ucapi.StatusCodes.CONFLICT
        )
    if cmd_id == "AFTER_CURRENT":
        return (
            ucapi.StatusCodes.OK
            if await _controller.arm_current()
            else ucapi.StatusCodes.CONFLICT
        )
    if cmd_id == "CANCEL":
        await _controller.cancel()
        return ucapi.StatusCodes.OK
    if cmd_id == "RUN_NOW":
        return (
            ucapi.StatusCodes.OK
            if await _controller.trigger_now()
            else ucapi.StatusCodes.SERVER_ERROR
        )
    return ucapi.StatusCodes.BAD_REQUEST


def _register_entities() -> None:
    for entity_id in (REMOTE_ID, STATUS_ID, REMAINING_ID):
        api.available_entities.remove(entity_id)
    current = _controller.view if _controller else TimerView()
    timer_remote = ucapi.Remote(
        REMOTE_ID,
        {"en": "Sleep Timer", "de": "Sleep Timer"},
        [remote.Features.SEND_CMD],
        {
            remote.Attributes.STATE: remote.States.ON
            if current.mode != TimerMode.OFF
            else remote.States.OFF
        },
        simple_commands=COMMANDS,
        ui_pages=_ui_pages(),
        icon="uc:bed",
        description={
            "en": "Run an off macro after a delay or after the current media item.",
            "de": "Führt ein Ausschalt-Makro nach Zeit oder nach dem aktuellen Medienelement aus.",
        },
        cmd_handler=command_handler,
    )
    status = ucapi.Sensor(
        STATUS_ID,
        {"en": "Sleep Timer status", "de": "Sleep-Timer-Status"},
        [],
        {
            sensor.Attributes.STATE: sensor.States.ON,
            sensor.Attributes.VALUE: current.status,
        },
        device_class=sensor.DeviceClasses.CUSTOM,
        icon="uc:info",
    )
    remaining = ucapi.Sensor(
        REMAINING_ID,
        {"en": "Sleep Timer remaining", "de": "Sleep-Timer-Restzeit"},
        [],
        {
            sensor.Attributes.STATE: sensor.States.ON,
            sensor.Attributes.VALUE: _remaining_minutes(current),
            sensor.Attributes.UNIT: "min",
        },
        device_class=sensor.DeviceClasses.CUSTOM,
        options={sensor.Options.CUSTOM_UNIT: "min", sensor.Options.DECIMALS: 0},
        icon="uc:timer",
    )
    for entity in (timer_remote, status, remaining):
        api.available_entities.add(entity)


def _remaining_minutes(view: TimerView) -> int:
    return (
        math.ceil(view.remaining_seconds / 60)
        if view.remaining_seconds is not None
        else 0
    )


def _update_attributes(entity_id: str, attributes: dict[str, Any]) -> None:
    available = api.available_entities.get(entity_id)
    if available:
        available.attributes.update(attributes)
    api.configured_entities.update_attributes(entity_id, attributes)


def on_timer_view(view: TimerView) -> None:
    """Publish timer changes to configured Remote entities."""
    _update_attributes(
        REMOTE_ID,
        {
            remote.Attributes.STATE: remote.States.ON
            if view.mode != TimerMode.OFF
            else remote.States.OFF
        },
    )
    detail = view.status
    if view.source:
        title = view.title or "Wiedergabe"
        detail = f"{view.source}: {title} – {view.status}"
    _update_attributes(
        STATUS_ID,
        {sensor.Attributes.STATE: sensor.States.ON, sensor.Attributes.VALUE: detail},
    )
    _update_attributes(
        REMAINING_ID,
        {
            sensor.Attributes.STATE: sensor.States.ON,
            sensor.Attributes.VALUE: _remaining_minutes(view),
            sensor.Attributes.UNIT: "min",
        },
    )


async def apply_settings(settings: Settings) -> None:
    """Replace the active controller after setup or reconfiguration."""
    global _controller
    if _controller:
        await _controller.stop()
    _controller = TimerController(settings, on_timer_view)
    _controller.start()
    _register_entities()
    await api.set_device_state(ucapi.DeviceStates.CONNECTED)


@api.listens_to(ucapi.Events.CONNECT)
async def on_connect() -> None:
    await api.set_device_state(ucapi.DeviceStates.CONNECTED)


@api.listens_to(ucapi.Events.SUBSCRIBE_ENTITIES)
async def on_subscribe(entity_ids: list[str]) -> None:
    # The SDK dispatches this event as the named argument ``entity_ids``.
    # Keep the exact parameter name or the listener wrapper drops the value and
    # calls this handler without arguments, which closes the Core WebSocket.
    if _controller:
        on_timer_view(_controller.view)
    if REMOTE_ID in entity_ids:
        _schedule_embedded_ui_sync()


def _schedule_embedded_ui_sync() -> None:
    """Schedule the one-time UI migration without delaying entity subscription."""
    global _ui_sync_task
    if _ui_sync_task and not _ui_sync_task.done():
        return
    _ui_sync_task = asyncio.create_task(_sync_embedded_ui())


async def _sync_embedded_ui() -> None:
    """Install the integration-provided page in an already configured entity."""
    if _store is None or _store.settings.ui_schema_version >= EMBEDDED_UI_VERSION:
        return
    settings = _store.settings
    client = CoreClient(settings.core_url, settings.core_api_key)
    try:
        entity_id = await client.find_configured_entity(REMOTE_ID, "remote")
        await client.upsert_remote_ui_page(entity_id, _ui_page_payload())
    except CoreApiError as error:
        _LOG.warning("Embedded Sleep Timer UI could not be synchronized: %s", error)
        return

    updated = replace(settings, ui_schema_version=EMBEDDED_UI_VERSION)
    if _store.save(updated):
        _LOG.info("Embedded Sleep Timer UI version %s installed", EMBEDDED_UI_VERSION)
    else:
        _LOG.error(
            "Embedded Sleep Timer UI was installed but migration state was not saved"
        )


async def main() -> None:
    """Initialize and run the integration."""
    global _store
    _configure_logging()
    _store = ConfigStore(api.config_dir_path)
    setup_flow.initialize(_store, apply_settings)
    await api.init("driver.json", setup_flow.driver_setup_handler)
    api._driver_info["setup_data_schema"] = setup_flow.setup_data_schema()  # noqa: SLF001
    if _store.settings.core_api_key and _store.settings.target_entity_id:
        await apply_settings(_store.settings)


def _configure_logging() -> None:
    level = os.getenv("UC_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    # ucapi 0.7.0 forces this logger to DEBUG and logs complete setup payloads.
    # Keep it at INFO so credentials never appear in exported integration logs.
    logging.getLogger("ucapi.api").setLevel(logging.INFO)


if __name__ == "__main__":
    _LOOP.run_until_complete(main())
    _LOOP.run_forever()
