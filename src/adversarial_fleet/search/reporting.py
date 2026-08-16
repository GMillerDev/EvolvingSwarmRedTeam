from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable

from pydantic import Field

from .archives import MapElitesArchive, MapElitesArchiveReport, map_elites_niche
from .config import MapElitesConfig
from .evaluation import AggregateEvaluation, EvaluationState
from .models import SearchModel


class DistributionSummary(SearchModel):
    minimum: float
    percentile_25: float
    median: float
    percentile_75: float
    maximum: float
    mean: float


class GenerationDiagnostics(SearchModel):
    generation: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    confirmed_failure_count: int = Field(ge=0)
    failure_mechanism_counts: dict[str, int]
    best_robust_severity: float = Field(ge=0, le=10)
    mean_novelty: float = Field(ge=0, le=1)
    mean_complexity: float = Field(ge=0, le=1)
    unique_behavior_count: int = Field(ge=0)
    cumulative_map_cells: int = Field(ge=0)
    cumulative_quality_diversity_score: float = Field(ge=0)
    mechanism_entropy: float = Field(ge=0, le=1)


class SearchMeasures(SearchModel):
    candidate_count: int = Field(ge=0)
    realization_evaluation_count: int = Field(ge=0)
    executed_realization_count: int = Field(ge=0)
    cache_hit_count: int = Field(ge=0)
    first_qualified_failure_candidate: int | None = Field(default=None, ge=1)
    best_robust_severity: float = Field(ge=0, le=10)
    confirmed_failure_count: int = Field(ge=0)
    unique_confirmed_behavior_count: int = Field(ge=0)
    unique_failure_mechanisms: tuple[str, ...]
    failure_mechanism_counts: dict[str, int]
    posthoc_map_elites: MapElitesArchiveReport
    novelty_archive_size: int = Field(ge=0)
    behavioral_evenness: float = Field(ge=0, le=1)
    reproducibility: DistributionSummary
    elite_complexity: DistributionSummary
    infrastructure_failure_count: int = Field(ge=0)
    cleanup_failure_count: int = Field(ge=0)
    orphan_process_count: int = Field(ge=0)
    simulation_runtime_seconds: float = Field(ge=0)
    wall_clock_runtime_seconds: float = Field(ge=0)
    mechanism_dominance_ratio: float = Field(ge=0, le=1)
    objective_correlations: dict[str, float | None]
    genome_observed_ranges: dict[str, tuple[float, float] | None]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def distribution(values: Iterable[float]) -> DistributionSummary:
    materialized = list(values)
    return DistributionSummary(
        minimum=min(materialized, default=0.0),
        percentile_25=_percentile(materialized, 0.25),
        median=statistics.median(materialized) if materialized else 0.0,
        percentile_75=_percentile(materialized, 0.75),
        maximum=max(materialized, default=0.0),
        mean=statistics.fmean(materialized) if materialized else 0.0,
    )


def _descriptor_hash(evaluation: AggregateEvaluation) -> str:
    canonical = json.dumps(
        evaluation.descriptor.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total <= 0 or len(counts) <= 1:
        return 0.0
    entropy = -sum(
        (count / total) * math.log(count / total) for count in counts.values() if count > 0
    )
    return entropy / math.log(len(counts))


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_sum = sum((value - left_mean) ** 2 for value in left)
    right_sum = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_sum * right_sum)
    if denominator == 0:
        return None
    return numerator / denominator


def _objective_correlations(
    evaluations: tuple[AggregateEvaluation, ...],
) -> dict[str, float | None]:
    objectives = {
        "severity": [item.robust_severity for item in evaluations],
        "novelty": [item.novelty_score for item in evaluations],
        "reproducibility": [item.reproducibility.score for item in evaluations],
        "complexity": [item.complexity for item in evaluations],
    }
    output: dict[str, float | None] = {}
    names = tuple(objectives)
    for index, left_name in enumerate(names):
        for right_name in names[index + 1 :]:
            output[f"{left_name}__{right_name}"] = _pearson(
                objectives[left_name],
                objectives[right_name],
            )
    return output


def _observed_genome_ranges(
    evaluations: tuple[AggregateEvaluation, ...],
) -> dict[str, tuple[float, float] | None]:
    values: dict[str, list[float]] = {
        "task_count": [],
        "arrival_interval_seconds": [],
        "priority_skew": [],
        "route_count": [],
        "total_route_waypoints": [],
    }
    for evaluation in evaluations:
        workload = evaluation.genome.workload
        values["task_count"].append(float(workload.task_count))
        values["arrival_interval_seconds"].append(workload.arrival_interval_seconds)
        values["priority_skew"].append(workload.priority_skew)
        values["route_count"].append(float(len(workload.patrol_routes)))
        values["total_route_waypoints"].append(
            float(sum(len(route) for route in workload.patrol_routes))
        )
    return {
        name: None if not observed else (min(observed), max(observed))
        for name, observed in values.items()
    }


