from __future__ import annotations

import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from adversarial_fleet.config import AppConfig, load_document
from adversarial_fleet.metrics.calculator import DEFAULT_SCALES, WEIGHTS
from adversarial_fleet.replay.verifier import ReplayVerifier
from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities

from .algorithms import (
    FitnessSharingGeneticAlgorithm,
    MapElitesAlgorithm,
    NSGA2Algorithm,
    RandomSearch,
    SeverityGeneticAlgorithm,
)
from .algorithms.base import SearchAlgorithm
from .artifacts import SearchArtifactStore
from .cache import (
    CachingEvaluator,
    EvaluationCache,
    EvaluationCacheContext,
    configuration_hash,
    runtime_environment_digest,
)
from .config import (
    GeneticAlgorithmConfig,
    SearchFileConfig,
    load_search_config,
)
from .coordinator import assign_novelty, evaluate_with_confirmation
from .evaluation import AggregateEvaluation, EvaluationState
from .evaluator import CandidateEvaluator, DeterministicFakeEvaluator
from .live_evaluator import LiveCandidateEvaluator
from .models import SearchModel
from .reporting import (
    GenerationDiagnostics,
    SearchMeasures,
    calculate_search_measures,
    generation_diagnostics,
    posthoc_map_archive,
)
from .replay_hooks import verify_elite_replays


SearchStatus = Literal[
    "completed",
    "infrastructure_failure",
    "cleanup_failure",
    "interrupted",
]


class SearchRunReport(SearchModel):
    search_id: str
    status: SearchStatus
    algorithm: str
    evaluator: str
    evaluation_budget: int = Field(ge=1)
    completed_generations: int = Field(ge=0)
    measures: SearchMeasures
    generations: tuple[GenerationDiagnostics, ...]
    replay_verification: dict[str, Any] | None = None
    search_directory: str


def _search_id(config: SearchFileConfig) -> str:
    if config.search.search_id is not None:
        return config.search.search_id
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    return f"search_{stamp}_{config.search.algorithm}_seed_{config.search.search_seed}"


def _algorithm(
    config: SearchFileConfig,
    capabilities: ScenarioCapabilities,
) -> SearchAlgorithm:
    settings = config.search
    ga_config = GeneticAlgorithmConfig(
        search_seed=settings.search_seed,
        population_size=settings.population_size,
        offspring_size=settings.offspring_size,
        tournament_size=settings.tournament_size,
    )
    if settings.algorithm == "random_search":
        return RandomSearch(
            capabilities=capabilities,
            bounds=config.genome,
            search_seed=settings.search_seed,
        )
    if settings.algorithm == "severity_ga":
        return SeverityGeneticAlgorithm(
            capabilities=capabilities,
            bounds=config.genome,
            config=ga_config,
        )
    if settings.algorithm == "fitness_sharing_ga":
        return FitnessSharingGeneticAlgorithm(
            capabilities=capabilities,
            bounds=config.genome,
            config=ga_config,
            descriptor_config=config.descriptor,
        )
    if settings.algorithm == "nsga2":
        return NSGA2Algorithm(
            capabilities=capabilities,
            bounds=config.genome,
            config=ga_config,
        )
    return MapElitesAlgorithm(
        capabilities=capabilities,
        bounds=config.genome,
        config=ga_config,
        map_config=config.map_elites,
    )


def _cache_context(
    config: SearchFileConfig,
    app_config: AppConfig,
) -> EvaluationCacheContext:
    return EvaluationCacheContext(
        environment_image_digest=runtime_environment_digest(),
        metric_configuration_hash=configuration_hash(
            {
                "scales": DEFAULT_SCALES,
                "weights": WEIGHTS,
                "descriptor": config.descriptor.model_dump(mode="json"),
            }
        ),
        failure_detector_configuration_hash=configuration_hash(app_config.failure_detection),
        defender_id=config.execution.defender_id,
    )


def _environment(
    config: SearchFileConfig,
    app_config: AppConfig,
) -> dict[str, Any]:
    context = _cache_context(config, app_config)
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "ros_distro": os.environ.get("ROS_DISTRO"),
        "ros_domain_id": app_config.simulation.ros_domain_id,
        "world": app_config.simulation.world,
        "rmf_container_image": os.environ.get("AFT_RMF_IMAGE"),
        "environment_image_digest": context.environment_image_digest,
        "metric_configuration_hash": context.metric_configuration_hash,
        "failure_detector_configuration_hash": (context.failure_detector_configuration_hash),
        "defender_id": context.defender_id,
    }


