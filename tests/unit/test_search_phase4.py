from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from adversarial_fleet.config import AppConfig, ProjectConfig
from adversarial_fleet.failures.models import FailureReport, FailureType
from adversarial_fleet.orchestrator.runner import RunResult
from adversarial_fleet.scenarios import ScenarioCapabilities
from adversarial_fleet.search.cache import (
    CachingEvaluator,
    EvaluationCache,
    EvaluationCacheContext,
)
from adversarial_fleet.search.config import (
    ConfirmationConfig,
    DescriptorConfig,
    GenomeBounds,
    SearchExecutionConfig,
    SearchFileConfig,
    SearchSettings,
    load_search_config,
)
from adversarial_fleet.search.evaluation import EvaluationState, FailureMechanism
from adversarial_fleet.search.evaluator import DeterministicFakeEvaluator
from adversarial_fleet.search.live_evaluator import LiveCandidateEvaluator
from adversarial_fleet.search.runner import SearchRunner
from adversarial_fleet.search.variation import sample_genome


CAPABILITIES = ScenarioCapabilities()
BOUNDS = GenomeBounds()


def _genome(seed: int = 100):
    return sample_genome(
        random.Random(seed),
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
    )


def _search_config(
    *,
    search_id: str,
    budget: int = 8,
    reuse_cache: bool = False,
) -> SearchFileConfig:
    return SearchFileConfig(
        search=SearchSettings(
            algorithm="map_elites",
            search_id=search_id,
            search_seed=9901,
            evaluation_budget=budget,
            population_size=4,
            offspring_size=4,
            tournament_size=2,
            realization_seeds=(1042, 1043, 1044),
        ),
        descriptor=DescriptorConfig(novelty_k=3),
        confirmation=ConfirmationConfig(confirm_all=True),
        execution=SearchExecutionConfig(
            evaluator="fake",
            reuse_cache=reuse_cache,
            verify_elites=False,
            maximum_elite_replays=0,
        ),
    )


def test_live_evaluator_converts_run_result_and_cleanup_evidence(tmp_path: Path) -> None:
    genome = _genome()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "timestamp": 12.0,
                        "event": "task_starved",
                        "robot_id": "tinyRobot1",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": 13.0,
                        "event": "robot_state",
                        "robot_id": "tinyRobot2",
                        "task_active": True,
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "cleanup_error": None,
                "orphan_process_count": 0,
            }
        ),
        encoding="utf-8",
    )
    failure = FailureReport(
        is_failure=True,
        failure_type=FailureType.TASK_STARVATION,
        severity=0.8,
        confidence=0.9,
        evidence={"affected_robots": ["tinyRobot1"]},
    )
    result = RunResult(
        run_id="run",
        run_dir=run_dir,
        status="failure",
        metrics={
            "tasks_submitted": 4.0,
            "tasks_completed": 2.0,
            "incomplete_task_ratio": 0.5,
            "p95_task_latency": 100.0,
            "task_starvation_count": 1.0,
            "simulation_runtime": 30.0,
            "wall_clock_runtime": 1.0,
        },
        fitness={"score": 3.0},
        failure=failure,
    )

    class FakeOrchestrator:
        def run(self, scenario, candidate_id="candidate_0000"):
            return result

    evaluator = LiveCandidateEvaluator(
        app_config=AppConfig(project=ProjectConfig(output_dir=tmp_path)),
        capabilities=CAPABILITIES,
        orchestrator=FakeOrchestrator(),
    )
    evaluation = evaluator.evaluate(
        genome,
        realization_seed=1042,
        candidate_id=genome.digest(),
    )

    assert evaluation.state == EvaluationState.VALID_FAILURE
    assert evaluation.failure_mechanism == FailureMechanism.TASK_STARVATION
    assert evaluation.failure_onset_seconds == 12.0
    assert evaluation.affected_robot_ids == ("tinyRobot1",)
    assert evaluation.affected_robot_data_available
    assert evaluation.severity_score > 0
    assert evaluation.run_path == str(run_dir.resolve())
    assert evaluation.orphan_process_count == 0

    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "cleanup_error": None,
                "orphan_process_count": 1,
            }
        ),
        encoding="utf-8",
    )
    cleanup = evaluator.evaluate(
        genome,
        realization_seed=1043,
        candidate_id=genome.digest(),
    )
    assert cleanup.state == EvaluationState.CLEANUP_FAILURE
    assert cleanup.severity_score == 0
    assert cleanup.orphan_process_count == 1


def test_evaluation_cache_reuses_only_matching_valid_context(tmp_path: Path) -> None:
    genome = _genome(101)
    delegate = DeterministicFakeEvaluator(CAPABILITIES)
    cache = EvaluationCache(tmp_path / "cache")
    context = EvaluationCacheContext(
        environment_image_digest="image@sha256:abc",
        metric_configuration_hash="a" * 64,
        failure_detector_configuration_hash="b" * 64,
        defender_id="baseline",
    )
    evaluator = CachingEvaluator(
        delegate,
        cache=cache,
        context=context,
        capabilities=CAPABILITIES,
    )

    first = evaluator.evaluate(
        genome,
        realization_seed=1042,
        candidate_id=genome.digest(),
    )
    repeated = evaluator.evaluate(
        genome,
        realization_seed=1042,
        candidate_id=genome.digest(),
    )

    assert first == repeated
    assert delegate.evaluation_count == 1
    assert evaluator.cache_hit_count == 1

    changed_context = CachingEvaluator(
        delegate,
        cache=cache,
        context=context.model_copy(update={"defender_id": "changed"}),
        capabilities=CAPABILITIES,
    )
    changed_context.evaluate(
        genome,
        realization_seed=1042,
        candidate_id=genome.digest(),
    )
    assert delegate.evaluation_count == 2
    assert changed_context.cache_hit_count == 0


