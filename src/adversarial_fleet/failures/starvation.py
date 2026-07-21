from __future__ import annotations

from typing import Any, Iterable

from .models import FailureReport, FailureType


def detect_starvation(
    events: Iterable[dict[str, Any]],
    *,
    threshold_seconds: float = 120,
    minimum_newer_tasks_completed: int = 2,
) -> FailureReport | None:
    ordered = sorted(events, key=lambda item: float(item.get("timestamp", 0)))
    submitted: dict[str, float] = {}
    completed: dict[str, float] = {}
    for event in ordered:
        task_id = event.get("task_id")
        if task_id is None:
            continue
        if event.get("event") == "task_submitted":
            submitted.setdefault(str(task_id), float(event["timestamp"]))
        elif event.get("event") == "task_completed":
            completed.setdefault(str(task_id), float(event["timestamp"]))
    end_time = max((float(event.get("timestamp", 0)) for event in ordered), default=0.0)
    starved: list[str] = []
    for task_id, start in submitted.items():
        if task_id in completed or end_time - start < threshold_seconds:
            continue
        newer_completed = sum(
            1 for newer_id, newer_start in submitted.items()
            if newer_start > start and newer_id in completed
        )
        if newer_completed >= minimum_newer_tasks_completed:
            starved.append(task_id)
    if not starved:
        return None
    return FailureReport(
        is_failure=True,
        failure_type=FailureType.TASK_STARVATION,
        severity=min(1.0, 0.5 + 0.1 * len(starved)),
        confidence=0.8,
        evidence={"starved_tasks": sorted(starved), "threshold_seconds": threshold_seconds},
    )

