from __future__ import annotations

import time
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adversarial_fleet.config import AppConfig
from adversarial_fleet.failures import FailureDetector
from adversarial_fleet.failures.models import FailureReport
from adversarial_fleet.failures.models import FailureType
from adversarial_fleet.metrics import calculate_fitness
from adversarial_fleet.replay.exporter import ReplayExporter
from adversarial_fleet.scenarios.genome import ScenarioGenome
from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities
from adversarial_fleet.scenarios.task_generator import generate_tasks
from adversarial_fleet.scenarios.validation import validate_scenario
from adversarial_fleet.telemetry.structured_logger import StructuredLogger

from .rmf_adapter import RmfDemoAdapter


@dataclass(frozen=True)
class RunResult:
    run_id: str
    run_dir: Path
    status: str
    metrics: dict[str, float]
    fitness: dict[str, Any]
    failure: FailureReport


class ExperimentOrchestrator:
    def __init__(
        self,
        config: AppConfig,
        capabilities: ScenarioCapabilities | None = None,
    ) -> None:
        self.config = config
        self.capabilities = capabilities or ScenarioCapabilities()

    def run(self, scenario: ScenarioGenome, candidate_id: str = "candidate_0000") -> RunResult:
        validation = validate_scenario(scenario, self.capabilities)
        validation.require_valid()
        tasks = generate_tasks(scenario)
        run_id = self._run_id(scenario.seed, candidate_id)
        run_dir = self.config.project.output_dir.resolve() / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        adapter = RmfDemoAdapter(self.config, run_dir, capabilities=self.capabilities)
        logger = StructuredLogger(
            run_dir / "orchestrator.jsonl",
            run_id=run_id,
            candidate_id=candidate_id,
            generation=None,
            search_method="direct",
        )
        started = time.monotonic()
        status = "startup_failure"
        failure: FailureReport
        metrics: dict[str, float]
        fitness: dict[str, Any]
        cleanup_error_message: str | None = None
        try:
            logger.log("run_started", seed=scenario.seed, scenario_sha256=scenario.digest())
            health: dict[str, Any] = {}
            startup_started = time.monotonic()
            startup_deadline = startup_started + self.config.simulation.startup_timeout_seconds
            for attempt in range(1, self.config.simulation.startup_max_attempts + 1):
                logger.log("simulation_starting", startup_attempt=attempt)
                adapter.initialize(attempt=attempt)
                attempt_deadline = min(
                    startup_deadline,
                    time.monotonic() + self.config.simulation.startup_attempt_timeout_seconds,
                )
                while time.monotonic() < attempt_deadline:
                    health = adapter.health_check()
                    if health.get("ready"):
                        logger.log("simulation_ready", startup_attempt=attempt)
                        break
                    time.sleep(self.config.simulation.poll_interval_seconds)
                if health.get("ready"):
                    break
                logger.log(
                    "simulation_startup_attempt_failed",
                    startup_attempt=attempt,
                    health=health,
                )
                adapter.shutdown()
                if (
                    attempt < self.config.simulation.startup_max_attempts
                    and time.monotonic() < startup_deadline
                ):
                    adapter = RmfDemoAdapter(
                        self.config,
                        run_dir,
                        capabilities=self.capabilities,
                    )
                    continue
                raise TimeoutError(
                    f"RMF did not become ready after {attempt} startup attempt(s): {health}"
                )
            else:
                raise TimeoutError(
                    f"RMF did not become ready within the configured startup attempts: {health}"
                )

            adapter.reset(scenario.seed, scenario.normalized())
            adapter.start()
            adapter.submit_tasks([task.model_dump(mode="json") for task in tasks])
            logger.log("tasks_submitted", task_count=len(tasks))
            status = "timeout"
            deadline = time.monotonic() + self.config.simulation.mission_timeout_seconds
            while time.monotonic() < deadline:
                adapter.observe()
                if adapter.has_failed():
                    status = "failure"
                    logger.log(
                        "failure_detected", simulation_time=adapter.observe()["simulation_time"]
                    )
                    break
                if adapter.is_complete():
                    status = "completed"
                    logger.log(
                        "mission_completed", simulation_time=adapter.observe()["simulation_time"]
                    )
                    break
                time.sleep(self.config.simulation.poll_interval_seconds)
            metrics = adapter.calculate_metrics()
            failure = FailureDetector(self.config.failure_detection).detect(
                adapter.observe_events()
            )
            if failure.failure_type == FailureType.DEADLOCK:
                metrics["deadlock_duration"] = float(
                    failure.evidence.get("blocked_duration_seconds", 0.0)
                )
                metrics["number_of_deadlock_events"] = 1.0
            elif failure.failure_type == FailureType.TASK_STARVATION:
                metrics["task_starvation_count"] = float(
                    len(failure.evidence.get("starved_tasks", []))
                )
            elif status == "timeout" and not failure.is_failure:
                failure = FailureReport(
                    is_failure=True,
                    failure_type=FailureType.TASK_TIMEOUT,
                    severity=min(1.0, 0.5 + 0.5 * metrics.get("incomplete_task_ratio", 0.0)),
                    confidence=0.95,
                    evidence={
                        "mission_timeout_seconds": self.config.simulation.mission_timeout_seconds,
                        "incomplete_task_ratio": metrics.get("incomplete_task_ratio", 0.0),
                    },
                )
            fitness = calculate_fitness(metrics)
        except Exception as exc:
            logger.log("infrastructure_error", error_type=type(exc).__name__, message=str(exc))
            failure = FailureReport(
                is_failure=False,
                failure_type=None,
                severity=0.0,
                confidence=1.0,
                evidence={"infrastructure_error": type(exc).__name__, "message": str(exc)},
            )
            metrics = {"simulation_runtime": 0.0, "wall_clock_runtime": time.monotonic() - started}
            fitness = {"score": -8.0, "raw_score": -8.0, "components": {}}
        finally:
            try:
                adapter.shutdown()
            except Exception as cleanup_error:
                cleanup_error_message = str(cleanup_error)
                status = "cleanup_failure"
                logger.log("cleanup_error", message=str(cleanup_error))
                (run_dir / "cleanup_error.log").write_text(str(cleanup_error), encoding="utf-8")
            logger.log("run_finished", status=status)
            logger.close()
        ReplayExporter().export(
            run_dir,
            scenario=scenario,
            tasks=tasks,
            config=self.config,
            metrics=metrics,
            fitness=fitness,
            failure=failure,
            capabilities=self.capabilities,
        )
        adapter.export_replay(str(run_dir))
        run_result_document = {
            "run_id": run_id,
            "status": status,
            "seed": scenario.seed,
            "scenario_hash": scenario.digest(),
            "failure_type": (
                failure.failure_type.value if failure.failure_type is not None else None
            ),
            "failure_score": fitness["score"],
            "orphan_process_count": len(adapter.orphan_processes),
            "orphan_processes": adapter.orphan_processes,
            "cleanup_error": cleanup_error_message,
        }
        (run_dir / "run_result.json").write_text(
            json.dumps(run_result_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return RunResult(run_id, run_dir, status, metrics, fitness, failure)

    @staticmethod
    def _run_id(seed: int, candidate_id: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
        safe_candidate = "".join(char for char in candidate_id if char.isalnum() or char in "_-")
        return f"run_{stamp}_seed_{seed}_{safe_candidate}"