def posthoc_map_archive(
    evaluations: Iterable[AggregateEvaluation],
    *,
    robot_count: int,
    map_config: MapElitesConfig,
) -> MapElitesArchive:
    archive = MapElitesArchive(robot_count=robot_count, config=map_config)
    for evaluation in evaluations:
        archive.consider(evaluation)
    return archive


def generation_diagnostics(
    generation: int,
    evaluations: Iterable[AggregateEvaluation],
    *,
    cumulative_evaluations: Iterable[AggregateEvaluation],
    robot_count: int,
    map_config: MapElitesConfig,
) -> GenerationDiagnostics:
    batch = tuple(evaluations)
    cumulative = tuple(cumulative_evaluations)
    eligible = tuple(item for item in batch if item.archive_eligible)
    mechanism_counts = Counter(item.descriptor.failure_mechanism.value for item in eligible)
    cumulative_archive = posthoc_map_archive(
        cumulative,
        robot_count=robot_count,
        map_config=map_config,
    ).report()
    return GenerationDiagnostics(
        generation=generation,
        candidate_count=len(batch),
        confirmed_failure_count=len(eligible),
        failure_mechanism_counts=dict(sorted(mechanism_counts.items())),
        best_robust_severity=max(
            (item.robust_severity for item in batch),
            default=0.0,
        ),
        mean_novelty=statistics.fmean(item.novelty_score for item in batch) if batch else 0.0,
        mean_complexity=statistics.fmean(item.complexity for item in batch) if batch else 0.0,
        unique_behavior_count=len({_descriptor_hash(item) for item in batch}),
        cumulative_map_cells=cumulative_archive.occupied_cell_count,
        cumulative_quality_diversity_score=cumulative_archive.quality_diversity_score,
        mechanism_entropy=_normalized_entropy(mechanism_counts),
    )


def calculate_search_measures(
    evaluations: Iterable[AggregateEvaluation],
    *,
    robot_count: int,
    map_config: MapElitesConfig,
    cache_hit_count: int,
    wall_clock_runtime_seconds: float,
) -> SearchMeasures:
    materialized = tuple(evaluations)
    eligible = tuple(item for item in materialized if item.archive_eligible)
    mechanism_counts = Counter(item.descriptor.failure_mechanism.value for item in eligible)
    niche_counts = Counter(
        map_elites_niche(
            item,
            robot_count=robot_count,
            config=map_config,
        ).key
        for item in eligible
    )
    archive = posthoc_map_archive(
        materialized,
        robot_count=robot_count,
        map_config=map_config,
    )
    archive_report = archive.report()
    first_failure = next(
        (index for index, item in enumerate(materialized, 1) if item.archive_eligible),
        None,
    )
    all_runs = tuple(run for item in materialized for run in item.runs)
    infrastructure_count = sum(
        run.state
        in {
            EvaluationState.INFRASTRUCTURE_FAILURE,
            EvaluationState.INVALID_GENOME,
        }
        for run in all_runs
    )
    cleanup_count = sum(run.state == EvaluationState.CLEANUP_FAILURE for run in all_runs)
    elite_complexities = [item.complexity for item in archive.elites.values()]
    executed_runs = max(0, len(all_runs) - cache_hit_count)
    dominance_ratio = (
        max(mechanism_counts.values()) / sum(mechanism_counts.values()) if mechanism_counts else 0.0
    )
    return SearchMeasures(
        candidate_count=len(materialized),
        realization_evaluation_count=len(all_runs),
        executed_realization_count=executed_runs,
        cache_hit_count=cache_hit_count,
        first_qualified_failure_candidate=first_failure,
        best_robust_severity=max(
            (item.robust_severity for item in materialized),
            default=0.0,
        ),
        confirmed_failure_count=len(eligible),
        unique_confirmed_behavior_count=len({_descriptor_hash(item) for item in eligible}),
        unique_failure_mechanisms=tuple(sorted(mechanism_counts)),
        failure_mechanism_counts=dict(sorted(mechanism_counts.items())),
        posthoc_map_elites=archive_report,
        novelty_archive_size=len({_descriptor_hash(item) for item in materialized}),
        behavioral_evenness=_normalized_entropy(niche_counts),
        reproducibility=distribution(item.reproducibility.score for item in materialized),
        elite_complexity=distribution(elite_complexities),
        infrastructure_failure_count=infrastructure_count,
        cleanup_failure_count=cleanup_count,
        orphan_process_count=sum(run.orphan_process_count for run in all_runs),
        simulation_runtime_seconds=sum(
            run.metrics.get("simulation_runtime", 0.0) for run in all_runs
        ),
        wall_clock_runtime_seconds=wall_clock_runtime_seconds,
        mechanism_dominance_ratio=dominance_ratio,
        objective_correlations=_objective_correlations(materialized),
        genome_observed_ranges=_observed_genome_ranges(materialized),
    )
