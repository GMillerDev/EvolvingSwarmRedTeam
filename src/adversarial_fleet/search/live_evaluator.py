from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from adversarial_fleet.config import AppConfig
from adversarial_fleet.failures.models import FailureType
from adversarial_fleet.metrics import calculate_severity
from adversarial_fleet.orchestrator.runner import ExperimentOrchestrator, RunResult
from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities
from adversarial_fleet.telemetry.event_writer import read_events

from .encoding import decode_genome
from .evaluation import CandidateEvaluation, EvaluationState, FailureMechanism
from .models import AdversarialGenome, ScenarioRealization


class Orchestrator(Protocol):
    def run(self, scenario: Any, candidate_id: str = "candidate_0000") -> RunResult: ...


FAILURE_TYPE_MAP = {
    FailureType.DEADLOCK: FailureMechanism.DEADLOCK,
    FailureType.CONGESTION_COLLAPSE: FailureMechanism.DEADLOCK,
    FailureType.RESOURCE_CONTENTION: FailureMechanism.DEADLOCK,
    FailureType.TASK_STARVATION: FailureMechanism.TASK_STARVATION,
    FailureType.TASK_TIMEOUT: FailureMechanism.TASK_TIMEOUT_OR_INCOMPLETE,
    FailureType.THROUGHPUT_COLLAPSE: FailureMechanism.TASK_TIMEOUT_OR_INCOMPLETE,
    FailureType.TRAFFIC_NEGOTIATION_FAILURE: FailureMechanism.NEGOTIATION_FAILURE,
    FailureType.RECOVERY_LOOP: FailureMechanism.RECOVERY_FAILURE,
    FailureType.CASCADING_ROBOT_FAILURE: FailureMechanism.UNKNOWN_FLEET_FAILURE,
    FailureType.FLEET_FRAGMENTATION: FailureMechanism.UNKNOWN_FLEET_FAILURE,
    FailureType.UNKNOWN_FAILURE: FailureMechanism.UNKNOWN_FLEET_FAILURE,
}

FAILURE_EVENT_NAMES = {
    "collision",
    "deadlock_start",
    "negotiation_failure",
    "recovery_loop",
    "robot_failure",
    "task_starved",
}


def _invalid_phenotype_hash(
    genome: AdversarialGenome,
    *,
    realization_seed: int,
    error: Exception,
) -> str:
    value = {
        "genome": genome.normalized(),
        "realization_seed": realization_seed,
        "error_type": type(error).__name__,
        "error": str(error),
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _failure_onset(events: tuple[dict[str, Any], ...]) -> float | None:
    timestamps = [
        float(event["timestamp"])
        for event in events
        if event.get("event") in FAILURE_EVENT_NAMES and event.get("timestamp") is not None
    ]
    return min(timestamps, default=None)


def _affected_robots(
    events: tuple[dict[str, Any], ...],
    evidence: Mapping[str, Any],
) -> tuple[str, ...]:
    robot_ids: set[str] = set()
    for event in events:
        if event.get("event") not in FAILURE_EVENT_NAMES:
            continue
        if event.get("robot_id") is not None:
            robot_ids.add(str(event["robot_id"]))
        value = event.get("robot_ids")
        if isinstance(value, list):
            robot_ids.update(str(item) for item in value)
    for key in ("robot_id", "failed_robot_id"):
        if evidence.get(key) is not None:
            robot_ids.add(str(evidence[key]))
    for key in ("robot_ids", "robots", "blocked_robots", "affected_robots"):
        value = evidence.get(key)
        if isinstance(value, list):
            robot_ids.update(str(item) for item in value)
    return tuple(sorted(robot_ids))


def _terminal_state(
    result: RunResult,
    *,
    orphan_process_count: int,
) -> EvaluationState:
    if result.status == "cleanup_failure" or orphan_process_count:
        return EvaluationState.CLEANUP_FAILURE
    if result.failure.failure_type == FailureType.SIMULATION_ERROR:
        return EvaluationState.INFRASTRUCTURE_FAILURE
    if result.status == "completed":
        return EvaluationState.VALID_COMPLETED
    if result.status == "failure":
        return EvaluationState.VALID_FAILURE
    if result.status == "timeout":
        return EvaluationState.VALID_TIMEOUT
    return EvaluationState.INFRASTRUCTURE_FAILURE


class LiveCandidateEvaluator:
    """Decode one candidate and execute it through the real experiment orchestrator."""

    def __init__(
        self,
        *,
        app_config: AppConfig,
        capabilities: ScenarioCapabilities | None = None,
        orchestrator: Orchestrator | None = None,
    ) -> None:
        self.app_config = app_config
        self.capabilities = capabilities or ScenarioCapabilities()
        self.orchestrator = orchestrator or ExperimentOrchestrator(
            app_config,
            capabilities=self.capabilities,
        )
        self.evaluation_count = 0

    def evaluate(
        self,
        genome: AdversarialGenome,
        *,
        realization_seed: int,
        candidate_id: str,
    ) -> CandidateEvaluation:
        if candidate_id != genome.digest():
            raise ValueError("candidate_id must match the supplied genome")
        realization = ScenarioRealization.from_genome(
            genome,
            realization_seed=realization_seed,
        )
        try:
            phenotype = decode_genome(
                genome,
                capabilities=self.capabilities,
                realization_seed=realization_seed,
            )
        except (ValueError, TypeError) as error:
            return CandidateEvaluation(
                candidate_id=candidate_id,
                realization_id=realization.digest(),
                phenotype_hash=_invalid_phenotype_hash(
                    genome,
                    realization_seed=realization_seed,
                    error=error,
                ),
                genome=genome,
                realization_seed=realization_seed,
                state=EvaluationState.INVALID_GENOME,
                mission_result="invalid",
                cleanup_error=f"{type(error).__name__}: {error}",
            )

        result = self.orchestrator.run(
            phenotype.scenario,
            candidate_id=candidate_id[:12],
        )
        self.evaluation_count += 1
        run_result_path = result.run_dir / "run_result.json"
        run_document = (
            json.loads(run_result_path.read_text(encoding="utf-8"))
            if run_result_path.is_file()
            else {}
        )
        orphan_process_count = int(run_document.get("orphan_process_count", 0))
        state = _terminal_state(
            result,
            orphan_process_count=orphan_process_count,
        )
        mechanism = (
            FAILURE_TYPE_MAP.get(result.failure.failure_type, FailureMechanism.NONE)
            if result.failure.failure_type is not None
            else FailureMechanism.NONE
        )
        events = tuple(read_events(result.run_dir / "events.jsonl"))
        affected = _affected_robots(events, result.failure.evidence)
        metrics = {key: float(value) for key, value in result.metrics.items()}
        severity = (
            float(calculate_severity(metrics)["severity_score"]) if state.is_valid_run else 0.0
        )
        return CandidateEvaluation(
            candidate_id=candidate_id,
            realization_id=phenotype.realization_id,
            phenotype_hash=phenotype.phenotype_hash,
            genome=genome,
            realization_seed=realization_seed,
            state=state,
            mission_result=result.status,
            failure_mechanism=mechanism,
            severity_score=severity,
            metrics=metrics,
            events=events,
            affected_robot_ids=affected,
            affected_robot_data_available=bool(affected),
            failure_onset_seconds=_failure_onset(events),
            cleanup_error=run_document.get("cleanup_error"),
            run_path=str(result.run_dir.resolve()),
            orphan_process_count=orphan_process_count,
        )
