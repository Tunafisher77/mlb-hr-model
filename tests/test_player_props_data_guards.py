import unittest

from player_props_math import stats_splits


class PlayerPropsDataGuardTest(unittest.TestCase):
    def test_stats_splits_tolerates_missing_and_empty_stats(self):
        self.assertEqual(stats_splits({}), [])
        self.assertEqual(stats_splits({"stats": []}), [])
        self.assertEqual(stats_splits({"stats": [{}]}), [])

    def test_stats_splits_returns_first_stats_block(self):
        splits = [{"stat": {"gamesStarted": 4}}]
        self.assertEqual(stats_splits({"stats": [{"splits": splits}]}), splits)


if __name__ == "__main__":
    unittest.main()
