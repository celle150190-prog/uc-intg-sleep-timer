"""Tests for configuration migration and target handling."""

import unittest

from config import Settings, TargetAction


class SettingsTest(unittest.TestCase):
    def test_migrates_legacy_single_macro(self) -> None:
        settings = Settings.from_dict(
            {
                "target_entity_id": "uc.main.macro.off",
                "target_command_id": "macro.start",
            }
        )

        self.assertEqual(
            [TargetAction("uc.main.macro.off", "macro.start")],
            settings.resolved_target_actions(),
        )
        self.assertTrue(settings.turn_off_active_activity)

    def test_deduplicates_target_actions(self) -> None:
        settings = Settings(
            target_actions=[
                TargetAction("tv.main.media_player.tv", "media_player.off"),
                TargetAction("tv.main.media_player.tv", "media_player.off"),
            ]
        )

        self.assertEqual(1, len(settings.resolved_target_actions()))


if __name__ == "__main__":
    unittest.main()
