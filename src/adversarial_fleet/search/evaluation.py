from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from .config import CONTINUOUS_DESCRIPTOR_FIELDS
from .models import AdversarialGenome, SearchModel


class EvaluationState(str, Enum):
    VALID_COMPLETED = "valid_completed"
    VALID_FAILURE = "valid_failure"
    VALID_TIMEOUT = "valid_timeout"
    INVALID_GENOME = "invalid_genome"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    CLEANUP_FAILURE = "cleanup_failure"

    @property
    def is_valid_run(self) -> bool:
        return self in {
            EvaluationState.VALID_COMPLETED,
            EvaluationState.VALID_FAILURE,
            EvaluationState.VALID_TIMEOUT,
        }


class FailureMechanism(str, Enum):
    NONE = "none"
    LATENCY_DEGRADATION = "latency_degradation"
    TASK_TIMEOUT_OR_INCOMPLETE = "task_timeout_or_incomplete"
    TASK_STARVATION = "task_starvation"
    DEADLOCK = "deadlock"
    NEGOTIATION_FAILURE = "negotiation_failure"
    COLLISION = "collision"
    RECOVERY_FAILURE = "recovery_failure"
    UNKNOWN_FLEET_FAILURE = "unknown_fleet_failure"


class BehaviorDescriptor(SearchModel):
    failure_mechanism: FailureMechanism
    mission_result: str
    incomplete_task_ratio: float | None = Field(default=None, ge=0, le=1)
    p95_latency_ratio: float | None = Field(default=None, ge=0, le=1)
    failure_onset_ratio: float | None = Field(default=None, ge=0, le=1)
    deadlock_duration_ratio: float | None = Field(default=None, ge=0, le=1)
    starvation_ratio: float | None = Field(default=None, ge=0, le=1)
    blocked_time_ratio: float | None = Field(default=None, ge=0, le=1)
    affected_robot_fraction: float | None = Field(default=None, ge=0, le=1)
    task_active_imbalance: float | None = Field(default=None, ge=0, le=1)
    recovery_ratio: float | None = Field(default=None, ge=0, le=1)
    negotiation_failure_ratio: float | None = Field(default=None, ge=0, le=1)
    availability_mask: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def validate_availability_mask(self) -> "BehaviorDescriptor":
        expected = frozenset(
            name for name in CONTINUOUS_DESCRIPTOR_FIELDS if getattr(self, name) is not None
        )
        if self.availability_mask != expected:
            raise ValueError("availability_mask must exactly match populated descriptor fields")
        return self


class CandidateEvaluation(SearchModel):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    realization_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    phenotype_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    genome: AdversarialGenome
    realization_seed: int = Field(ge=0, le=2**32 - 1)
    state: EvaluationState
    mission_result: str
    failure_mechanism: FailureMechanism = FailureMechanism.NONE
    severity_score: float = Field(default=0.0, ge=0, le=10)
    metrics: dict[str, float] = Field(default_factory=dict)
    events: tuple[dict[str, Any], ...] = ()
    affected_robot_ids: tuple[str, ...] = ()
    affected_robot_data_available: bool = False
    failure_onset_seconds: float | None = Field(default=None, ge=0)
    cleanup_error: str | None = None
    run_path: str | None = None

    @model_validator(mode="after")
    def validate_terminal_state(self) -> "CandidateEvaluation":
        if not self.state.is_valid_run and self.severity_score != 0:
            raise ValueError("invalid or infrastructure evaluations must have zero severity")
        return self


class SeverityStatistics(SearchModel):
    minimum: float
    maximum: float
    mean: float
    median: float
    standard_deviation: float
    percentile_25: float


class ReproducibilitySummary(SearchModel):
    score: float = Field(ge=0, le=1)
    modal_signature: tuple[str, str, str] | None = None
    valid_run_count: int = Field(ge=0)
    total_run_count: int = Field(ge=0)
    continuous_metric_agreement: dict[str, bool] = Field(default_factory=dict)


class AggregateEvaluation(SearchModel):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    genome: AdversarialGenome
    runs: tuple[CandidateEvaluation, ...]
    severity: SeverityStatistics
    robust_severity: float = Field(ge=0, le=10)
    reproducibility: ReproducibilitySummary
    descriptor: BehaviorDescriptor
    complexity: float = Field(ge=0, le=1)
    archive_eligible: bool
    unstable: bool
    novelty_score: float = Field(default=0.0, ge=0, le=1)
    within_mechanism_novelty: float = Field(default=0.0, ge=0, le=1)
    shared_severity: float = Field(default=0.0, ge=0)
    niche_count: float = Field(default=1.0, ge=1)
    pareto_rank: int | None = Field(default=None, ge=0)
    crowding_distance: float | None = Field(default=None, ge=0)
    archive_niche: str | None = None
    archive_inserted: bool = False

    @model_validator(mode="after")
    def validate_candidate_identity(self) -> "AggregateEvaluation":
        if self.candidate_id != self.genome.digest():
            raise ValueError("candidate_id does not match genome hash")
        if any(run.candidate_id != self.candidate_id for run in self.runs):
            raise ValueError("aggregate contains a run for a different candidate")
        return self
