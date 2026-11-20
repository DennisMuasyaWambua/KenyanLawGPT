"""Ranking metrics. A ranking is a list of doc_ids (best first, no duplicates);
``rel`` maps doc_id -> graded relevance (0 = not relevant, 1..3 = relevant)."""
from __future__ import annotations

import math
import random
from typing import Mapping, Sequence


def recall_at_k(ranking: Sequence[str], rel: Mapping[str, int], k: int) -> float:
    relevant = {d for d, g in rel.items() if g > 0}
    if not relevant:
        return 0.0
    return len(relevant & set(ranking[:k])) / len(relevant)


def precision_at_k(ranking: Sequence[str], rel: Mapping[str, int], k: int) -> float:
    if k <= 0:
        return 0.0
    return sum(1 for d in ranking[:k] if rel.get(d, 0) > 0) / k


def hit_at_k(ranking: Sequence[str], rel: Mapping[str, int], k: int) -> float:
    return 1.0 if any(rel.get(d, 0) > 0 for d in ranking[:k]) else 0.0


def mrr(ranking: Sequence[str], rel: Mapping[str, int], k: int = 10) -> float:
    for i, d in enumerate(ranking[:k], 1):
        if rel.get(d, 0) > 0:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranking: Sequence[str], rel: Mapping[str, int], k: int) -> float:
    def dcg(grades: Sequence[int]) -> float:
        return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades))

    ideal = sorted((g for g in rel.values() if g > 0), reverse=True)[:k]
    if not ideal:
        return 0.0
    return dcg([rel.get(d, 0) for d in ranking[:k]]) / dcg(ideal)


def per_query_metrics(ranking: Sequence[str], rel: Mapping[str, int], k: int = 10) -> dict[str, float]:
    return {
        f"recall@{k}": recall_at_k(ranking, rel, k),
        "recall@5": recall_at_k(ranking, rel, min(5, k)),
        f"precision@{k}": precision_at_k(ranking, rel, k),
        f"hit@{k}": hit_at_k(ranking, rel, k),
        f"mrr@{k}": mrr(ranking, rel, k),
        f"ndcg@{k}": ndcg_at_k(ranking, rel, k),
    }


def bootstrap_ci(values: Sequence[float], n_boot: int = 2000, alpha: float = 0.05,
                 seed: int = 0) -> tuple[float, float, float]:
    """(mean, lo, hi) percentile bootstrap CI over queries."""
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return (sum(values) / n, means[int(alpha / 2 * n_boot)], means[int((1 - alpha / 2) * n_boot) - 1])


def paired_bootstrap_diff(a: Sequence[float], b: Sequence[float], n_boot: int = 2000,
                          seed: int = 0) -> tuple[float, float, float, float]:
    """Paired comparison of system a vs b over the same queries.
    Returns (mean diff a-b, lo, hi, two-sided p ~ share of resamples crossing 0)."""
    assert len(a) == len(b), "paired samples must align"
    n = len(a)
    if n == 0:
        return 0.0, 0.0, 0.0, 1.0
    diffs = [x - y for x, y in zip(a, b)]
    rng = random.Random(seed)
    boots = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    mean = sum(diffs) / n
    below = sum(1 for m in boots if m <= 0) / n_boot
    above = sum(1 for m in boots if m >= 0) / n_boot
    return mean, boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1], min(1.0, 2 * min(below, above))
