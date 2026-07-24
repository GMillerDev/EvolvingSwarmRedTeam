from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Iterable

from .config import ConfirmationConfig, DescriptorConfig, GenomeBounds
from .descriptors import aggregate_descriptors, build_behavior_descriptor
from .evaluation import (
    AggregateEvaluation,
    CandidateEvaluation,
    EvaluationState,
    FailureMechanism,
    ReproducibilitySummary,
    SeverityStatistics,
)
from .models import AdversarialGenome


DEFAULT_METRIC_TOLERANCES = {
    "severity_score": {"absolute": 0.5},
    "p95_task_latency": {"absolute": 10.0, "relative": 0.20},
    "deadlock_duration": {"absolute": 2.0},
    "tasks_completed": {"absolute": 0.0},
    "tasks_incomplete": {"absolute": 0.0},
}


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def calculate_complexity(genome: AdversarialGenome, bounds: GenomeBounds) -> float:
    workload = genome.workload
    total_waypoints = sum(len(route) for route in workload.patrol_routes)
    maximum_total_waypoints = bounds.route_count_max * bounds.route_length_max
    return min(
        1.0,
        0.50 * workload.task_count / bounds.task_count_max
        + 0.25 * total_waypoints / maximum_total_waypoints
        + 0.25 * len(workload.patrol_routes) / bounds.route_count_max,
    )


def _completion_bucket(metrics: dict[str, float]) -> str:
    submitted = max(0.0, float(metrics.get("tasks_submitted", 0.0)))
    completed = max(0.0, float(metrics.get("tasks_completed", 0.0)))
    if submitted <= 0:
        return "none"
    ratio = min(1.0, completed / submitted)
    if ratio == 1:
        return "all"
    if ratio <= 0.25:
        return "low"
    if ratio <= 0.75:
        return "medium"
    return "high"


def _modal_signature(
    evaluations: tuple[CandidateEvaluation, ...],
) -> tuple[tuple[str, str, str] | None, float]:
    if not evaluations:
        return None, 0.0
    signatures = [
        (
            item.mission_result,
            item.failure_mechanism.value,
            _completion_bucket(item.metrics),
        )
        for item in evaluations
    ]
    counts = Counter(signatures)
    modal = min(counts, key=lambda signature: (-counts[signature], signature))
    return modal, counts[modal] / len(evaluations)


def _within_tolerance(
    values: list[float],
    *,
    absolute: float,
    relative: float = 0.0,
) -> bool:
    if len(values) < 2:
        return True
    reference = statistics.median(values)
    tolerance = max(absolute, relative * max(abs(reference), 1e-9))
    return max(abs(value - reference) for value in values) <= tolerance


def calculate_reproducibility(
    runs: Iterable[CandidateEvaluation],
    *,
    metric_tolerances: dict[str, dict[str, float]] | None = None,
) -> ReproducibilitySummary:
    materialized = tuple(runs)
    valid = tuple(item for item in materialized if item.state.is_valid_run)
    signature, score = _modal_signature(valid)
    tolerances = DEFAULT_METRIC_TOLERANCES | (metric_tolerances or {})
    agreement: dict[str, bool] = {}
    for metric, tolerance in tolerances.items():
        if metric == "severity_score":
            values = [item.severity_score for item in valid]
        else:
            values = [float(item.metrics[metric]) for item in valid if metric in item.metrics]
        agreement[metric] = len(values) == len(valid) and _within_tolerance(
            values,
            absolute=float(tolerance.get("absolute", 0.0)),
            relative=float(tolerance.get("relative", 0.0)),
        )
    return ReproducibilitySummary(
        score=score,
        modal_signature=signature,
        valid_run_count=len(valid),
        total_run_count=len(materialized),
        continuous_metric_agreement=agreement,
    )


def aggregate_candidate_evaluations(
    genome: AdversarialGenome,
    runs: Iterable[CandidateEvaluation],
    *,
    bounds: GenomeBounds,
    descriptor_config: DescriptorConfig,
    confirmation_config: ConfirmationConfig,
    mission_timeout_seconds: float,
    robot_count: int,
) -> AggregateEvaluation:
    materialized = tuple(runs)
    if not materialized:
        raise ValueError("at least one candidate evaluation is required")
    if any(item.candidate_id != genome.digest() for item in materialized):
        raise ValueError("all candidate evaluations must belong to the supplied genome")

    valid = tuple(item for item in materialized if item.state.is_valid_run)
    severities = [item.severity_score for item in valid]
    severity = SeverityStatistics(
        minimum=min(severities, default=0.0),
        maximum=max(severities, default=0.0),
        mean=statistics.fmean(severities) if severities else 0.0,
        median=statistics.median(severities) if severities else 0.0,
        standard_deviation=statistics.pstdev(severities) if len(severities) > 1 else 0.0,
        percentile_25=_percentile(severities, 0.25),
    )
    reproducibility = calculate_reproducibility(materialized)
    descriptors = [
        build_behavior_descriptor(
            item,
            config=descriptor_config,
            mission_timeout_seconds=mission_timeout_seconds,
            robot_count=robot_count,
        )
        for item in valid
    ]
    if descriptors:
        descriptor = aggregate_descriptors(descriptors)
    else:
        descriptor = build_behavior_descriptor(
            materialized[0],
            config=descriptor_config,
            mission_timeout_seconds=mission_timeout_seconds,
            robot_count=robot_count,
        )
    cleanup_failure = any(item.state == EvaluationState.CLEANUP_FAILURE for item in materialized)
    qualifies = descriptor.failure_mechanism != FailureMechanism.NONE
    archive_eligible = (
        len(valid) >= confirmation_config.minimum_valid_runs
        and reproducibility.score >= confirmation_config.reproducibility_threshold
        and not cleanup_failure
        and qualifies
    )
    return AggregateEvaluation(
        candidate_id=genome.digest(),
        genome=genome,
        runs=materialized,
        severity=severity,
        robust_severity=severity.median,
        reproducibility=reproducibility,
        descriptor=descriptor,
        complexity=calculate_complexity(genome, bounds),
        archive_eligible=archive_eligible,
        unstable=qualifies and not archive_eligible,
        shared_severity=severity.median,
    )


def should_confirm(
    screening: CandidateEvaluation,
    *,
    confirmation_config: ConfirmationConfig,
) -> bool:
    if confirmation_config.confirm_all:
        return True
    return (
        screening.state in {EvaluationState.VALID_FAILURE, EvaluationState.VALID_TIMEOUT}
        or screening.failure_mechanism != FailureMechanism.NONE
        or screening.metrics.get("incomplete_task_ratio", 0.0) > 0
    )
