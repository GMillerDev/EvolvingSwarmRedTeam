from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ConfigDict, Field

from .genome import StrictModel


OFFICE_WAYPOINTS = frozenset({"coe", "lounge", "supplies", "pantry", "hardware_2"})
OFFICE_ROBOTS = frozenset({"tinyRobot1", "tinyRobot2"})


class ScenarioCapabilities(StrictModel):
    """Versioned declaration of scenario mutations a live adapter can apply."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "office-kilted-v1"
    world: str = "office"
    fleet_name: str = "tinyRobot"
    supported_robot_count: int = Field(default=2, ge=1, le=12)
    default_charger_count: int = Field(default=2, ge=0, le=12)
    waypoints: frozenset[str] = OFFICE_WAYPOINTS
    robot_ids: frozenset[str] = OFFICE_ROBOTS
    lane_ids: frozenset[str] = frozenset()
    supports_speed_multiplier: bool = False
    supports_acceleration_multiplier: bool = False
    supports_lane_closure: bool = False
    supports_door_delay: bool = False
    supports_charger_count: bool = False
    supports_robot_failure: bool = False
    supports_state_update_latency: bool = False

    def normalized(self) -> dict[str, object]:
        """Return a stable JSON-compatible capability document."""

        return {
            "version": self.version,
            "world": self.world,
            "fleet_name": self.fleet_name,
            "supported_robot_count": self.supported_robot_count,
            "default_charger_count": self.default_charger_count,
            "waypoints": sorted(self.waypoints),
            "robot_ids": sorted(self.robot_ids),
            "lane_ids": sorted(self.lane_ids),
            "supports_speed_multiplier": self.supports_speed_multiplier,
            "supports_acceleration_multiplier": self.supports_acceleration_multiplier,
            "supports_lane_closure": self.supports_lane_closure,
            "supports_door_delay": self.supports_door_delay,
            "supports_charger_count": self.supports_charger_count,
            "supports_robot_failure": self.supports_robot_failure,
            "supports_state_update_latency": self.supports_state_update_latency,
        }

    def digest(self) -> str:
        canonical = json.dumps(self.normalized(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_capabilities(path: Path) -> ScenarioCapabilities:
    from adversarial_fleet.config import load_document

    return ScenarioCapabilities.model_validate(load_document(path))
