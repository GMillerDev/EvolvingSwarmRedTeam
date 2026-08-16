from __future__ import annotations

import hashlib
import math
import random
import statistics
from collections.abc import Callable, Iterable
from typing import Literal

from pydantic import Field

from adversarial_fleet.search.models import SearchModel


MetricDirection = Literal["higher", "lower"]


class StatisticalSummary(SearchModel):
    count: int = Field(ge=1)
    minimum: float
    percentile_25: float
    median: float
    percentile_75: float
    maximum: float
    mean: float
    confidence_level: float = Field(gt=0, lt=1)
    confidence_interval_lower: float
    confidence_interval_upper: float


class MetricAggregate(SearchModel):
    algorithm: str
    budget_checkpoint: int = Field(ge=1)
    metric: str
    direction: MetricDirection
    summary: StatisticalSummary
    censored_count: int = Field(default=0, ge=0)


class PairedComparison(SearchModel):
    algorithm: str
    baseline_algorithm: str
    budget_checkpoint: int = Field(ge=1)
    metric: str
    direction: MetricDirection
    pair_count: int = Field(ge=1)
    median_difference: float
    mean_difference: float
    confidence_level: float = Field(gt=0, lt=1)
    confidence_interval_lower: float
    confidence_interval_upper: float
    wins: int = Field(ge=0)
    ties: int = Field(ge=0)
    losses: int = Field(ge=0)


def percentile(values: Iterable[float], probability: float) -> float:
    materialized = sorted(values)
    if not materialized:
        raise ValueError("percentile requires at least one value")
    rank = (len(materialized) - 1) * probability
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return materialized[lower]
    fraction = rank - lower
    return materialized[lower] * (1.0 - fraction) + materialized[upper] * fraction


def _stable_seed(seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{seed}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def bootstrap_confidence_interval(
    values: Iterable[float],
    *,
    confidence_level: float,
    resamples: int,
    seed: int,
    statistic: Callable[[list[float]], float] = statistics.median,
) -> tuple[float, float]:
    materialized = list(values)
    if not materialized:
        raise ValueError("bootstrap requires at least one value")
    if len(materialized) == 1:
        return materialized[0], materialized[0]
    rng = random.Random(seed)
    sampled = [
        statistic([rng.choice(materialized) for _ in materialized]) for _ in range(resamples)
    ]
    tail = (1.0 - confidence_level) / 2.0
    return percentile(sampled, tail), percentile(sampled, 1.0 - tail)


def summarize(
    values: Iterable[float],
    *,
    confidence_level: float,
    resamples: int,
    seed: int,
) -> StatisticalSummary:
    materialized = list(values)
    if not materialized:
        raise ValueError("statistical summary requires at least one value")
    lower, upper = bootstrap_confidence_interval(
        materialized,
        confidence_level=confidence_level,
        resamples=resamples,
        seed=seed,
    )
    return StatisticalSummary(
        count=len(materialized),
        minimum=min(materialized),
        percentile_25=percentile(materialized, 0.25),
        median=statistics.median(materialized),
        percentile_75=percentile(materialized, 0.75),
        maximum=max(materialized),
        mean=statistics.fmean(materialized),
        confidence_level=confidence_level,
        confidence_interval_lower=lower,
        confidence_interval_upper=upper,
    )


def paired_comparison(
    *,
    algorithm: str,
    baseline_algorithm: str,
    budget_checkpoint: int,
    metric: str,
    direction: MetricDirection,
    algorithm_values: dict[int, float],
    baseline_values: dict[int, float],
    confidence_level: float,
    resamples: int,
    seed: int,
) -> PairedComparison:
    common_seeds = sorted(set(algorithm_values) & set(baseline_values))
    if not common_seeds:
        raise ValueError("paired comparison requires at least one common search seed")
    differences = [
        algorithm_values[search_seed] - baseline_values[search_seed] for search_seed in common_seeds
    ]
    lower, upper = bootstrap_confidence_interval(
        differences,
        confidence_level=confidence_level,
        resamples=resamples,
        seed=_stable_seed(seed, f"{algorithm}:{budget_checkpoint}:{metric}"),
    )
    tolerance = 1e-12
    signed = differences if direction == "higher" else [-item for item in differences]
    wins = sum(item > tolerance for item in signed)
    losses = sum(item < -tolerance for item in signed)
    ties = len(signed) - wins - losses
    return PairedComparison(
        algorithm=algorithm,
        baseline_algorithm=baseline_algorithm,
        budget_checkpoint=budget_checkpoint,
        metric=metric,
        direction=direction,
        pair_count=len(differences),
        median_difference=statistics.median(differences),
        mean_difference=statistics.fmean(differences),
        confidence_level=confidence_level,
        confidence_interval_lower=lower,
        confidence_interval_upper=upper,
        wins=wins,
        ties=ties,
        losses=losses,
    )


def summary_seed(analysis_seed: int, *, algorithm: str, checkpoint: int, metric: str) -> int:
    return _stable_seed(analysis_seed, f"{algorithm}:{checkpoint}:{metric}")
