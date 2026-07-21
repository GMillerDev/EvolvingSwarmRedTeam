from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FailureType(StrEnum):
    DEADLOCK = "DEADLOCK"
    CONGESTION_COLLAPSE = "CONGESTION_COLLAPSE"
    TASK_STARVATION = "TASK_STARVATION"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    TRAFFIC_NEGOTIATION_FAILURE = "TRAFFIC_NEGOTIATION_FAILURE"
    RECOVERY_LOOP = "RECOVERY_LOOP"
    RESOURCE_CONTENTION = "RESOURCE_CONTENTION"
    CASCADING_ROBOT_FAILURE = "CASCADING_ROBOT_FAILURE"
    FLEET_FRAGMENTATION = "FLEET_FRAGMENTATION"
    THROUGHPUT_COLLAPSE = "THROUGHPUT_COLLAPSE"
    SIMULATION_ERROR = "SIMULATION_ERROR"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class FailureReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_failure: bool
    failure_type: FailureType | None = None
    severity: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence: dict[str, Any]

