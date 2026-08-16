from __future__ import annotations

import hashlib
import random
from typing import Protocol

from adversarial_fleet.metrics import calculate_severity
from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities

from .encoding import decode_genome
from .evaluation import CandidateEvaluation, EvaluationState, FailureMechanism
from .models import AdversarialGenome


class CandidateEvaluator(Protocol):
    def evaluate(
        self,
        genome: AdversarialGenome,
        *,
        realization_seed: int,
        candidate_id: str,
    ) -> CandidateEvaluation: ...


class DeterministicFakeEvaluator:
    """ROS-free evaluator used to validate search behavior and reproducibility."""

    def __init__(
        self,
        capabilities: ScenarioCapabilities | None = None,
    ) -> None:
        self.capabilities = capabilities or ScenarioCapabilities()
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
        phenotype = decode_genome(
            genome,
            capabilities=self.capabilities,
            realization_seed=realization_seed,
        )
        self.evaluation_count += 1
        workload = genome.workload
        route_points = [point for route in workload.patrol_routes for point in route]
        unique_ratio = len(set(route_points)) / len(route_points)
        overlap = 1.0 - unique_ratio
        density = workload.task_count / max(0.5, workload.arrival_interval_seconds)
        if genome.facility is not None:
            density *= 1.35
            overlap = min(1.0, overlap + 0.15)
        seed_material = f"{phenotype.realization_id}:fake-evaluator-v1"
        jitter_rng = random.Random(
            int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
        )
        jitter = jitter_rng.uniform(-2.0, 2.0)

        p95_latency = max(
            0.0,
            25.0 + 13.0 * density + 90.0 * overlap + 25.0 * workload.priority_skew + jitter,
        )
        incomplete_ratio = 0.0
        if density >= 8:
            incomplete_ratio = 0.75
        elif density >= 4:
            incomplete_ratio = 0.50
        elif density >= 2.5:
            incomplete_ratio = 0.25

        mechanism = FailureMechanism.NONE
        if overlap >= 0.45 and density >= 1.25:
            mechanism = FailureMechanism.DEADLOCK
        elif workload.priority_skew >= 0.65 and workload.task_count >= 8:
            mechanism = FailureMechanism.TASK_STARVATION
        elif incomplete_ratio > 0:
            mechanism = FailureMechanism.TASK_TIMEOUT_OR_INCOMPLETE
        elif p95_latency >= 120:
            mechanism = FailureMechanism.LATENCY_DEGRADATION

        completed = round(workload.task_count * (1.0 - incomplete_ratio))
        deadlock_duration = 45.0 + 30.0 * overlap if mechanism == FailureMechanism.DEADLOCK else 0.0
        starvation_count = 1.0 if mechanism == FailureMechanism.TASK_STARVATION else 0.0
        blocked_time = deadlock_duration * 2 if deadlock_duration else 0.0
        metrics = {
            "tasks_submitted": float(workload.task_count),
            "tasks_completed": float(completed),
            "tasks_incomplete": float(workload.task_count - completed),
            "task_completion_ratio": completed / workload.task_count,
            "incomplete_task_ratio": incomplete_ratio,
            "mean_task_latency": p95_latency * 0.8,
            "p95_task_latency": p95_latency,
            "maximum_task_latency": p95_latency * 1.1,
            "deadlock_duration": deadlock_duration,
            "number_of_deadlock_events": float(deadlock_duration > 0),
            "task_starvation_count": starvation_count,
            "negotiation_failure_count": 0.0,
            "recovery_event_count": 0.0,
            "recovery_loop_count": 0.0,
            "robot_failure_count": 0.0,
            "lane_closure_event_count": float(genome.facility is not None),
            "fleet_fragmentation_score": min(1.0, overlap),
            "robot_idle_time_mean": 0.0,
            "robot_idle_time_variance": 0.0,
            "blocked_time_total": blocked_time,
            "simulation_runtime": min(300.0, p95_latency + 30),
            "wall_clock_runtime": 0.01,
        }
        severity = calculate_severity(metrics)
        affected = (
            ("tinyRobot1", "tinyRobot2")
            if mechanism
            in {
                FailureMechanism.DEADLOCK,
                FailureMechanism.TASK_TIMEOUT_OR_INCOMPLETE,
                FailureMechanism.LATENCY_DEGRADATION,
            }
            else ("tinyRobot1",)
            if mechanism == FailureMechanism.TASK_STARVATION
            else ()
        )
        active_one = max(1, workload.task_count * 3)
        active_two = max(
            1,
            round(active_one * (1.0 - 0.6 * workload.priority_skew)),
        )
        events = tuple(
            [
                {
                    "timestamp": float(index),
                    "event": "robot_state",
                    "robot_id": "tinyRobot1",
                    "task_active": index < active_one,
                }
                for index in range(active_one)
            ]
            + [
                {
                    "timestamp": float(index),
                    "event": "robot_state",
                    "robot_id": "tinyRobot2",
                    "task_active": index < active_two,
                }
                for index in range(active_one)
            ]
        )
        if incomplete_ratio >= 0.50:
            state = EvaluationState.VALID_TIMEOUT
            mission_result = "timeout"
        elif mechanism in {
            FailureMechanism.DEADLOCK,
            FailureMechanism.TASK_STARVATION,
        }:
            state = EvaluationState.VALID_FAILURE
            mission_result = "failure"
        else:
            state = EvaluationState.VALID_COMPLETED
            mission_result = "completed"
        return CandidateEvaluation(
            candidate_id=candidate_id,
            realization_id=phenotype.realization_id,
            phenotype_hash=phenotype.phenotype_hash,
            genome=genome,
            realization_seed=realization_seed,
            state=state,
            mission_result=mission_result,
            failure_mechanism=mechanism,
            severity_score=float(severity["severity_score"]),
            metrics=metrics,
            events=events,
            affected_robot_ids=affected,
            affected_robot_data_available=True,
            failure_onset_seconds=(
                min(240.0, 20.0 + p95_latency * 0.35)
                if mechanism != FailureMechanism.NONE
                else None
            ),
        )
