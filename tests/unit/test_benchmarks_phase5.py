from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from adversarial_fleet.benchmarks.config import (
    REQUIRED_ALGORITHMS,
    BenchmarkFileConfig,
    BenchmarkSearchSettings,
    BenchmarkSettings,
)
from adversarial_fleet.benchmarks.runner import BenchmarkRunner
from adversarial_fleet.benchmarks.statistics import (
    bootstrap_confidence_interval,
    paired_comparison,
    summarize,
)
from adversarial_fleet.cli import build_parser
from adversarial_fleet.config import AppConfig, ProjectConfig
from adversarial_fleet.search.config import ConfirmationConfig, SearchExecutionConfig


def _benchmark_config(*, benchmark_id: str) -> BenchmarkFileConfig:
    return BenchmarkFileConfig(
        benchmark=BenchmarkSettings(
            benchmark_id=benchmark_id,
            algorithms=REQUIRED_ALGORITHMS,
            search_seeds=(8101, 8102),
            evaluation_budget=6,
            budget_checkpoints=(3, 6),
            bootstrap_resamples=100,
            analysis_seed=44,
        ),
        search=BenchmarkSearchSettings(
            population_size=3,
            offspring_size=3,
            tournament_size=2,
            realization_seeds=(1042, 1043),
        ),
        confirmation=ConfirmationConfig(
            total_runs=2,
            minimum_valid_runs=2,
            confirm_all=True,
        ),
        execution=SearchExecutionConfig(
            evaluator="fake",
            reuse_cache=False,
            verify_elites=False,
            maximum_elite_replays=0,
        ),
    )


def test_benchmark_config_enforces_complete_fair_design() -> None:
    with pytest.raises(ValidationError, match="missing"):
        BenchmarkSettings(
            algorithms=("random_search",),
            search_seeds=(1, 2),
            evaluation_budget=4,
            budget_checkpoints=(4,),
        )


def test_benchmark_cli_accepts_reproduction_output_directory() -> None:
    args = build_parser().parse_args(
        [
            "benchmark",
            "--benchmark-config",
            "persisted-benchmark.yaml",
            "--config",
            "persisted-simulator.yaml",
            "--output",
            "new-results",
        ]
    )

    assert args.command == "benchmark"
    assert args.output == Path("new-results")
    with pytest.raises(ValidationError, match="unique"):
        BenchmarkSettings(search_seeds=(1, 1))
    with pytest.raises(ValidationError, match="final budget checkpoint"):
        BenchmarkSettings(evaluation_budget=10, budget_checkpoints=(5,))
    with pytest.raises(ValidationError, match="baseline_algorithm"):
        BenchmarkSettings(
            algorithms=("severity_ga",),
            search_seeds=(1, 2),
            evaluation_budget=4,
            budget_checkpoints=(4,),
            require_complete_suite=False,
        )


def test_bootstrap_and_paired_statistics_are_deterministic() -> None:
    values = [1.0, 2.0, 9.0, 10.0]
    first = bootstrap_confidence_interval(
        values,
        confidence_level=0.95,
        resamples=250,
        seed=50,
    )
    second = bootstrap_confidence_interval(
        values,
        confidence_level=0.95,
        resamples=250,
        seed=50,
    )
    assert first == second

    summary = summarize(
        values,
        confidence_level=0.95,
        resamples=250,
        seed=51,
    )
    assert summary.median == 5.5
    assert summary.percentile_25 == 1.75
    assert summary.percentile_75 == 9.25

    comparison = paired_comparison(
        algorithm="map_elites",
        baseline_algorithm="random_search",
        budget_checkpoint=10,
        metric="coverage",
        direction="higher",
        algorithm_values={1: 0.3, 2: 0.2, 3: 0.4},
        baseline_values={1: 0.1, 2: 0.2, 3: 0.3},
        confidence_level=0.95,
        resamples=250,
        seed=52,
    )
    assert comparison.pair_count == 3
    assert (comparison.wins, comparison.ties, comparison.losses) == (2, 1, 0)
    assert comparison.median_difference == pytest.approx(0.1)


