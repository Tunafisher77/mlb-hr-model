import unittest

from best_card_math import composite_stack_score, select_distinct_props, top_complete_stacks
from run_daily_mlb_best_card import build_stacks, rows_as_records


class BestCardMathTest(unittest.TestCase):
    def test_composite_weights(self):
        self.assertAlmostEqual(composite_stack_score(80, 70, 75, 65), 73.5)

    def test_props_are_distinct_and_exclude_hr_hitter(self):
        hr = {"Player ID": "1", "Player": "HR Player"}
        props = [
            {"Player ID": "1", "Player": "HR Player", "Prop Score": 99},
            {"Player ID": "2", "Player": "Prop A", "Prop Score": 80},
            {"Player ID": "2", "Player": "Prop A", "Prop Score": 79},
            {"Player ID": "3", "Player": "Prop B", "Prop Score": 78},
        ]
        selected = select_distinct_props(props, hr)
        self.assertEqual([row["Player ID"] for row in selected], ["2", "3"])

    def test_published_props_are_preferred_before_extended_fallbacks(self):
        props = [
            {"Player": "Extended A", "Prop Score": 95, "Prop Candidate Source": "Extended Player Prop"},
            {"Player": "Published A", "Prop Score": 80, "Prop Candidate Source": "Published Player Prop"},
            {"Player": "Published B", "Prop Score": 79, "Prop Candidate Source": "Published Player Prop"},
        ]
        selected = select_distinct_props(props, {"Player": "HR Player"})
        self.assertEqual([row["Player"] for row in selected], ["Published A", "Published B"])

    def test_extended_prop_completes_stack_when_only_one_published_prop_exists(self):
        props = [
            {"Player": "Published A", "Prop Score": 80, "Prop Candidate Source": "Published Player Prop"},
            {"Player": "Extended A", "Prop Score": 78, "Prop Candidate Source": "Extended Player Prop"},
        ]
        selected = select_distinct_props(props, {"Player": "HR Player"})
        self.assertEqual([row["Player"] for row in selected], ["Published A", "Extended A"])

    def test_only_complete_stacks_are_ranked(self):
        stacks = [
            {"GamePk": "1", "Complete": True, "Stack Score": 75, "Win Probability": 80, "HR Score": 70},
            {"GamePk": "2", "Complete": False, "Stack Score": 99, "Win Probability": 99, "HR Score": 99},
            {"GamePk": "3", "Complete": True, "Stack Score": 78, "Win Probability": 79, "HR Score": 72},
        ]
        self.assertEqual([row["GamePk"] for row in top_complete_stacks(stacks)], ["3", "1"])

    def test_duplicate_headers_keep_first_populated_value(self):
        values = [
            ["Player", "Score", "Score"],
            ["Junior Caminero", "72.76", ""],
        ]
        self.assertEqual(rows_as_records(values)[0]["Score"], "72.76")


    def test_thin_slate_uses_distinct_complete_alternate_stack(self):
        games = [
            {"GamePk": "1", "Game": "A @ B", "Rank": "1", "Win Probability": "75", "Projected Winner": "B"},
            {"GamePk": "2", "Game": "C @ D", "Rank": "2", "Win Probability": "72", "Projected Winner": "D"},
        ]
        hrs = [
            {"GamePk": "1", "Player": "HR A", "Player ID": "10", "Rank": "1", "Score": "80", "HR Candidate Source": "Published HR Target"},
            {"GamePk": "1", "Player": "HR B", "Player ID": "11", "Rank": "4", "Score": "74", "HR Candidate Source": "Published HR Target"},
            {"GamePk": "2", "Player": "HR C", "Player ID": "20", "Rank": "2", "Score": "78", "HR Candidate Source": "Published HR Target"},
        ]
        props = []
        for game_pk, offset in (("1", 100), ("2", 200)):
            for index, score in enumerate((82, 79, 76), start=1):
                props.append({
                    "GamePk": game_pk, "Player": f"Prop {game_pk}-{index}",
                    "Player ID": str(offset + index), "Prediction ID": f"p-{game_pk}-{index}",
                    "Prop Type": "Hits", "Prop Score": score, "Projected Probability": score,
                    "Prop Candidate Source": "Published Player Prop",
                })

        card, _ = build_stacks(games, hrs, props)

        self.assertEqual(len(card), 3)
        self.assertEqual(len({row["Prediction ID"] for row in card}), 3)
        self.assertTrue(any("Emergency alternate" in row["Selection Notes"] for row in card))


if __name__ == "__main__":
    unittest.main()
