from __future__ import annotations

import json
import random
from pathlib import Path

from adversarial_fleet.scenarios import ScenarioCapabilities
from adversarial_fleet.search.algorithms import MapElitesAlgorithm, NSGA2Algorithm
from adversarial_fleet.search.archives import (
    AffectedRobotBucket,
    ArchiveInsertionReason,
    IncompleteTaskBucket,
    MapElitesArchive,
    OnsetBucket,
    map_elites_niche,
)
from adversarial_fleet.search.config import (
    ConfirmationConfig,
    DescriptorConfig,
    GeneticAlgorithmConfig,
    GenomeBounds,
    MapElitesConfig,
)
from adversarial_fleet.search.coordinator import evaluate_with_confirmation, run_search
from adversarial_fleet.search.evaluation import EvaluationState, FailureMechanism
from adversarial_fleet.search.evaluator import DeterministicFakeEvaluator
from adversarial_fleet.search.pareto import (
    crowding_distances,
    dominates,
    non_dominated_sort,
)
from adversarial_fleet.search.replay_hooks import verify_elite_replays
from adversarial_fleet.search.variation import sample_genome


CAPABILITIES = ScenarioCapabilities()
BOUNDS = GenomeBounds()
DESCRIPTORS = DescriptorConfig(novelty_k=4)
CONFIRMATION = ConfirmationConfig(confirm_all=True)
SEEDS = (1042, 1043, 1044)


def _evaluations(count: int, *, seed: int = 300):
    rng = random.Random(seed)
    evaluator = DeterministicFakeEvaluator(CAPABILITIES)
    return [
        evaluate_with_confirmation(
            sample_genome(rng, capabilities=CAPABILITIES, bounds=BOUNDS),
            evaluator=evaluator,
            realization_seeds=SEEDS,
            capabilities=CAPABILITIES,
            bounds=BOUNDS,
            descriptor_config=DESCRIPTORS,
            confirmation_config=CONFIRMATION,
            mission_timeout_seconds=300.0,
        )
        for _ in range(count)
    ]


def _objectives(
    evaluation,
    *,
    severity: float,
    novelty: float,
    reproducibility: float,
    complexity: float,
):
    return evaluation.model_copy(
        update={
            "robust_severity": severity,
            "novelty_score": novelty,
            "reproducibility": evaluation.reproducibility.model_copy(
                update={"score": reproducibility}
            ),
            "complexity": complexity,
        }
    )


def _niche_evaluation(
    evaluation,
    *,
    mechanism: FailureMechanism = FailureMechanism.DEADLOCK,
    affected_fraction: float = 1.0,
    onset: float = 0.2,
    incomplete: float = 0.0,
    severity: float = 5.0,
    reproducibility: float = 1.0,
    complexity: float = 0.5,
):
    return evaluation.model_copy(
        update={
            "descriptor": evaluation.descriptor.model_copy(
                update={
                    "failure_mechanism": mechanism,
                    "mission_result": "failure",
                    "affected_robot_fraction": affected_fraction,
                    "failure_onset_ratio": onset,
                    "incomplete_task_ratio": incomplete,
                }
            ),
            "robust_severity": severity,
            "reproducibility": evaluation.reproducibility.model_copy(
                update={"score": reproducibility}
            ),
            "complexity": complexity,
            "archive_eligible": True,
            "unstable": False,
        }
    )


def test_non_dominated_sort_uses_all_objectives_and_validity_constraint() -> None:
    raw = _evaluations(4)
    severe = _objectives(
        raw[0],
        severity=9,
        novelty=0.2,
        reproducibility=0.9,
        complexity=0.5,
    )
    novel = _objectives(
        raw[1],
        severity=5,
        novelty=0.9,
        reproducibility=0.9,
        complexity=0.2,
    )
    dominated = _objectives(
        raw[2],
        severity=4,
        novelty=0.1,
        reproducibility=0.5,
        complexity=0.8,
    )
    invalid_runs = tuple(
        run.model_copy(
            update={
                "state": EvaluationState.INFRASTRUCTURE_FAILURE,
                "severity_score": 0.0,
            }
        )
        for run in raw[3].runs
    )
    invalid = _objectives(
        raw[3].model_copy(update={"runs": invalid_runs}),
        severity=10,
        novelty=1,
        reproducibility=1,
        complexity=0,
    )

    fronts = non_dominated_sort([dominated, invalid, novel, severe])

    assert {item.candidate_id for item in fronts[0]} == {
        severe.candidate_id,
        novel.candidate_id,
    }
    assert dominates(severe, dominated)
    assert dominates(novel, dominated)
    assert dominates(dominated, invalid)


