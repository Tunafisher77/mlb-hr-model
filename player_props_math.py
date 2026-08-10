"""Pure statistical helpers for the MLB Player Props model."""

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Mapping


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def poisson_tail(mean: float, threshold: int) -> float:
    """P(X >= threshold) for a Poisson random variable."""
    mean = max(0.0, float(mean))
    threshold = int(threshold)
    if threshold <= 0:
        return 1.0
    term = math.exp(-mean)
    cumulative = term
    for value in range(1, threshold):
        term *= mean / value
        cumulative += term
    return clamp(1.0 - cumulative, 0.0, 1.0)


def binomial_tail(trials: int, probability: float, threshold: int) -> float:
    """P(X >= threshold) for a Binomial random variable."""
    trials = max(0, int(trials))
    threshold = int(threshold)
    probability = clamp(probability, 0.0, 1.0)
    if threshold <= 0:
        return 1.0
    if threshold > trials:
        return 0.0
    total = 0.0
    for successes in range(threshold, trials + 1):
        total += (
            math.comb(trials, successes)
            * probability ** successes
            * (1.0 - probability) ** (trials - successes)
        )
    return clamp(total, 0.0, 1.0)


def compound_total_bases_tail(
    trials: int,
    single_probability: float,
    double_probability: float,
    triple_probability: float,
    home_run_probability: float,
    threshold: int,
) -> float:
    """Exact total-bases tail probability from independent AB outcomes."""
    trials = max(0, int(trials))
    threshold = int(threshold)
    probabilities = [
        max(0.0, 1.0 - single_probability - double_probability - triple_probability - home_run_probability),
        max(0.0, single_probability),
        max(0.0, double_probability),
        max(0.0, triple_probability),
        max(0.0, home_run_probability),
    ]
    scale = sum(probabilities)
    probabilities = [value / scale for value in probabilities]
    distribution = [1.0]
    for _ in range(trials):
        next_distribution = [0.0] * (len(distribution) + 4)
        for current_bases, current_probability in enumerate(distribution):
            for added_bases, outcome_probability in enumerate(probabilities):
                next_distribution[current_bases + added_bases] += current_probability * outcome_probability
        distribution = next_distribution
    return clamp(sum(distribution[threshold:]), 0.0, 1.0)


def choose_dynamic_milestone(
    probabilities: dict[int, float],
    probability_gates: dict[int, float],
) -> tuple[int, float, float] | None:
    """Choose the highest milestone whose modeled probability clears its gate."""
    eligible = []
    for threshold, probability in probabilities.items():
        gate = probability_gates.get(int(threshold))
        if gate is not None and probability >= gate:
            eligible.append((int(threshold), float(probability), float(gate)))
    if not eligible:
        return None
    return max(eligible, key=lambda item: item[0])


def prop_strength_score(probability: float, gate: float, threshold: int, difficulty_step: float) -> float:
    """Comparable score after category-specific probability gates normalize difficulty."""
    clearance = max(0.0, probability - gate)
    score = 62.0 + clearance * 110.0 + max(0, threshold - 1) * difficulty_step
    return round(clamp(score, 0.0, 99.0), 2)


def parse_baseball_innings(value) -> float:
    """Convert MLB's 6.1/6.2 notation to 6 1/3 or 6 2/3 innings."""
    text = str(value or "0").strip()
    if "." not in text:
        try:
            return float(text)
        except ValueError:
            return 0.0
    whole, fraction = text.split(".", 1)
    try:
        innings = int(whole)
    except ValueError:
        return 0.0
    outs = int(fraction[:1]) if fraction[:1].isdigit() else 0
    if outs not in {0, 1, 2}:
        outs = 0
    return innings + outs / 3.0


def normalized_outcome_probabilities(counts: Iterable[float], pseudo_counts: Iterable[float]) -> list[float]:
    observed = [max(0.0, float(value)) for value in counts]
    priors = [max(0.0, float(value)) for value in pseudo_counts]
    if len(observed) != len(priors):
        raise ValueError("counts and pseudo_counts must have the same length")
    combined = [left + right for left, right in zip(observed, priors)]
    total = sum(combined)
    if total <= 0:
        return [1.0 / len(combined)] * len(combined)
    return [value / total for value in combined]


def select_limited_indices(
    rows: Iterable[Mapping[str, object]],
    player_limit: int = 2,
    game_limit: int = 3,
    total_limit: int = 20,
) -> list[int]:
    """Select ranked row positions while enforcing player and game exposure limits."""
    selected = []
    player_counts = Counter()
    game_counts = Counter()
    for index, row in enumerate(rows):
        player_key = str(row.get("Player ID", ""))
        game_key = str(row.get("GamePk", ""))
        if player_counts[player_key] >= player_limit or game_counts[game_key] >= game_limit:
            continue
        selected.append(index)
        player_counts[player_key] += 1
        game_counts[game_key] += 1
        if len(selected) >= total_limit:
            break
    return selected
