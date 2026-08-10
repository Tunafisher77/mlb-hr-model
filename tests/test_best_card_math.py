import unittest

from best_card_math import composite_stack_score, select_distinct_props, top_complete_stacks
from run_daily_mlb_best_card import rows_as_records


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


if __name__ == "__main__":
    unittest.main()
