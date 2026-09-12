"""Tests for normalized playback state."""

import unittest

from models import PlaybackSnapshot


class PlaybackSnapshotTest(unittest.TestCase):
    def test_item_id_is_preferred_identity(self):
        item = PlaybackSnapshot("Emby", "4711", "Episode", "PLAYING", 10, 100)
        self.assertEqual("id:4711", item.identity)
        self.assertEqual(90, item.remaining)

    def test_generic_streaming_app_is_not_an_item_identity(self):
        item = PlaybackSnapshot("Netflix", "", "Netflix", "PLAYING")
        self.assertEqual("", item.identity)

    def test_specific_title_can_identify_item(self):
        item = PlaybackSnapshot("Netflix", "", "My series – Episode 4", "PLAYING")
        self.assertEqual("title:my series – episode 4", item.identity)


if __name__ == "__main__":
    unittest.main()
