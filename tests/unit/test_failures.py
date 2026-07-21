from __future__ import annotations

from adversarial_fleet.failures.deadlock import detect_deadlock
from adversarial_fleet.failures.models import FailureType
from adversarial_fleet.failures.starvation import detect_starvation


def test_detects_two_robot_deadlock() -> None:
    events = []
    for timestamp in (0.0, 15.0, 30.0):
        events.extend(
            [
                {
                    "timestamp": timestamp,
                    "event": "robot_state",
                    "robot_id": "r1",
                    "x": 1.0,
                    "y": 2.0,
                    "task_active": True,
                },
                {
                    "timestamp": timestamp,
                    "event": "robot_state",
                    "robot_id": "r2",
                    "x": 1.05,
                    "y": 2.0,
                    "task_active": True,
                },
            ]
        )
    report = detect_deadlock(events)
    assert report is not None
    assert report.failure_type == FailureType.DEADLOCK
    assert report.evidence["blocked_robots"] == ["r1", "r2"]


def test_motion_prevents_deadlock() -> None:
    events = [
        {"timestamp": 0, "event": "robot_state", "robot_id": "r1", "x": 0, "y": 0, "task_active": True},
        {"timestamp": 30, "event": "robot_state", "robot_id": "r1", "x": 5, "y": 0, "task_active": True},
        {"timestamp": 0, "event": "robot_state", "robot_id": "r2", "x": 0, "y": 1, "task_active": True},
        {"timestamp": 30, "event": "robot_state", "robot_id": "r2", "x": 5, "y": 1, "task_active": True},
    ]
    assert detect_deadlock(events) is None


def test_detects_starvation_only_after_newer_completions() -> None:
    events = [
        {"timestamp": 0, "event": "task_submitted", "task_id": "old"},
        {"timestamp": 10, "event": "task_submitted", "task_id": "new1"},
        {"timestamp": 11, "event": "task_submitted", "task_id": "new2"},
        {"timestamp": 20, "event": "task_completed", "task_id": "new1"},
        {"timestamp": 30, "event": "task_completed", "task_id": "new2"},
        {"timestamp": 130, "event": "heartbeat"},
    ]
    report = detect_starvation(events)
    assert report is not None
    assert report.failure_type == FailureType.TASK_STARVATION
    assert report.evidence["starved_tasks"] == ["old"]

