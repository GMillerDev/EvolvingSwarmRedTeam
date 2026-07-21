from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Iterable

from .normalization import clamp, normalize


DEFAULT_SCALES = {
    "p95_task_latency": 300.0,
    "deadlock_duration": 120.0,
    "task_starvation_count": 10.0,
    "negotiation_failure_count": 10.0,
    "recovery_loop_count": 10.0,
    "blocked_time_total": 600.0,
}

WEIGHTS = {
    "incomplete_task_ratio": 3.0,
    "p95_task_latency": 2.0,
    "deadlock_duration": 3.0,
    "task_starvation_count": 2.0,
    "negotiation_failure_count": 1.5,
    "recovery_loop_count": 1.5,
    "blocked_time_total": 1.0,
    "fleet_fragmentation_score": 1.0,
}


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


def calculate_metrics(
    events: Iterable[dict[str, Any]],
    *,
    simulation_runtime: float,
    wall_clock_runtime: float,
) -> dict[str, float]:
    materialized = sorted(events, key=lambda item: float(item.get("timestamp", 0)))
    submitted: dict[str, float] = {}
    completed: dict[str, float] = {}
    robot_idle: dict[str, float] = defaultdict(float)
    deadlock_durations: list[float] = []
    counters: dict[str, int] = defaultdict(int)
    blocked_total = 0.0

    for event in materialized:
        kind = str(event.get("event", ""))
        timestamp = float(event.get("timestamp", 0))
        task_id = event.get("task_id")
        if kind == "task_submitted" and task_id is not None:
            submitted.setdefault(str(task_id), timestamp)
        elif kind == "task_completed" and task_id is not None:
            completed.setdefault(str(task_id), timestamp)
        elif kind == "deadlock_end":
            deadlock_durations.append(float(event.get("duration", 0)))
        elif kind == "robot_blocked_end":
            blocked_total += float(event.get("duration", 0))
        elif kind == "robot_idle_interval":
            robot_idle[str(event["robot_id"])] += float(event.get("duration", 0))
        elif kind in {
            "task_starved",
            "negotiation_failure",
            "recovery_event",
            "recovery_loop",
            "robot_failure",
        }:
            counters[kind] += 1

    latencies = [completed[task] - started for task, started in submitted.items() if task in completed]
    task_count = len(submitted)
    complete_count = len(completed.keys() & submitted.keys())
    completion_ratio = complete_count / task_count if task_count else 0.0
    idle_values = list(robot_idle.values())
    metrics = {
        "tasks_submitted": float(task_count),
        "tasks_completed": float(complete_count),
        "tasks_incomplete": float(task_count - complete_count),
        "task_completion_ratio": completion_ratio,
        "incomplete_task_ratio": 1.0 - completion_ratio if task_count else 1.0,
        "mean_task_latency": statistics.fmean(latencies) if latencies else 0.0,
        "p95_task_latency": _percentile(latencies, 0.95),
        "maximum_task_latency": max(latencies, default=0.0),
        "deadlock_duration": sum(deadlock_durations),
        "number_of_deadlock_events": float(len(deadlock_durations)),
        "task_starvation_count": float(counters["task_starved"]),
        "negotiation_failure_count": float(counters["negotiation_failure"]),
        "recovery_event_count": float(counters["recovery_event"]),
        "recovery_loop_count": float(counters["recovery_loop"]),
        "robot_failure_count": float(counters["robot_failure"]),
        "fleet_fragmentation_score": 0.0,
        "robot_idle_time_mean": statistics.fmean(idle_values) if idle_values else 0.0,
        "robot_idle_time_variance": statistics.pvariance(idle_values) if idle_values else 0.0,
        "blocked_time_total": blocked_total,
        "simulation_runtime": simulation_runtime,
        "wall_clock_runtime": wall_clock_runtime,
    }
    return metrics


def calculate_fitness(
    metrics: dict[str, float],
    *,
    scales: dict[str, float] | None = None,
) -> dict[str, Any]:
    selected_scales = DEFAULT_SCALES | (scales or {})
    components = {
        "incomplete_task_ratio": clamp(metrics.get("incomplete_task_ratio", 0.0)),
        "p95_task_latency": normalize(metrics.get("p95_task_latency", 0.0), selected_scales["p95_task_latency"]),
        "deadlock_duration": normalize(metrics.get("deadlock_duration", 0.0), selected_scales["deadlock_duration"]),
        "task_starvation_count": normalize(metrics.get("task_starvation_count", 0.0), selected_scales["task_starvation_count"]),
        "negotiation_failure_count": normalize(metrics.get("negotiation_failure_count", 0.0), selected_scales["negotiation_failure_count"]),
        "recovery_loop_count": normalize(metrics.get("recovery_loop_count", 0.0), selected_scales["recovery_loop_count"]),
        "blocked_time_total": normalize(metrics.get("blocked_time_total", 0.0), selected_scales["blocked_time_total"]),
        "fleet_fragmentation_score": clamp(metrics.get("fleet_fragmentation_score", 0.0)),
    }
    raw_score = sum(WEIGHTS[name] * value for name, value in components.items())
    return {"score": clamp(raw_score, 0.0, 10.0), "raw_score": raw_score, "components": components}
