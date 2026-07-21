from __future__ import annotations

from typing import Any, Iterable

from adversarial_fleet.config import FailureDetectionConfig

from .deadlock import detect_deadlock
from .models import FailureReport
from .starvation import detect_starvation


class FailureDetector:
    def __init__(self, config: FailureDetectionConfig) -> None:
        self.config = config

    def detect(self, events: Iterable[dict[str, Any]]) -> FailureReport:
        materialized = list(events)
        if self.config.deadlock:
            report = detect_deadlock(
                materialized,
                minimum_robots=self.config.deadlock_minimum_robots,
                movement_threshold_meters=self.config.deadlock_movement_threshold_meters,
                deadlock_timeout_seconds=self.config.deadlock_timeout_seconds,
            )
            if report:
                return report
        if self.config.starvation:
            report = detect_starvation(
                materialized,
                threshold_seconds=self.config.starvation_threshold_seconds,
                minimum_newer_tasks_completed=self.config.starvation_minimum_newer_tasks_completed,
            )
            if report:
                return report
        return FailureReport(
            is_failure=False,
            failure_type=None,
            severity=0.0,
            confidence=1.0,
            evidence={},
        )

