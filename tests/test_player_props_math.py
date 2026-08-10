import unittest

from player_props_math import (
    binomial_tail,
    choose_dynamic_milestone,
    compound_total_bases_tail,
    parse_baseball_innings,
    poisson_tail,
    prop_strength_score,
    select_limited_indices,
)


class PlayerPropsMathTest(unittest.TestCase):
    def test_poisson_tail_decreases_with_threshold(self):
        self.assertGreater(poisson_tail(6.5, 6), poisson_tail(6.5, 8))

    def test_binomial_tail_known_case(self):
        self.assertAlmostEqual(binomial_tail(4, 0.25, 1), 1 - 0.75 ** 4, places=8)

    def test_total_bases_distribution(self):
        probability = compound_total_bases_tail(4, 0.18, 0.05, 0.01, 0.05, 2)
        self.assertGreater(probability, 0)
        self.assertLess(probability, 1)

    def test_dynamic_milestone_chooses_highest_supported(self):
        result = choose_dynamic_milestone(
            {1: 0.70, 2: 0.32, 3: 0.08},
            {1: 0.60, 2: 0.28, 3: 0.10},
        )
        self.assertEqual(result[0], 2)

    def test_baseball_innings_parser(self):
        self.assertAlmostEqual(parse_baseball_innings("6.2"), 6 + 2 / 3)

    def test_report_card_exposure_limits(self):
        rows = [
            {"Player ID": 100 + (rank % 4), "GamePk": 200 + (rank % 3)}
            for rank in range(12)
        ]
        selected = select_limited_indices(rows)
        chosen = [rows[index] for index in selected]
        for player_id in {row["Player ID"] for row in chosen}:
            self.assertLessEqual(sum(row["Player ID"] == player_id for row in chosen), 2)
        for game_pk in {row["GamePk"] for row in chosen}:
            self.assertLessEqual(sum(row["GamePk"] == game_pk for row in chosen), 3)

    def test_cross_category_score_does_not_overweight_total_bases(self):
        total_bases = prop_strength_score(0.311, 0.24, 4, 3.0)
        two_hits = prop_strength_score(0.38, 0.32, 2, 4.0)
        self.assertLess(abs(total_bases - two_hits), 4.0)

    def test_more_reliable_prop_scores_higher_at_same_gate(self):
        self.assertGreater(
            prop_strength_score(0.50, 0.38, 1, 3.0),
            prop_strength_score(0.42, 0.38, 1, 3.0),
        )


if __name__ == "__main__":
    unittest.main()