def test_crowding_marks_objective_edges_and_scores_interior_points() -> None:
    raw = _evaluations(5, seed=410)
    front = [
        _objectives(
            evaluation,
            severity=float(index + 1),
            novelty=1.0 - index / 4,
            reproducibility=0.8,
            complexity=0.4,
        )
        for index, evaluation in enumerate(raw)
    ]

    crowding = crowding_distances(front)

    assert crowding[front[0].candidate_id] is None
    assert crowding[front[-1].candidate_id] is None
    assert all(crowding[item.candidate_id] is not None for item in front[1:-1])
    assert all(float(crowding[item.candidate_id]) >= 0 for item in front[1:-1])


def test_nsga2_selects_tradeoffs_and_resumes_deterministically() -> None:
    config = GeneticAlgorithmConfig(search_seed=7301, population_size=3, offspring_size=3)
    algorithm = NSGA2Algorithm(
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
        config=config,
    )
    genomes = algorithm.ask(5)
    evaluator = DeterministicFakeEvaluator(CAPABILITIES)
    raw = [
        evaluate_with_confirmation(
            genome,
            evaluator=evaluator,
            realization_seeds=SEEDS,
            capabilities=CAPABILITIES,
            bounds=BOUNDS,
            descriptor_config=DESCRIPTORS,
            confirmation_config=CONFIRMATION,
            mission_timeout_seconds=300.0,
        )
        for genome in genomes
    ]
    values = (
        (9.0, 0.1, 0.9, 0.5),
        (7.0, 0.8, 0.9, 0.5),
        (5.0, 0.9, 0.9, 0.2),
        (4.0, 0.1, 0.5, 0.8),
        (3.0, 0.2, 0.3, 0.9),
    )
    evaluated = [
        _objectives(
            item,
            severity=severity,
            novelty=novelty,
            reproducibility=reproducibility,
            complexity=complexity,
        )
        for item, (severity, novelty, reproducibility, complexity) in zip(raw, values)
    ]
    algorithm.tell(evaluated)

    assert {item.candidate_id for item in algorithm.population} == {
        item.candidate_id for item in evaluated[:3]
    }
    assert all(item.pareto_rank == 0 for item in algorithm.population)

    state = json.loads(json.dumps(algorithm.state_dict()))
    resumed = NSGA2Algorithm(
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
        config=config,
    )
    resumed.load_state_dict(state)
    assert resumed.population == algorithm.population
    assert resumed.ask(3) == algorithm.ask(3)


def test_nsga2_search_is_deterministic_and_retains_a_pareto_front() -> None:
    algorithm_config = GeneticAlgorithmConfig(
        search_seed=8500,
        population_size=12,
        offspring_size=12,
        tournament_size=3,
    )

    def execute():
        algorithm = NSGA2Algorithm(
            capabilities=CAPABILITIES,
            bounds=BOUNDS,
            config=algorithm_config,
        )
        summary = run_search(
            algorithm,
            evaluator=DeterministicFakeEvaluator(CAPABILITIES),
            capabilities=CAPABILITIES,
            bounds=BOUNDS,
            descriptor_config=DESCRIPTORS,
            confirmation_config=CONFIRMATION,
            realization_seeds=SEEDS,
            iterations=4,
            batch_size=12,
        )
        return algorithm, summary

    algorithm, summary = execute()
    repeated_algorithm, repeated_summary = execute()

    assert summary == repeated_summary
    assert algorithm.state_dict() == repeated_algorithm.state_dict()
    assert summary.candidate_count == 48
    assert summary.realization_run_count == 144
    assert summary.pareto_front_size >= 2
    assert len(summary.unique_failure_mechanisms) >= 2
    assert all(item.pareto_rank == 0 for item in algorithm.population)


def test_map_elites_niche_assignment_uses_specified_buckets() -> None:
    evaluation = _niche_evaluation(
        _evaluations(1, seed=500)[0],
        affected_fraction=0.5,
        onset=0.5,
        incomplete=0.6,
    )

    niche = map_elites_niche(
        evaluation,
        robot_count=2,
        config=MapElitesConfig(),
    )

    assert niche.affected_robot_count == AffectedRobotBucket.ONE
    assert niche.onset == OnsetBucket.MIDDLE
    assert niche.incomplete_tasks == IncompleteTaskBucket.MEDIUM
    assert niche.key == "deadlock|1|middle|medium"


