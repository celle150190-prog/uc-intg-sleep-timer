"""Tests for Remote Core entity and embedded UI handling."""

from __future__ import annotations

from unittest.mock import AsyncMock
import unittest

import httpx

from core_client import CoreApiError, CoreClient


def response(status: int, data: object) -> httpx.Response:
    """Create a minimal JSON response for the mocked Core client."""
    return httpx.Response(status, json=data)


class CoreClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_finds_full_configured_remote_id(self) -> None:
        client = CoreClient("http://remote", "key")
        client._request = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
            return_value=response(
                200,
                [
                    {
                        "entity_id": "sleep-timer.main.remote.sleep_timer",
                        "entity_type": "remote",
                    }
                ],
            )
        )

        entity_id = await client.find_configured_entity("remote.sleep_timer", "remote")

        self.assertEqual("sleep-timer.main.remote.sleep_timer", entity_id)

    async def test_updates_existing_embedded_page(self) -> None:
        client = CoreClient("http://remote", "key")
        client._request = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
            side_effect=[
                response(
                    200,
                    [{"page_id": "sleep_timer", "name": "Sleep Timer"}],
                ),
                response(200, {}),
            ]
        )
        page = {
            "page_id": "sleep_timer",
            "name": "Sleep Timer",
            "grid": {"width": 4, "height": 6},
            "items": [],
        }

        page_id = await client.upsert_remote_ui_page(
            "sleep-timer.main.remote.sleep_timer", page
        )

        self.assertEqual("sleep_timer", page_id)
        client._request.assert_awaited_with(  # noqa: SLF001
            "PATCH",
            "/api/remotes/sleep-timer.main.remote.sleep_timer/ui/pages/sleep_timer",
            json={
                "name": "Sleep Timer",
                "grid": {"width": 4, "height": 6},
                "items": [],
            },
        )

    async def test_lists_only_active_power_capable_activities(self) -> None:
        client = CoreClient("http://remote", "key")
        client._request = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
            side_effect=[
                response(200, []),
                response(
                    200,
                    [
                        {
                            "entity_id": "uc.main.activity.game-avr",
                            "entity_type": "activity",
                            "features": ["on_off"],
                            "attributes": {"state": "ON"},
                        },
                        {
                            "entity_id": "uc.main.activity.music",
                            "entity_type": "activity",
                            "features": ["on_off"],
                            "attributes": {"state": "OFF"},
                        },
                    ],
                ),
            ]
        )

        activities = await client.list_active_activities()

        self.assertEqual(
            ["uc.main.activity.game-avr"],
            [item["entity_id"] for item in activities],
        )

    async def test_uses_activity_group_live_state_for_internal_activity(self) -> None:
        client = CoreClient("http://remote", "key")
        client._request = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
            side_effect=[
                response(
                    200,
                    [
                        {
                            "group_id": "default",
                            "name": {"en": "Default"},
                            "activity_count": 2,
                            "state": "ACTIVE",
                        }
                    ],
                ),
                response(
                    200,
                    {
                        "group_id": "default",
                        "activities": [
                            {
                                "entity_id": "uc.main.activity.game-avr",
                                "state": "ON",
                            },
                            {
                                "entity_id": "uc.main.activity.music",
                                "state": "OFF",
                            },
                        ],
                    },
                ),
                response(200, []),
            ]
        )

        activities = await client.list_active_activities()

        self.assertEqual(
            ["uc.main.activity.game-avr"],
            [item["entity_id"] for item in activities],
        )
        self.assertEqual(
            "/api/activity_groups/default",
            client._request.await_args_list[1].args[1],  # noqa: SLF001
        )

    async def test_loads_activity_details_if_overview_has_no_state(self) -> None:
        client = CoreClient("http://remote", "key")
        client._request = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
            side_effect=[
                response(200, []),
                response(
                    200,
                    [
                        {
                            "entity_id": "uc.main.activity.game-avr",
                            "entity_type": "activity",
                            "features": ["on_off"],
                        }
                    ],
                ),
                response(
                    200,
                    {
                        "entity_id": "uc.main.activity.game-avr",
                        "entity_type": "activity",
                        "features": ["on_off"],
                        "attributes": {"state": "ON"},
                    },
                ),
            ]
        )

        activities = await client.list_active_activities()

        self.assertEqual(1, len(activities))
        client._request.assert_awaited_with(  # noqa: SLF001
            "GET",
            "/api/activities/uc.main.activity.game-avr",
        )

    async def test_turn_off_activity_waits_for_confirmed_off_state(self) -> None:
        client = CoreClient("http://remote", "key")
        client._request = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
            side_effect=[
                response(200, {}),
                response(
                    200,
                    {
                        "entity_id": "uc.main.activity.game-avr",
                        "attributes": {"state": "RUNNING"},
                    },
                ),
                response(
                    200,
                    {
                        "entity_id": "uc.main.activity.game-avr",
                        "attributes": {"state": "OFF"},
                    },
                ),
            ]
        )

        ended = await client.turn_off_activity(
            "uc.main.activity.game-avr", attempts=2, interval=0
        )

        self.assertTrue(ended)
        self.assertEqual(3, client._request.await_count)  # noqa: SLF001

    async def test_turn_off_activity_rejects_unconfirmed_state(self) -> None:
        client = CoreClient("http://remote", "key")
        client._request = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
            side_effect=[
                response(200, {}),
                response(
                    200,
                    {
                        "entity_id": "uc.main.activity.game-avr",
                        "attributes": {"state": "ON"},
                    },
                ),
            ]
        )

        ended = await client.turn_off_activity(
            "uc.main.activity.game-avr", attempts=1, interval=0
        )

        self.assertFalse(ended)

    async def test_retries_short_command_on_older_core(self) -> None:
        client = CoreClient("http://remote", "key")
        client._request = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
            side_effect=[
                CoreApiError("unsupported command", 422),
                response(200, {}),
            ]
        )

        await client.execute("denon.main.media_player.zone1", "media_player.off")

        self.assertEqual(
            [
                (
                    "PUT",
                    "/api/entities/denon.main.media_player.zone1/command",
                ),
                (
                    "PUT",
                    "/api/entities/denon.main.media_player.zone1/command",
                ),
            ],
            [
                (call.args[0], call.args[1])
                for call in client._request.await_args_list  # noqa: SLF001
            ],
        )
        self.assertEqual(
            [{"cmd_id": "media_player.off"}, {"cmd_id": "off"}],
            [
                call.kwargs["json"]
                for call in client._request.await_args_list  # noqa: SLF001
            ],
        )


if __name__ == "__main__":
    unittest.main()
