from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FleetGenome(StrictModel):
    robot_count: int = Field(ge=1, le=12)
    max_speed_multiplier: float = Field(default=1.0, ge=0.4, le=1.2)
    acceleration_multiplier: float = Field(default=1.0, gt=0, le=2.0)


class TaskGenome(StrictModel):
    task_count: int = Field(ge=1, le=50)
    arrival_interval_seconds: float = Field(ge=0, le=30)
    priority_skew: float = Field(default=0.0, ge=0, le=1)
    patrol_routes: list[list[str]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_routes(self) -> "TaskGenome":
        if any(len(route) < 2 for route in self.patrol_routes):
            raise ValueError("each patrol route must contain at least two places")
        return self


class FacilityGenome(StrictModel):
    blocked_lane_id: str | None = None
    door_delay_seconds: float = Field(default=0, ge=0, le=30)
    charger_count: int = Field(default=2, ge=0, le=12)


class FaultGenome(StrictModel):
    failed_robot_id: str | None = None
    failure_time_seconds: float | None = Field(default=None, ge=10, le=300)
    state_update_latency_ms: int = Field(default=0, ge=0, le=2000)

    @model_validator(mode="after")
    def validate_failure_pair(self) -> "FaultGenome":
        if self.failed_robot_id is None and self.failure_time_seconds is not None:
            raise ValueError("failure_time_seconds must be null when failed_robot_id is null")
        if self.failed_robot_id is not None and self.failure_time_seconds is None:
            raise ValueError("failure_time_seconds is required when failed_robot_id is set")
        return self


class ScenarioGenome(StrictModel):
    seed: int = Field(ge=0, le=2**32 - 1)
    fleet: FleetGenome
    tasks: TaskGenome
    facility: FacilityGenome = FacilityGenome()
    faults: FaultGenome = FaultGenome()

    def normalized(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)

    def digest(self) -> str:
        canonical = json.dumps(self.normalized(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TaskSpec(StrictModel):
    task_id: str
    category: str = "patrol"
    places: list[str] = Field(min_length=2)
    rounds: int = Field(default=1, ge=1)
    start_offset_seconds: float = Field(default=0, ge=0)
    priority: int = Field(default=0, ge=0)