def test_search_runner_uses_exact_budget_and_writes_review_artifacts(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    runner = SearchRunner(
        app_config=AppConfig(project=ProjectConfig(output_dir=output)),
        search_config=_search_config(search_id="artifact-test"),
        capabilities=CAPABILITIES,
    )

    report = runner.run()
    search_dir = output / "searches" / "artifact-test"

    assert report.status == "completed"
    assert report.measures.candidate_count == 8
    assert report.measures.realization_evaluation_count == 24
    assert report.completed_generations == 2
    assert report.measures.infrastructure_failure_count == 0
    assert report.measures.cleanup_failure_count == 0
    assert report.measures.orphan_process_count == 0
    assert len(report.generations) == 2
    assert set(report.measures.objective_correlations) == {
        "severity__novelty",
        "severity__reproducibility",
        "severity__complexity",
        "novelty__reproducibility",
        "novelty__complexity",
        "reproducibility__complexity",
    }
    required = {
        "search_config.yaml",
        "simulator_config.yaml",
        "environment.json",
        "capabilities.json",
        "manifest.json",
        "candidates.jsonl",
        "evaluations.jsonl",
        "archive.json",
        "novelty_archive.json",
        "checkpoints",
        "run_references",
        "summary.json",
    }
    assert required <= {path.name for path in search_dir.iterdir()}
    assert len((search_dir / "candidates.jsonl").read_text().splitlines()) == 8
    assert len((search_dir / "evaluations.jsonl").read_text().splitlines()) == 8
    manifest = json.loads((search_dir / "manifest.json").read_text())
    assert manifest["status"] == "completed"
    assert manifest["completed_candidate_count"] == 8


def test_interrupted_resume_matches_uninterrupted_candidate_and_archive_state(
    tmp_path: Path,
) -> None:
    config = _search_config(search_id="resume-test")
    interrupted_output = tmp_path / "interrupted"
    interrupted_runner = SearchRunner(
        app_config=AppConfig(project=ProjectConfig(output_dir=interrupted_output)),
        search_config=config,
        capabilities=CAPABILITIES,
    )
    partial = interrupted_runner.run(stop_after_candidates=4)
    assert partial.status == "interrupted"
    assert partial.measures.candidate_count == 4

    search_dir = interrupted_output / "searches" / "resume-test"
    resumed_runner = SearchRunner.resume(
        search_dir,
        evaluator=DeterministicFakeEvaluator(CAPABILITIES),
    )
    resumed = resumed_runner.run(resume=True)

    uninterrupted_output = tmp_path / "uninterrupted"
    uninterrupted_runner = SearchRunner(
        app_config=AppConfig(project=ProjectConfig(output_dir=uninterrupted_output)),
        search_config=config,
        capabilities=CAPABILITIES,
    )
    uninterrupted = uninterrupted_runner.run()

    assert resumed.status == "completed"
    assert resumed.measures.model_dump(
        exclude={"wall_clock_runtime_seconds"}
    ) == uninterrupted.measures.model_dump(exclude={"wall_clock_runtime_seconds"})
    assert resumed.generations == uninterrupted.generations
    assert (search_dir / "candidates.jsonl").read_text() == (
        uninterrupted_output / "searches" / "resume-test" / "candidates.jsonl"
    ).read_text()
    assert (search_dir / "evaluations.jsonl").read_text() == (
        uninterrupted_output / "searches" / "resume-test" / "evaluations.jsonl"
    ).read_text()
    resumed_archive = json.loads((search_dir / "archive.json").read_text())
    uninterrupted_archive = json.loads(
        (uninterrupted_output / "searches" / "resume-test" / "archive.json").read_text()
    )
    assert resumed_archive == uninterrupted_archive


def test_search_configuration_requires_a_complete_common_seed_set() -> None:
    with pytest.raises(ValidationError, match="realization seed count"):
        SearchFileConfig(
            search=SearchSettings(realization_seeds=(1042,)),
            confirmation=ConfirmationConfig(total_runs=3),
        )


def test_phase4_fake_review_exposes_convergence_indicators(tmp_path: Path) -> None:
    loaded = load_search_config(Path("configs/search/phase4_fake_review.yaml"))
    config = loaded.model_copy(
        update={"search": loaded.search.model_copy(update={"search_id": "phase4-review-test"})}
    )
    runner = SearchRunner(
        app_config=AppConfig(project=ProjectConfig(output_dir=tmp_path / "review")),
        search_config=config,
        capabilities=CAPABILITIES,
    )

    report = runner.run()

    assert report.measures.candidate_count == 48
    assert report.measures.confirmed_failure_count == 39
    assert report.measures.posthoc_map_elites.occupied_cell_count == 5
    assert len(report.measures.unique_failure_mechanisms) == 3
    assert report.measures.mechanism_dominance_ratio > 0.5
    assert report.generations[-1].mean_novelty < report.generations[0].mean_novelty
    assert report.generations[2].mean_complexity > report.generations[0].mean_complexity
    assert "latency_degradation" not in report.generations[-1].failure_mechanism_counts
    assert report.measures.genome_observed_ranges["task_count"] == (1.0, 20.0)