def test_benchmark_runner_executes_equal_budgets_and_persists_report(
    tmp_path: Path,
) -> None:
    config = _benchmark_config(benchmark_id="phase5-test")
    output = tmp_path / "output"
    runner = BenchmarkRunner(
        app_config=AppConfig(project=ProjectConfig(output_dir=output)),
        benchmark_config=config,
    )

    report = runner.run()
    root = output / "benchmarks" / "phase5-test"

    assert report.status == "completed"
    assert report.completed_search_count == 10
    assert report.failed_search_count == 0
    assert report.total_candidate_budget == 60
    assert report.total_candidates_evaluated == 60
    assert report.total_realization_evaluations == 120
    assert len(report.search_records) == 10
    assert len(report.observations) == 20
    assert len(report.aggregates) == 200
    assert len(report.paired_comparisons) == 160
    assert all(
        item.measures.candidate_count == item.budget_checkpoint for item in report.observations
    )
    assert all(
        item.measures.infrastructure_failure_count == 0
        and item.measures.cleanup_failure_count == 0
        and item.measures.orphan_process_count == 0
        for item in report.observations
    )
    assert {item.search_seed for item in report.search_records} == set(
        config.benchmark.search_seeds
    )
    assert {item.algorithm for item in report.search_records} == set(config.benchmark.algorithms)

    required_artifacts = {
        "benchmark_config.yaml",
        "simulator_config.yaml",
        "capabilities.json",
        "environment.json",
        "fairness_manifest.json",
        "observations.json",
        "aggregates.json",
        "paired_comparisons.json",
        "summary.json",
        "manifest.json",
        "report.md",
    }
    assert required_artifacts <= {path.name for path in root.iterdir()}
    fairness = json.loads((root / "fairness_manifest.json").read_text(encoding="utf-8"))
    assert fairness["ordered_realization_seeds"] == [1042, 1043]
    assert fairness["fairness_controls"]["cache_initial_state"] == (
        "empty_isolated_per_algorithm_seed"
    )
    markdown = (root / "report.md").read_text(encoding="utf-8")
    assert "not evidence of live Open-RMF algorithm performance" in markdown
    assert "no hypothesis test" in markdown

    for search_record in report.search_records:
        search_dir = Path(search_record.search_directory)
        search_summary = json.loads((search_dir / "summary.json").read_text(encoding="utf-8"))
        search_manifest = json.loads((search_dir / "manifest.json").read_text(encoding="utf-8"))
        assert search_summary["measures"]["candidate_count"] == 6
        assert search_manifest["realization_seeds"] == [1042, 1043]


def test_fake_benchmark_scientific_result_is_reproducible(tmp_path: Path) -> None:
    app_config = AppConfig(project=ProjectConfig(output_dir=tmp_path / "output"))
    first = BenchmarkRunner(
        app_config=app_config,
        benchmark_config=_benchmark_config(benchmark_id="repro-a"),
    ).run()
    second = BenchmarkRunner(
        app_config=app_config,
        benchmark_config=_benchmark_config(benchmark_id="repro-b"),
    ).run()

    assert first.scientific_result_fingerprint == second.scientific_result_fingerprint
    assert [
        (item.algorithm, item.search_seed, item.candidate_sequence_hash)
        for item in first.search_records
    ] == [
        (item.algorithm, item.search_seed, item.candidate_sequence_hash)
        for item in second.search_records
    ]
    first_core = [
        (
            item.algorithm,
            item.search_seed,
            item.budget_checkpoint,
            item.measures.model_dump(exclude={"wall_clock_runtime_seconds"}),
        )
        for item in first.observations
    ]
    second_core = [
        (
            item.algorithm,
            item.search_seed,
            item.budget_checkpoint,
            item.measures.model_dump(exclude={"wall_clock_runtime_seconds"}),
        )
        for item in second.observations
    ]
    assert first_core == second_core
