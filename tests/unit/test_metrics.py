from __future__ import annotations

import pytest

from adversarial_fleet.metrics import calculate_fitness, calculate_metrics, calculate_severity


def test_metrics_and_fitness() -> None:
    events = [
        {"timestamp": 0.0, "event": "task_submitted", "task_id": "a"},
        {"timestamp": 5.0, "event": "task_submitted", "task_id": "b"},
        {"timestamp": 20.0, "event": "task_completed", "task_id": "a"},
        {"timestamp": 31.0, "event": "robot_blocked_end", "duration": 11.0},
    ]
    metrics = calculate_metrics(events, simulation_runtime=31, wall_clock_runtime=2)
    assert metrics["task_completion_ratio"] == 0.5
    assert metrics["incomplete_task_ratio"] == 0.5
    assert metrics["mean_task_latency"] == 20.0
    assert metrics["blocked_time_total"] == 11.0
    fitness = calculate_fitness(metrics)
    assert fitness["score"] == pytest.approx(1.6516666667)
    severity = calculate_severity(metrics)
    assert severity["severity_score"] == fitness["score"]
    assert severity["raw_severity_score"] == fitness["raw_score"]
    assert severity["components"] == fitness["components"]


def test_fitness_is_clamped() -> None:
    metrics = {
        "incomplete_task_ratio": 1,
        "p95_task_latency": 10000,
        "deadlock_duration": 10000,
        "task_starvation_count": 100,
        "negotiation_failure_count": 100,
        "recovery_loop_count": 100,
        "blocked_time_total": 10000,
        "fleet_fragmentation_score": 1,
    }
    assert calculate_fitness(metrics)["score"] == 10.0
