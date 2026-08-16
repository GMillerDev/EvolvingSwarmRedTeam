from __future__ import annotations

import json

from adversarial_fleet.config import AppConfig, ProjectConfig
from adversarial_fleet.failures.models import FailureReport
from adversarial_fleet.replay import ReplayExporter
from adversarial_fleet.replay.verifier import _actuator_sequence
from adversarial_fleet.scenarios import ScenarioCapabilities
from adversarial_fleet.scenarios.task_generator import generate_tasks

from .test_scenarios import valid_scenario


def test_replay_package_contains_required_core_artifacts(tmp_path) -> None:
    scenario = valid_scenario()
    config = AppConfig(project=ProjectConfig(output_dir=tmp_path))
    failure = FailureReport(
        is_failure=False, failure_type=None, severity=0, confidence=1, evidence={}
    )
    ReplayExporter().export(
        tmp_path,
        scenario=scenario,
        tasks=generate_tasks(scenario),
        config=config,
        metrics={"task_completion_ratio": 1.0},
        fitness={"score": 0.0, "components": {}},
        failure=failure,
        capabilities=ScenarioCapabilities(),
    )
    required = {
        "scenario.yaml",
        "run_config.yaml",
        "seed.json",
        "tasks.json",
        "metrics.json",
        "failure.json",
        "environment.json",
        "optimizer.json",
        "events.jsonl",
        "rosbag",
        "reproduce.sh",
        "capabilities.json",
    }
    # events.jsonl is normally produced by telemetry; create the empty no-event case explicitly.
    (tmp_path / "events.jsonl").touch()
    assert required <= {path.name for path in tmp_path.iterdir()}
    seed = json.loads((tmp_path / "seed.json").read_text(encoding="utf-8"))
    assert seed["seed"] == 1042
    assert len(seed["scenario_sha256"]) == 64
    assert len(seed["capabilities_sha256"]) == 64


def test_actuator_sequence_ignores_timestamps_but_requires_verification(tmp_path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        '\n'.join(
            (
                '{"event":"robot_state","timestamp":1}',
                '{"event":"lane_closed","fleet_name":"tinyRobot",'
                '"lane_id":"20","actuator_verified":true,"timestamp":2}',
                '{"event":"lane_reopened","fleet_name":"tinyRobot",'
                '"lane_id":"20","actuator_verified":true,"timestamp":9}',
            )
        )
        + '\n',
        encoding="utf-8",
    )

    assert _actuator_sequence(events) == [
        {
            "event": "lane_closed",
            "fleet_name": "tinyRobot",
            "lane_id": "20",
            "actuator_verified": True,
        },
        {
            "event": "lane_reopened",
            "fleet_name": "tinyRobot",
            "lane_id": "20",
            "actuator_verified": True,
        },
    ]
