from __future__ import annotations

from adversarial_fleet.scenarios.genome import ScenarioGenome
from adversarial_fleet.scenarios.task_generator import generate_tasks
from adversarial_fleet.scenarios.validation import validate_scenario


def valid_scenario() -> ScenarioGenome:
    return ScenarioGenome.model_validate(
        {
            "seed": 1042,
            "fleet": {
                "robot_count": 2,
                "max_speed_multiplier": 1.0,
                "acceleration_multiplier": 1.0,
            },
            "tasks": {
                "task_count": 5,
                "arrival_interval_seconds": 8.0,
                "priority_skew": 0.5,
                "patrol_routes": [["coe", "lounge"], ["supplies", "pantry"]],
            },
            "facility": {"blocked_lane_id": None, "door_delay_seconds": 0, "charger_count": 2},
            "faults": {
                "failed_robot_id": None,
                "failure_time_seconds": None,
                "state_update_latency_ms": 0,
            },
        }
    )


def test_generation_is_deterministic() -> None:
    scenario = valid_scenario()
    first = [task.model_dump() for task in generate_tasks(scenario)]
    second = [task.model_dump() for task in generate_tasks(scenario)]
    assert first == second
    assert first[1]["start_offset_seconds"] == 8.0
    assert scenario.digest() == valid_scenario().digest()


def test_valid_office_scenario() -> None:
    result = validate_scenario(valid_scenario())
    assert result.valid
    assert not result.errors


def test_rejects_unverified_runtime_mutation() -> None:
    scenario = valid_scenario().model_copy(deep=True)
    scenario.fleet.max_speed_multiplier = 0.7
    result = validate_scenario(scenario)
    assert not result.valid
    assert any("max_speed_multiplier" in error for error in result.errors)


def test_rejects_unknown_waypoint() -> None:
    scenario = valid_scenario().model_copy(deep=True)
    scenario.tasks.patrol_routes[0][0] = "not_a_real_place"
    result = validate_scenario(scenario)
    assert not result.valid
    assert any("not_a_real_place" in error for error in result.errors)


def test_rejects_unverified_charger_count_mutation() -> None:
    scenario = valid_scenario().model_copy(deep=True)
    scenario.facility.charger_count = 1
    result = validate_scenario(scenario)
    assert not result.valid
    assert any("charger_count" in error for error in result.errors)
