from __future__ import annotations

import pytest

from adversarial_fleet.telemetry.event_writer import EventWriter, read_events
from adversarial_fleet.telemetry.structured_logger import StructuredLogger


def test_event_writer_round_trip_and_contract(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    with EventWriter(path) as writer:
        writer.write({"timestamp": 1.0, "event": "heartbeat", "value": 2})
        with pytest.raises(ValueError):
            writer.write({"event": "missing_timestamp"})
    assert read_events(path) == [{"event": "heartbeat", "timestamp": 1.0, "value": 2}]


def test_structured_logger_includes_required_context(tmp_path) -> None:
    path = tmp_path / "orchestrator.jsonl"
    logger = StructuredLogger(
        path,
        run_id="run_1",
        candidate_id="candidate_1",
        generation=3,
        search_method="genetic",
    )
    logger.log("failure_detected", simulation_time=10.0, failure_type="DEADLOCK")
    logger.close()
    event = read_events(path)[0]
    assert event["run_id"] == "run_1"
    assert event["event_type"] == "failure_detected"
    assert event["simulation_time"] == 10.0