def test_map_elites_replacement_duplicate_and_infrastructure_safeguards() -> None:
    raw = _evaluations(4, seed=600)
    archive = MapElitesArchive(robot_count=2, config=MapElitesConfig())
    lower = _niche_evaluation(raw[0], severity=4, reproducibility=0.9, complexity=0.4)
    higher = _niche_evaluation(raw[1], severity=6, reproducibility=0.8, complexity=0.7)
    duplicate_runs = tuple(
        run.model_copy(update={"phenotype_hash": higher.runs[index].phenotype_hash})
        for index, run in enumerate(raw[2].runs)
    )
    duplicate = _niche_evaluation(
        raw[2].model_copy(update={"runs": duplicate_runs}),
        mechanism=FailureMechanism.TASK_STARVATION,
        severity=9,
    )
    invalid_runs = tuple(
        run.model_copy(
            update={
                "state": EvaluationState.CLEANUP_FAILURE,
                "severity_score": 0.0,
            }
        )
        for run in raw[3].runs
    )
    invalid = _niche_evaluation(
        raw[3].model_copy(update={"runs": invalid_runs}),
        severity=10,
    )

    first = archive.consider(lower)
    replacement = archive.consider(higher)
    duplicate_decision = archive.consider(duplicate)
    invalid_decision = archive.consider(invalid)
    report = archive.report()

    assert first.reason == ArchiveInsertionReason.INSERTED_EMPTY
    assert replacement.reason == ArchiveInsertionReason.REPLACED_LOWER_QUALITY
    assert duplicate_decision.reason == ArchiveInsertionReason.DUPLICATE_PHENOTYPE
    assert invalid_decision.reason == ArchiveInsertionReason.INELIGIBLE
    assert report.occupied_cell_count == 1
    assert report.replacement_count == 1
    assert report.quality_diversity_score == 6


def test_map_elites_search_covers_niches_and_resumes_deterministically() -> None:
    algorithm_config = GeneticAlgorithmConfig(
        search_seed=8400,
        population_size=12,
        offspring_size=12,
        tournament_size=3,
    )

    def execute():
        algorithm = MapElitesAlgorithm(
            capabilities=CAPABILITIES,
            bounds=BOUNDS,
            config=algorithm_config,
        )
        summary = run_search(
            algorithm,
            evaluator=DeterministicFakeEvaluator(CAPABILITIES),
            capabilities=CAPABILITIES,
            bounds=BOUNDS,
            descriptor_config=DESCRIPTORS,
            confirmation_config=CONFIRMATION,
            realization_seeds=SEEDS,
            iterations=4,
            batch_size=12,
        )
        return algorithm, summary

    algorithm, summary = execute()
    repeated_algorithm, repeated_summary = execute()
    report = algorithm.archive_report()

    assert summary == repeated_summary
    assert algorithm.archive.state_dict() == repeated_algorithm.archive.state_dict()
    assert report.occupied_cell_count >= 4
    assert len(report.coverage_by_mechanism) >= 2
    assert report.quality_diversity_score > 0
    assert summary.archive_report == report.model_dump(mode="json")

    state = json.loads(json.dumps(algorithm.state_dict()))
    resumed = MapElitesAlgorithm(
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
        config=algorithm_config,
    )
    resumed.load_state_dict(state)
    assert resumed.archive_report() == report
    assert resumed.ask(6) == algorithm.ask(6)


def test_elite_replay_hook_reports_verified_and_missing_references(tmp_path: Path) -> None:
    raw = _evaluations(2, seed=920)
    package = tmp_path / "replay-package"
    package.mkdir()
    with_reference = _niche_evaluation(raw[0])
    with_reference = with_reference.model_copy(
        update={
            "runs": tuple(
                run.model_copy(update={"run_path": str(package)}) for run in with_reference.runs
            )
        }
    )
    without_reference = _niche_evaluation(
        raw[1],
        mechanism=FailureMechanism.TASK_STARVATION,
    )
    archive = MapElitesArchive(robot_count=2, config=MapElitesConfig())
    archive.consider(with_reference)
    archive.consider(without_reference)

    class FakeReplayVerifier:
        def verify(self, package_dir: Path):
            return {"verified": package_dir == package.resolve()}

    report = verify_elite_replays(archive, verifier=FakeReplayVerifier())

    assert report.total_elites == 2
    assert report.references_checked == 1
    assert report.verified_count == 1
    assert report.missing_reference_count == 1
    assert report.failed_count == 0
