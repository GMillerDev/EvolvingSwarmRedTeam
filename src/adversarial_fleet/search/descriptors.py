from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable

from adversarial_fleet.metrics.normalization import clamp

from .config import DescriptorConfig
from .evaluation import (
    CONTINUOUS_DESCRIPTOR_FIELDS,
    BehaviorDescriptor,
    CandidateEvaluation,
)


def _available(value: float | None, name: str, mask: set[str]) -> float | None:
    if value is not None:
        mask.add(name)
    return value


def _active_time_imbalance(events: tuple[dict[str, object], ...]) -> float | None:
    samples: dict[str, int] = defaultdict(int)
    observed_robots: set[str] = set()
    for event in events:
        if event.get("event") != "robot_state" or event.get("robot_id") is None:
            continue
        robot_id = str(event["robot_id"])
        observed_robots.add(robot_id)
        if bool(event.get("task_active")):
            samples[robot_id] += 1
    if len(observed_robots) < 2:
        return None
    values = [samples[robot_id] for robot_id in sorted(observed_robots)]
    maximum = max(values)
    return 0.0 if maximum == 0 else (maximum - min(values)) / maximum


def build_behavior_descriptor(
    evaluation: CandidateEvaluation,
    *,
    config: DescriptorConfig,
    mission_timeout_seconds: float,
    robot_count: int,
) -> BehaviorDescriptor:
    if mission_timeout_seconds <= 0:
        raise ValueError("mission_timeout_seconds must be positive")
    metrics = evaluation.metrics
    mask: set[str] = set()

    def metric_ratio(name: str, scale: float) -> float | None:
        value = metrics.get(name)
        return None if value is None else clamp(float(value) / scale)

    incomplete = metrics.get("incomplete_task_ratio")
    onset = (
        1.0
        if evaluation.failure_onset_seconds is None
        else clamp(evaluation.failure_onset_seconds / mission_timeout_seconds)
    )
    affected = (
        None
        if robot_count <= 0 or not evaluation.affected_robot_data_available
        else clamp(len(set(evaluation.affected_robot_ids)) / robot_count)
    )
    imbalance = _active_time_imbalance(evaluation.events)
    values = {
        "incomplete_task_ratio": _available(
            None if incomplete is None else clamp(float(incomplete)),
            "incomplete_task_ratio",
            mask,
        ),
        "p95_latency_ratio": _available(
            metric_ratio("p95_task_latency", config.latency_scale),
            "p95_latency_ratio",
            mask,
        ),
        "failure_onset_ratio": _available(onset, "failure_onset_ratio", mask),
        "deadlock_duration_ratio": _available(
            metric_ratio("deadlock_duration", config.deadlock_scale),
            "deadlock_duration_ratio",
            mask,
        ),
        "starvation_ratio": _available(
            metric_ratio("task_starvation_count", config.starvation_scale),
            "starvation_ratio",
            mask,
        ),
        "blocked_time_ratio": _available(
            metric_ratio("blocked_time_total", config.blocked_time_scale),
            "blocked_time_ratio",
            mask,
        ),
        "affected_robot_fraction": _available(
            affected,
            "affected_robot_fraction",
            mask,
        ),
        "task_active_imbalance": _available(
            imbalance,
            "task_active_imbalance",
            mask,
        ),
        "recovery_ratio": _available(
            metric_ratio("recovery_event_count", config.recovery_scale),
            "recovery_ratio",
            mask,
        ),
        "negotiation_failure_ratio": _available(
            metric_ratio(
                "negotiation_failure_count",
                config.negotiation_failure_scale,
            ),
            "negotiation_failure_ratio",
            mask,
        ),
    }
    return BehaviorDescriptor(
        failure_mechanism=evaluation.failure_mechanism,
        mission_result=evaluation.mission_result,
        availability_mask=frozenset(mask),
        **values,
    )


def aggregate_descriptors(
    descriptors: Iterable[BehaviorDescriptor],
) -> BehaviorDescriptor:
    materialized = tuple(descriptors)
    if not materialized:
        raise ValueError("at least one behavior descriptor is required")

    def modal(values: Iterable[str]) -> str:
        counts: dict[str, int] = defaultdict(int)
        for value in values:
            counts[value] += 1
        return min(counts, key=lambda value: (-counts[value], value))

    mechanism_value = modal(item.failure_mechanism.value for item in materialized)
    mission_result = modal(item.mission_result for item in materialized)
    minimum_presence = len(materialized) // 2 + 1
    mask: set[str] = set()
    continuous: dict[str, float | None] = {}
    for name in CONTINUOUS_DESCRIPTOR_FIELDS:
        values = [
            float(value) for item in materialized if (value := getattr(item, name)) is not None
        ]
        if len(values) >= minimum_presence:
            continuous[name] = statistics.median(values)
            mask.add(name)
        else:
            continuous[name] = None
    return BehaviorDescriptor(
        failure_mechanism=mechanism_value,
        mission_result=mission_result,
        availability_mask=frozenset(mask),
        **continuous,
    )


def behavior_distance(
    left: BehaviorDescriptor,
    right: BehaviorDescriptor,
    *,
    config: DescriptorConfig,
) -> float:
    categorical = (
        int(left.failure_mechanism != right.failure_mechanism)
        + int(left.mission_result != right.mission_result)
    ) / 2
    common = left.availability_mask & right.availability_mask
    feature_weights = dict(config.continuous_feature_weights)
    continuous_weight_total = sum(feature_weights[name] for name in common)
    continuous = (
        sum(
            feature_weights[name] * abs(float(getattr(left, name)) - float(getattr(right, name)))
            for name in common
        )
        / continuous_weight_total
        if common
        else 0.0
    )
    all_fields = frozenset(CONTINUOUS_DESCRIPTOR_FIELDS)
    mask_mismatch = len(left.availability_mask ^ right.availability_mask) / len(all_fields)
    total_weight = config.categorical_weight + config.continuous_weight + config.mask_weight
    return clamp(
        (
            config.categorical_weight * categorical
            + config.continuous_weight * continuous
            + config.mask_weight * mask_mismatch
        )
        / total_weight
    )


def novelty_score(
    target: BehaviorDescriptor,
    neighbors: Iterable[BehaviorDescriptor],
    *,
    config: DescriptorConfig,
) -> float:
    distances = sorted(behavior_distance(target, neighbor, config=config) for neighbor in neighbors)
    if not distances:
        return 0.0
    return statistics.fmean(distances[: config.novelty_k])
