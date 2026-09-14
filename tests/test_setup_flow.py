"""Tests for setup target discovery."""

import unittest

import setup_flow


class SetupTargetTest(unittest.TestCase):
    def test_builds_media_player_off_action(self) -> None:
        action = setup_flow._target_action(  # noqa: SLF001
            {
                "entity_id": "denon.main.media_player.zone1",
                "entity_type": "media_player",
                "features": ["on_off", "volume"],
                "name": {"de": "Denon Wohnzimmer"},
            }
        )

        self.assertIsNotNone(action)
        self.assertEqual("media_player.off", action.command_id)
        self.assertEqual("Denon Wohnzimmer", action.name)

    def test_ignores_media_player_without_power_feature(self) -> None:
        action = setup_flow._target_action(  # noqa: SLF001
            {
                "entity_id": "player.main.media_player.now_playing",
                "entity_type": "media_player",
                "features": ["play_pause"],
            }
        )

        self.assertIsNone(action)

    def test_builds_macro_start_action_and_reads_nested_name(self) -> None:
        action = setup_flow._target_action(  # noqa: SLF001
            {
                "entity_id": "uc.main.macro.everything-off",
                "entity_type": "macro",
                "features": ["start"],
                "name": {"value": {"de": "Alles aus"}},
            }
        )

        self.assertIsNotNone(action)
        self.assertEqual("macro.start", action.command_id)
        self.assertEqual("Alles aus", action.name)


if __name__ == "__main__":
    unittest.main()
