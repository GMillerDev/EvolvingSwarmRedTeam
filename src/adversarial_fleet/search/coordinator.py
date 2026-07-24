from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import Field

from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities

from .algorithms.base import SearchAlgorithm
from .config import ConfirmationConfig, DescriptorConfig, GenomeBounds
from .descriptors import novelty_score
from .evaluation import AggregateEvaluation, CandidateEvaluation
from .evaluator import CandidateEvaluator
from .models import AdversarialGenome, SearchModel
from .objectives import aggregate_candidate_evaluations, should_confirm


class SearchSummary(SearchModel):
    algorithm: str
    candidate_count: int = Field(ge=0)
    realization_run_count: int = Field(ge=0)
    confirmed_failure_count: int = Field(ge=0)
    unique_failure_mechanisms: tuple[str, ...]
    best_robust_severity: float = Field(ge=0, le=10)
    pareto_front_size: int = Field(default=0, ge=0)
    archive_report: dict[str, Any] | None = None
    evaluations: tuple[AggregateEvaluation, ...]


def evaluate_with_confirmation(
    genome: AdversarialGenome,
    *,
    evaluator: CandidateEvaluator,
    realization_seeds: tuple[int, ...],
    capabilities: ScenarioCapabilities,
    bounds: GenomeBounds,
    descriptor_config: DescriptorConfig,
    confirmation_config: ConfirmationConfig,
    mission_timeout_seconds: float,
) -> AggregateEvaluation:
    if not realization_seeds:
        raise ValueError("at least one realization seed is required")
    if len(realization_seeds) < confirmation_config.total_runs:
        raise ValueError("not enough realization seeds for the confirmation policy")
    candidate_id = genome.digest()
    screening = evaluator.evaluate(
        genome,
        realization_seed=realization_seeds[0],
        candidate_id=candidate_id,
    )
    runs: list[CandidateEvaluation] = [screening]
    if should_confirm(screening, confirmation_config=confirmation_config):
        runs.extend(
            evaluator.evaluate(
                genome,
                realization_seed=seed,
                candidate_id=candidate_id,
            )
            for seed in realization_seeds[1 : confirmation_config.total_runs]
        )
    return aggregate_candidate_evaluations(
        genome,
        runs,
        bounds=bounds,
        descriptor_config=descriptor_config,
        confirmation_config=confirmation_config,
        mission_timeout_seconds=mission_timeout_seconds,
        robot_count=capabilities.supported_robot_count,
    )


def assign_novelty(
    evaluations: Iterable[AggregateEvaluation],
    *,
    archive: Iterable[AggregateEvaluation] = (),
    config: DescriptorConfig,
) -> list[AggregateEvaluation]:
    batch = tuple(evaluations)
    archived = tuple(archive)
    output: list[AggregateEvaluation] = []
    for target in batch:
        neighbors = [
            item.descriptor for item in archived + batch if item.candidate_id != target.candidate_id
        ]
        within_mechanism = [
            item.descriptor
            for item in archived + batch
            if item.candidate_id != target.candidate_id
            and item.descriptor.failure_mechanism == target.descriptor.failure_mechanism
        ]
        output.append(
            target.model_copy(
                update={
                    "novelty_score": novelty_score(
                        target.descriptor,
                        neighbors,
                        config=config,
                    ),
                    "within_mechanism_novelty": novelty_score(
                        target.descriptor,
                        within_mechanism,
                        config=config,
                    ),
                }
            )
        )
    return output


def run_search(
    algorithm: SearchAlgorithm,
    *,
    evaluator: CandidateEvaluator,
    capabilities: ScenarioCapabilities,
    bounds: GenomeBounds,
    descriptor_config: DescriptorConfig,
    confirmation_config: ConfirmationConfig,
    realization_seeds: tuple[int, ...],
    iterations: int,
    batch_size: int,
    mission_timeout_seconds: float = 300.0,
) -> SearchSummary:
    if iterations < 1 or batch_size < 1:
        raise ValueError("iterations and batch_size must be positive")
    archive: list[AggregateEvaluation] = []
    realization_run_count = 0
    for _ in range(iterations):
        genomes = algorithm.ask(batch_size)
        evaluated = [
            evaluate_with_confirmation(
                genome,
                evaluator=evaluator,
                realization_seeds=realization_seeds,
                capabilities=capabilities,
                bounds=bounds,
                descriptor_config=descriptor_config,
                confirmation_config=confirmation_config,
                mission_timeout_seconds=mission_timeout_seconds,
            )
            for genome in genomes
        ]
        realization_run_count += sum(len(item.runs) for item in evaluated)
        diversified = assign_novelty(
            evaluated,
            archive=archive,
            config=descriptor_config,
        )
        algorithm.tell(diversified)
        archive.extend(diversified)
    mechanisms = tuple(
        sorted(
            {item.descriptor.failure_mechanism.value for item in archive if item.archive_eligible}
        )
    )
    reporter = getattr(algorithm, "archive_report", None)
    report = reporter() if callable(reporter) else None
    population = tuple(getattr(algorithm, "population", ()))
    return SearchSummary(
        algorithm=str(getattr(algorithm, "algorithm_name", type(algorithm).__name__)),
        candidate_count=len(archive),
        realization_run_count=realization_run_count,
        confirmed_failure_count=sum(item.archive_eligible for item in archive),
        unique_failure_mechanisms=mechanisms,
        best_robust_severity=max(
            (item.robust_severity for item in archive),
            default=0.0,
        ),
        pareto_front_size=sum(item.pareto_rank == 0 for item in population),
        archive_report=None if report is None else report.model_dump(mode="json"),
        evaluations=tuple(archive),
    )
