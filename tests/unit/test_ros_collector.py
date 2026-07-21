from adversarial_fleet.telemetry.ros_collector import _task_event


def test_maps_task_state_update() -> None:
    event = _task_event(
        {"type": "task_state_update", "data": {"booking": {"id": "patrol.dispatch-0"}, "status": "completed"}},
        12.5,
    )
    assert event == {
        "timestamp": 12.5,
        "event": "task_completed",
        "task_id": "patrol.dispatch-0",
        "status": "completed",
    }

