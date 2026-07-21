from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

from .models import FailureReport, FailureType


def detect_deadlock(
    events: Iterable[dict[str, Any]],
    *,
    minimum_robots: int = 2,
    movement_threshold_meters: float = 0.10,
    deadlock_timeout_seconds: float = 30.0,
) -> FailureReport | None:
    observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("event") == "robot_state" and event.get("task_active"):
            observations[str(event["robot_id"])].append(event)

    blocked: list[str] = []
    durations: dict[str, float] = {}
    for robot_id, samples in observations.items():
        samples.sort(key=lambda item: float(item["timestamp"]))
        if len(samples) < 2:
            continue
        latest = samples[-1]
        cutoff = float(latest["timestamp"]) - deadlock_timeout_seconds
        window = [sample for sample in samples if float(sample["timestamp"]) >= cutoff]
        if len(window) < 2:
            continue
        duration = float(window[-1]["timestamp"]) - float(window[0]["timestamp"])
        displacement = math.hypot(
            float(window[-1]["x"]) - float(window[0]["x"]),
            float(window[-1]["y"]) - float(window[0]["y"]),
        )
        if duration >= deadlock_timeout_seconds and displacement <= movement_threshold_meters:
            blocked.append(robot_id)
            durations[robot_id] = duration

    if len(blocked) < minimum_robots:
        return None
    duration = min(durations.values())
    severity = min(1.0, 0.4 + 0.1 * len(blocked) + duration / 300.0)
    return FailureReport(
        is_failure=True,
        failure_type=FailureType.DEADLOCK,
        severity=severity,
        confidence=0.85,
        evidence={"blocked_robots": sorted(blocked), "blocked_duration_seconds": duration},
    )

