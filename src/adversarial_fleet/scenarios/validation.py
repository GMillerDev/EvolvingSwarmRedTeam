from __future__ import annotations

from dataclasses import dataclass, field

from .genome import ScenarioGenome


OFFICE_WAYPOINTS = frozenset({"coe", "lounge", "supplies", "pantry", "hardware_2"})
OFFICE_ROBOTS = frozenset({"tinyRobot1", "tinyRobot2"})


@dataclass(frozen=True)
class ScenarioCapabilities:
    world: str = "office"
    supported_robot_count: int = 2
    waypoints: frozenset[str] = OFFICE_WAYPOINTS
    robot_ids: frozenset[str] = OFFICE_ROBOTS
    lane_ids: frozenset[str] = field(default_factory=frozenset)
    supports_speed_multiplier: bool = False
    supports_acceleration_multiplier: bool = False
    supports_lane_closure: bool = False
    supports_door_delay: bool = False
    supports_robot_failure: bool = False
    supports_state_update_latency: bool = False


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...]

    def require_valid(self) -> None:
        if not self.valid:
            raise ValueError("Invalid scenario: " + "; ".join(self.errors))


def validate_scenario(
    scenario: ScenarioGenome,
    capabilities: ScenarioCapabilities = ScenarioCapabilities(),
) -> ValidationResult:
    errors: list[str] = []
    if scenario.fleet.robot_count != capabilities.supported_robot_count:
        errors.append(
            f"{capabilities.world} currently supports exactly "
            f"{capabilities.supported_robot_count} configured robots"
        )
    unknown_places = sorted(
        {place for route in scenario.tasks.patrol_routes for place in route}
        - capabilities.waypoints
    )
    if unknown_places:
        errors.append(f"unknown or unverified waypoints: {', '.join(unknown_places)}")
    if scenario.fleet.max_speed_multiplier != 1.0 and not capabilities.supports_speed_multiplier:
        errors.append("max_speed_multiplier mutation is not verified for this adapter")
    if scenario.fleet.acceleration_multiplier != 1.0 and not capabilities.supports_acceleration_multiplier:
        errors.append("acceleration_multiplier mutation is not verified for this adapter")
    if scenario.facility.blocked_lane_id is not None:
        if scenario.facility.blocked_lane_id not in capabilities.lane_ids:
            errors.append("blocked_lane_id is not in the verified navigable lane set")
        elif not capabilities.supports_lane_closure:
            errors.append("lane closure is not verified for this adapter")
    if scenario.facility.door_delay_seconds != 0 and not capabilities.supports_door_delay:
        errors.append("door_delay_seconds mutation is not verified for this adapter")
    if scenario.faults.failed_robot_id is not None:
        if scenario.faults.failed_robot_id not in capabilities.robot_ids:
            errors.append("failed_robot_id does not identify a verified Office robot")
        if not capabilities.supports_robot_failure:
            errors.append("robot failure injection is not verified for this adapter")
    if scenario.faults.state_update_latency_ms != 0 and not capabilities.supports_state_update_latency:
        errors.append("state_update_latency_ms mutation is not verified for this adapter")
    return ValidationResult(not errors, tuple(errors))

