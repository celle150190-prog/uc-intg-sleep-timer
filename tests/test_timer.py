"""Tests for the timer state machine."""

import unittest

from config import Settings, TargetAction
from models import PlaybackSnapshot, TimerMode
from timer import TimerController


class FakeClient:
    def __init__(self, failing_entities=None):
        self.calls = []
        self.failing_entities = set(failing_entities or [])

    async def execute(self, entity_id, command_id):
        self.calls.append((entity_id, command_id))
        if entity_id in self.failing_entities:
            raise RuntimeError("simulated failure")


class FakeResolver:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)

    async def current(self):
        if not self.snapshots:
            return None
        return self.snapshots.pop(0)


class TimerControllerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.views = []
        self.settings = Settings(
            core_api_key="key",
            target_entity_id="uc.main.macro.off",
            stopped_grace=0,
        )
        self.timer = TimerController(self.settings, self.views.append)
        self.client = FakeClient()
        self.timer._client = self.client

    async def asyncTearDown(self):
        await self.timer.stop()

    async def test_fixed_timer_can_be_triggered(self):
        self.assertTrue(await self.timer.set_minutes(15))
        self.assertEqual(TimerMode.DEADLINE, self.timer.view.mode)
        self.assertTrue(await self.timer.trigger_now())
        self.assertEqual(
            [("uc.main.macro.off", "macro.start")],
            self.client.calls,
        )
        self.assertEqual(TimerMode.OFF, self.timer.view.mode)

    async def test_all_targets_are_attempted_if_one_fails(self):
        settings = Settings(
            core_api_key="key",
            target_actions=[
                TargetAction("tv.main.media_player.tv", "media_player.off"),
                TargetAction("denon.main.media_player.zone1", "media_player.off"),
            ],
        )
        timer = TimerController(settings, self.views.append)
        client = FakeClient({"tv.main.media_player.tv"})
        timer._client = client

        self.assertFalse(await timer.trigger_now())

        self.assertEqual(
            [
                ("tv.main.media_player.tv", "media_player.off"),
                ("denon.main.media_player.zone1", "media_player.off"),
            ],
            client.calls,
        )
        self.assertIn("1 von 2", timer.view.status)

    async def test_watch_fires_when_item_changes(self):
        first = PlaybackSnapshot("Emby", "one", "Episode 1", "PLAYING", 100, 120)
        second = PlaybackSnapshot("Emby", "two", "Episode 2", "PLAYING", 0, 120)
        self.timer._resolver = FakeResolver([first, second])
        self.assertTrue(await self.timer.arm_current())
        async with self.timer._lock:
            await self.timer._poll_current_locked()
        self.assertEqual(1, len(self.client.calls))
        self.assertEqual(TimerMode.OFF, self.timer.view.mode)

    async def test_watch_rejects_app_only_metadata(self):
        item = PlaybackSnapshot("Netflix", "", "Netflix", "PLAYING")
        self.timer._resolver = FakeResolver([item])
        self.assertFalse(await self.timer.arm_current())
        self.assertIn("keine Enddaten", self.timer.view.status)

    async def test_watch_fires_near_end(self):
        first = PlaybackSnapshot("Prime Video", "", "Episode 1", "PLAYING", 100, 120)
        last = PlaybackSnapshot("Prime Video", "", "Episode 1", "PLAYING", 116, 120)
        self.timer._resolver = FakeResolver([first, last])
        self.assertTrue(await self.timer.arm_current())
        async with self.timer._lock:
            await self.timer._poll_current_locked()
        self.assertEqual(1, len(self.client.calls))


if __name__ == "__main__":
    unittest.main()
