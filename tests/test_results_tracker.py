import unittest
from unittest.mock import patch

import mlb_results_tracker as tracker


class WorksheetNotFound(Exception):
    pass


class FakeWorksheet:
    def __init__(self, values=None):
        self.values = [list(row) for row in (values or [])]

    def get_all_values(self):
        return [list(row) for row in self.values]

    def row_values(self, row):
        return list(self.values[row - 1]) if row <= len(self.values) else []

    def col_values(self, column):
        return [row[column - 1] if len(row) >= column else "" for row in self.values]

    def append_rows(self, rows, value_input_option=None):
        self.values.extend([list(row) for row in rows])

    def update(self, values, range_name=None):
        if range_name and range_name.startswith("A1:"):
            if self.values:
                self.values[0] = list(values[0])
            else:
                self.values.append(list(values[0]))


class FakeWorkbook:
    def __init__(self, sheets):
        self.sheets = sheets

    def worksheet(self, title):
        if title not in self.sheets:
            raise WorksheetNotFound(title)
        return self.sheets[title]

    def add_worksheet(self, title, rows, cols):
        worksheet = FakeWorksheet()
        self.sheets[title] = worksheet
        return worksheet


def sample_feed(final=True, home_runs=1, plate_appearances=4):
    return {
        "gameData": {
            "status": {
                "abstractGameState": "Final" if final else "Live",
                "codedGameState": "F" if final else "I",
                "detailedState": "Final" if final else "In Progress",
            },
            "teams": {
                "away": {"abbreviation": "KC", "name": "Kansas City Royals"},
                "home": {"abbreviation": "LAD", "name": "Los Angeles Dodgers"},
            },
        },
        "liveData": {
            "linescore": {"teams": {"away": {"runs": 2}, "home": {"runs": 6}}},
            "boxscore": {
                "teams": {
                    "away": {"players": {}},
                    "home": {
                        "players": {
                            "ID660271": {
                                "person": {"id": 660271, "fullName": "Shohei Ohtani"},
                                "stats": {"batting": {"plateAppearances": plate_appearances, "homeRuns": home_runs}},
                            }
                        }
                    },
                }
            },
        },
    }


class ResultsTrackerUnitTest(unittest.TestCase):
    def test_final_score(self):
        away, home, away_runs, home_runs, winner = tracker.final_score(sample_feed())
        self.assertEqual((away, home, away_runs, home_runs, winner), ("KC", "LAD", 2, 6, "LAD"))

    def test_player_match_is_scoped_to_side(self):
        player = tracker.find_player_boxscore(sample_feed(), "Shohei Ohtani", "Home")
        self.assertEqual(player["person"]["id"], 660271)
        self.assertIsNone(tracker.find_player_boxscore(sample_feed(), "Shohei Ohtani", "Away"))

    def test_ids_are_deterministic(self):
        record = {
            "Date": "2026-08-10", "GamePk": "823918", "Player": "Shohei Ohtani",
            "Model Version": "Automated V16.2 - Eastern Slate Schedule Fix",
        }
        self.assertEqual(tracker.hr_prediction_id(record), tracker.hr_prediction_id(record))
        self.assertIn("823918", tracker.hr_prediction_id(record))

    def test_rank_tiers_match_production(self):
        self.assertEqual(tracker.tier_from_rank(3), "Primary")
        self.assertEqual(tracker.tier_from_rank(6), "Secondary")
        self.assertEqual(tracker.tier_from_rank(9), "Longshot")

    def test_feed_cache_fetches_each_game_once(self):
        cache = {}
        with patch.object(tracker, "fetch_game_feed", return_value=sample_feed()) as fetch:
            tracker.cached_feed(cache, "823918")
            tracker.cached_feed(cache, "823918")
        fetch.assert_called_once_with("823918")

    def test_snapshot_is_idempotent_and_uses_published_cards(self):
        workbook = FakeWorkbook({
            "Game Email Summary": FakeWorksheet([
                ["Schedule Date Used", "2026-08-10"],
            ]),
            "Game Picks": FakeWorksheet([
                ["Date", "Model Version", "Rank", "GamePk", "Game", "Venue", "Projected Winner", "Opponent", "Confidence", "Win Probability", "Expected Margin", "Away Team", "Home Team", "Away Projected Runs", "Home Projected Runs", "Verified"],
                ["2026-08-10", "Game Picks V2.1.1", "1", "823918", "KC @ LAD", "Dodger Stadium", "LAD", "KC", "Elite", "95.2", "3.8", "KC", "LAD", "2.9", "6.7", "Yes"],
            ]),
            "Email Summary": FakeWorksheet([
                ["Model Version", "Automated V16.2"],
                ["Schedule Date Used", "2026-08-10"],
            ]),
            "Model Results": FakeWorksheet([
                ["Date", "Model Version", "Rank", "Group", "Confidence", "Player", "Team", "Opponent", "Opposing Pitcher", "Venue", "GamePk", "HomeAway", "Score", "Season HR", "Last7HR", "HardHit%", "100+MPH%", "FlyBall%", "PitcherVulnerability", "ParkFactor", "WeatherScore"],
                ["2026-08-10", "Automated V16.2", "1", "Group 1", "Elite Target", "Shohei Ohtani", "LAD", "KC", "Noah Cameron", "Dodger Stadium", "823918", "Home", "81.2", "40", "3", "52", "31", "48", "65", "105", "57"],
            ]),
        })

        self.assertEqual(tracker.snapshot_game_picks(workbook, "2026-08-10"), 1)
        self.assertEqual(tracker.snapshot_hr_picks(workbook, "2026-08-10"), 1)
        self.assertEqual(tracker.snapshot_game_picks(workbook, "2026-08-10"), 0)
        self.assertEqual(tracker.snapshot_hr_picks(workbook, "2026-08-10"), 0)
        self.assertEqual(len(workbook.sheets[tracker.GAME_TRACKING_TAB].values), 2)
        self.assertEqual(len(workbook.sheets[tracker.HR_TRACKING_TAB].values), 2)


if __name__ == "__main__":
    unittest.main()
