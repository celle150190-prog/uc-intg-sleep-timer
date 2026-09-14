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