class SearchRunner:
    def __init__(
        self,
        *,
        app_config: AppConfig,
        search_config: SearchFileConfig,
        capabilities: ScenarioCapabilities | None = None,
        evaluator: CandidateEvaluator | None = None,
        search_directory: Path | None = None,
    ) -> None:
        self.app_config = app_config
        self.search_config = search_config
        self.capabilities = capabilities or ScenarioCapabilities()
        self.search_id = (
            search_directory.name if search_directory is not None else _search_id(search_config)
        )
        self.search_directory = (
            search_directory.resolve()
            if search_directory is not None
            else (app_config.project.output_dir.resolve() / "searches" / self.search_id)
        )
        self.store = SearchArtifactStore(self.search_directory)
        self.algorithm = _algorithm(search_config, self.capabilities)
        base_evaluator: CandidateEvaluator
        if evaluator is not None:
            base_evaluator = evaluator
        elif search_config.execution.evaluator == "live":
            base_evaluator = LiveCandidateEvaluator(
                app_config=app_config,
                capabilities=self.capabilities,
            )
        else:
            base_evaluator = DeterministicFakeEvaluator(self.capabilities)
        if search_config.execution.reuse_cache:
            self.evaluator: CandidateEvaluator = CachingEvaluator(
                base_evaluator,
                cache=EvaluationCache(search_config.execution.cache_directory),
                context=_cache_context(search_config, app_config),
                capabilities=self.capabilities,
            )
        else:
            self.evaluator = base_evaluator

    @property
    def cache_hit_count(self) -> int:
        return int(getattr(self.evaluator, "cache_hit_count", 0))

    def _initial_batch_size(self, completed: int, *, target: int) -> int:
        remaining = target - completed
        if completed == 0 and self.search_config.search.algorithm != "random_search":
            requested = self.search_config.search.population_size
        else:
            requested = self.search_config.search.offspring_size
        return min(remaining, requested)

    def run(
        self,
        *,
        resume: bool = False,
        stop_after_candidates: int | None = None,
    ) -> SearchRunReport:
        started = time.monotonic()
        history: list[AggregateEvaluation]
        generations: list[GenerationDiagnostics]
        generation = 0
        prior_elapsed = 0.0
        if resume:
            history = self.store.load_evaluations()
            checkpoint = self.store.load_checkpoint()
            self.algorithm.load_state_dict(checkpoint["algorithm_state"])
            generation = int(checkpoint["generation"])
            generations = [
                GenerationDiagnostics.model_validate(item)
                for item in checkpoint.get("generation_diagnostics", [])
            ]
            prior_elapsed = float(checkpoint.get("elapsed_wall_clock_seconds", 0.0))
            if hasattr(self.evaluator, "cache_hit_count"):
                self.evaluator.cache_hit_count = int(checkpoint.get("cache_hit_count", 0))
        else:
            history = []
            generations = []
            self.store.initialize(
                search_id=self.search_id,
                search_config=self.search_config,
                app_config=self.app_config,
                capabilities=self.capabilities,
                environment=_environment(self.search_config, self.app_config),
            )

        status: SearchStatus = "completed"
        budget = self.search_config.search.evaluation_budget
        target = budget if stop_after_candidates is None else min(budget, stop_after_candidates)
        if target < len(history):
            raise ValueError("stop_after_candidates is below the completed candidate count")
        while len(history) < target:
            batch_size = self._initial_batch_size(len(history), target=target)
            genomes = self.algorithm.ask(batch_size)
            for offset, genome in enumerate(genomes, 1):
                self.store.append_candidate(
                    evaluation_index=len(history) + offset,
                    generation=generation,
                    genome=genome,
                )
            evaluated: list[AggregateEvaluation] = []
            accounting: list[tuple[int, float]] = []
            for genome in genomes:
                evaluation = evaluate_with_confirmation(
                    genome,
                    evaluator=self.evaluator,
                    realization_seeds=self.search_config.search.realization_seeds,
                    capabilities=self.capabilities,
                    bounds=self.search_config.genome,
                    descriptor_config=self.search_config.descriptor,
                    confirmation_config=self.search_config.confirmation,
                    mission_timeout_seconds=(self.app_config.simulation.mission_timeout_seconds),
                )
                evaluated.append(evaluation)
                accounting.append(
                    (
                        self.cache_hit_count,
                        prior_elapsed + time.monotonic() - started,
                    )
                )
            diversified = assign_novelty(
                evaluated,
                archive=history,
                config=self.search_config.descriptor,
            )
            self.algorithm.tell(diversified)
            for offset, evaluation in enumerate(diversified, 1):
                cumulative_cache_hits, wall_clock_elapsed = accounting[offset - 1]
                self.store.append_evaluation(
                    evaluation,
                    evaluation_index=len(history) + offset,
                    generation=generation,
                    cumulative_cache_hit_count=cumulative_cache_hits,
                    wall_clock_elapsed_seconds=wall_clock_elapsed,
                )
            history.extend(diversified)
            generations.append(
                generation_diagnostics(
                    generation,
                    diversified,
                    cumulative_evaluations=history,
                    robot_count=self.capabilities.supported_robot_count,
                    map_config=self.search_config.map_elites,
                )
            )
            generation += 1
            elapsed = prior_elapsed + time.monotonic() - started
            self.store.save_checkpoint(
                {
                    "schema_version": 1,
                    "generation": generation,
                    "completed_candidate_count": len(history),
                    "cache_hit_count": self.cache_hit_count,
                    "elapsed_wall_clock_seconds": elapsed,
                    "algorithm_state": self.algorithm.state_dict(),
                    "generation_diagnostics": [
                        item.model_dump(mode="json") for item in generations
                    ],
                }
            )
            terminal_states = {run.state for item in diversified for run in item.runs}
            if EvaluationState.CLEANUP_FAILURE in terminal_states:
                status = "cleanup_failure"
                break
            if self.search_config.execution.abort_on_infrastructure_failure and terminal_states & {
                EvaluationState.INFRASTRUCTURE_FAILURE,
                EvaluationState.INVALID_GENOME,
            }:
                status = "infrastructure_failure"
                break

        if status == "completed" and len(history) < budget:
            status = "interrupted"
        elapsed = prior_elapsed + time.monotonic() - started
        measures = calculate_search_measures(
            history,
            robot_count=self.capabilities.supported_robot_count,
            map_config=self.search_config.map_elites,
            cache_hit_count=self.cache_hit_count,
            wall_clock_runtime_seconds=elapsed,
        )
        posthoc_archive = posthoc_map_archive(
            history,
            robot_count=self.capabilities.supported_robot_count,
            map_config=self.search_config.map_elites,
        )
        replay_report = None
        if (
            self.search_config.execution.evaluator == "live"
            and self.search_config.execution.verify_elites
            and self.search_config.execution.maximum_elite_replays > 0
        ):
            replay_report = verify_elite_replays(
                posthoc_archive,
                verifier=ReplayVerifier(),
                maximum_elites=(self.search_config.execution.maximum_elite_replays),
            ).model_dump(mode="json")
            if replay_report["failed_count"] or replay_report["missing_reference_count"]:
                status = "infrastructure_failure"

        report = SearchRunReport(
            search_id=self.search_id,
            status=status,
            algorithm=self.search_config.search.algorithm,
            evaluator=self.search_config.execution.evaluator,
            evaluation_budget=budget,
            completed_generations=generation,
            measures=measures,
            generations=tuple(generations),
            replay_verification=replay_report,
            search_directory=str(self.search_directory),
        )
        algorithm_reporter = getattr(self.algorithm, "archive_report", None)
        algorithm_archive = (
            algorithm_reporter().model_dump(mode="json") if callable(algorithm_reporter) else None
        )
        novelty_archive = [
            {
                "candidate_id": item.candidate_id,
                "descriptor": item.descriptor.model_dump(mode="json"),
                "novelty_score": item.novelty_score,
                "within_mechanism_novelty": item.within_mechanism_novelty,
            }
            for item in history
        ]
        self.store.finalize(
            summary=report.model_dump(mode="json"),
            archive={
                "posthoc": posthoc_archive.report().model_dump(mode="json"),
                "algorithm": algorithm_archive,
            },
            novelty_archive=novelty_archive,
            status=status,
        )
        return report

    @classmethod
    def resume(
        cls,
        search_directory: Path,
        *,
        evaluator: CandidateEvaluator | None = None,
    ) -> "SearchRunner":
        search_directory = search_directory.resolve()
        search_config = load_search_config(search_directory / "search_config.yaml")
        app_config = AppConfig.model_validate(
            load_document(search_directory / "simulator_config.yaml")
        )
        capabilities = ScenarioCapabilities.model_validate(
            load_document(search_directory / "capabilities.json")
        )
        return cls(
            app_config=app_config,
            search_config=search_config,
            capabilities=capabilities,
            evaluator=evaluator,
            search_directory=search_directory,
        )
