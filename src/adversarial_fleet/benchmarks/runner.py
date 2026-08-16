from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from adversarial_fleet.config import AppConfig
from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities
from adversarial_fleet.search.artifacts import _atomic_json
from adversarial_fleet.search.cache import configuration_hash, runtime_environment_digest
from adversarial_fleet.search.config import SearchFileConfig, SearchSettings
from adversarial_fleet.search.evaluation import AggregateEvaluation
from adversarial_fleet.search.models import SearchModel
from adversarial_fleet.search.reporting import SearchMeasures, calculate_search_measures
from adversarial_fleet.search.runner import SearchRunner

from .config import AlgorithmName, BenchmarkFileConfig
from .statistics import (
    MetricAggregate,
    MetricDirection,
    PairedComparison,
    paired_comparison,
    summarize,
    summary_seed,
)


BenchmarkStatus = Literal["completed", "failed"]


class BenchmarkObservation(SearchModel):
    algorithm: AlgorithmName
    search_seed: int = Field(ge=0)
    budget_checkpoint: int = Field(ge=1)
    search_status: str
    measures: SearchMeasures
    time_to_first_qualified_failure_seconds: float | None = Field(default=None, ge=0)


class BenchmarkSearchRecord(SearchModel):
    algorithm: AlgorithmName
    search_seed: int = Field(ge=0)
    status: str
    candidate_sequence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    search_directory: str


class BenchmarkRunReport(SearchModel):
    benchmark_id: str
    status: BenchmarkStatus
    evaluator: str
    fairness_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    design_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_result_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    algorithm_count: int = Field(ge=1)
    search_seed_count: int = Field(ge=2)
    completed_search_count: int = Field(ge=0)
    failed_search_count: int = Field(ge=0)
    evaluation_budget_per_search: int = Field(ge=1)
    total_candidate_budget: int = Field(ge=1)
    total_candidates_evaluated: int = Field(ge=0)
    total_realization_evaluations: int = Field(ge=0)
    search_records: tuple[BenchmarkSearchRecord, ...]
    observations: tuple[BenchmarkObservation, ...]
    aggregates: tuple[MetricAggregate, ...]
    paired_comparisons: tuple[PairedComparison, ...]
    wall_clock_runtime_seconds: float = Field(ge=0)
    benchmark_directory: str
    report_path: str


METRIC_DIRECTIONS: dict[str, MetricDirection] = {
    "evaluations_to_first_qualified_failure": "lower",
    "time_to_first_qualified_failure_seconds": "lower",
    "qualified_failure_discovered": "higher",
    "best_robust_severity": "higher",
    "confirmed_failure_count": "higher",
    "unique_confirmed_behavior_count": "higher",
    "unique_failure_mechanism_count": "higher",
    "map_elites_coverage": "higher",
    "quality_diversity_score": "higher",
    "novelty_archive_size": "higher",
    "behavioral_evenness": "higher",
    "mean_reproducibility": "higher",
    "median_elite_complexity": "lower",
    "infrastructure_failure_count": "lower",
    "cleanup_failure_count": "lower",
    "orphan_process_count": "lower",
    "executed_realization_count": "lower",
    "cache_hit_count": "higher",
    "simulation_runtime_seconds": "lower",
    "wall_clock_runtime_seconds": "lower",
}


def _benchmark_id(config: BenchmarkFileConfig) -> str:
    if config.benchmark.benchmark_id is not None:
        return config.benchmark.benchmark_id
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    return f"benchmark_{stamp}"


def _hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _candidate_sequence_hash(records: list[dict[str, Any]]) -> str:
    return _hash([record["evaluation"]["candidate_id"] for record in records])


def _metric_values(
    observation: BenchmarkObservation,
) -> dict[str, tuple[float, bool]]:
    measures = observation.measures
    first_failure = measures.first_qualified_failure_candidate
    censored = first_failure is None
    first_failure_value = (
        float(observation.budget_checkpoint + 1) if first_failure is None else float(first_failure)
    )
    first_failure_time = (
        measures.wall_clock_runtime_seconds
        if observation.time_to_first_qualified_failure_seconds is None
        else observation.time_to_first_qualified_failure_seconds
    )
    return {
        "evaluations_to_first_qualified_failure": (first_failure_value, censored),
        "time_to_first_qualified_failure_seconds": (first_failure_time, censored),
        "qualified_failure_discovered": (0.0 if censored else 1.0, False),
        "best_robust_severity": (measures.best_robust_severity, False),
        "confirmed_failure_count": (float(measures.confirmed_failure_count), False),
        "unique_confirmed_behavior_count": (
            float(measures.unique_confirmed_behavior_count),
            False,
        ),
        "unique_failure_mechanism_count": (
            float(len(measures.unique_failure_mechanisms)),
            False,
        ),
        "map_elites_coverage": (measures.posthoc_map_elites.coverage_ratio, False),
        "quality_diversity_score": (
            measures.posthoc_map_elites.quality_diversity_score,
            False,
        ),
        "novelty_archive_size": (float(measures.novelty_archive_size), False),
        "behavioral_evenness": (measures.behavioral_evenness, False),
        "mean_reproducibility": (measures.reproducibility.mean, False),
        "median_elite_complexity": (measures.elite_complexity.median, False),
        "infrastructure_failure_count": (
            float(measures.infrastructure_failure_count),
            False,
        ),
        "cleanup_failure_count": (float(measures.cleanup_failure_count), False),
        "orphan_process_count": (float(measures.orphan_process_count), False),
        "executed_realization_count": (
            float(measures.executed_realization_count),
            False,
        ),
        "cache_hit_count": (float(measures.cache_hit_count), False),
        "simulation_runtime_seconds": (measures.simulation_runtime_seconds, False),
        "wall_clock_runtime_seconds": (measures.wall_clock_runtime_seconds, False),
    }


def _scientific_result_fingerprint(
    observations: list[BenchmarkObservation],
    search_records: list[BenchmarkSearchRecord],
) -> str:
    values: list[dict[str, Any]] = []
    for observation in observations:
        measures = observation.measures.model_dump(mode="json")
        measures.pop("wall_clock_runtime_seconds")
        values.append(
            {
                "algorithm": observation.algorithm,
                "search_seed": observation.search_seed,
                "budget_checkpoint": observation.budget_checkpoint,
                "search_status": observation.search_status,
                "measures": measures,
            }
        )
    return _hash(
        {
            "observations": values,
            "candidate_sequence_hashes": [
                {
                    "algorithm": item.algorithm,
                    "search_seed": item.search_seed,
                    "status": item.status,
                    "candidate_sequence_hash": item.candidate_sequence_hash,
                }
                for item in search_records
            ],
        }
    )


class BenchmarkRunner:
    def __init__(
        self,
        *,
        app_config: AppConfig,
        benchmark_config: BenchmarkFileConfig,
        capabilities: ScenarioCapabilities | None = None,
        benchmark_directory: Path | None = None,
    ) -> None:
        self.app_config = app_config
        self.config = benchmark_config
        self.capabilities = capabilities or ScenarioCapabilities()
        self.benchmark_id = _benchmark_id(benchmark_config)
        self.benchmark_directory = (
            benchmark_directory.resolve()
            if benchmark_directory is not None
            else (app_config.project.output_dir.resolve() / "benchmarks" / self.benchmark_id)
        )

    def _search_config(
        self,
        algorithm: AlgorithmName,
        search_seed: int,
    ) -> SearchFileConfig:
        shared = self.config.search
        execution = self.config.execution.model_copy(
            update={
                "cache_directory": (
                    self.benchmark_directory / "cache_state" / algorithm / f"seed_{search_seed}"
                )
            }
        )
        return SearchFileConfig(
            search=SearchSettings(
                algorithm=algorithm,
                search_seed=search_seed,
                evaluation_budget=self.config.benchmark.evaluation_budget,
                population_size=shared.population_size,
                offspring_size=shared.offspring_size,
                tournament_size=shared.tournament_size,
                checkpoint_interval=shared.checkpoint_interval,
                realization_seeds=shared.realization_seeds,
            ),
            genome=self.config.genome,
            descriptor=self.config.descriptor,
            confirmation=self.config.confirmation,
            map_elites=self.config.map_elites,
            execution=execution,
        )

    def _fairness_payload(self) -> dict[str, Any]:
        return {
            "capabilities_version": self.capabilities.version,
            "capabilities_hash": self.capabilities.digest(),
            "genome": self.config.genome.model_dump(mode="json"),
            "descriptor": self.config.descriptor.model_dump(mode="json"),
            "confirmation": self.config.confirmation.model_dump(mode="json"),
            "map_elites": self.config.map_elites.model_dump(mode="json"),
            "search": self.config.search.model_dump(mode="json"),
            "evaluation_budget": self.config.benchmark.evaluation_budget,
            "execution": {
                key: value
                for key, value in self.config.execution.model_dump(mode="json").items()
                if key != "cache_directory"
            },
            "cache_initial_state": "empty_isolated_per_algorithm_seed",
            "app_config": self.app_config.model_dump(mode="json"),
            "environment_image_digest": runtime_environment_digest(),
        }

    def _initialize(self) -> tuple[str, str]:
        if self.benchmark_directory.exists() and any(self.benchmark_directory.iterdir()):
            raise FileExistsError(
                f"benchmark directory already exists and is not empty: {self.benchmark_directory}"
            )
        self.benchmark_directory.mkdir(parents=True, exist_ok=True)
        (self.benchmark_directory / "searches").mkdir()
        (self.benchmark_directory / "cache_state").mkdir()
        (self.benchmark_directory / "benchmark_config.yaml").write_text(
            yaml.safe_dump(self.config.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
        (self.benchmark_directory / "simulator_config.yaml").write_text(
            yaml.safe_dump(self.app_config.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
        _atomic_json(
            self.benchmark_directory / "capabilities.json",
            self.capabilities.normalized(),
        )
        fairness = self._fairness_payload()
        fairness_fingerprint = configuration_hash(fairness)
        design_fingerprint = configuration_hash(self.config)
        _atomic_json(
            self.benchmark_directory / "fairness_manifest.json",
            {
                "schema_version": 1,
                "benchmark_id": self.benchmark_id,
                "fairness_fingerprint": fairness_fingerprint,
                "design_fingerprint": design_fingerprint,
                "algorithms": list(self.config.benchmark.algorithms),
                "search_seeds": list(self.config.benchmark.search_seeds),
                "ordered_realization_seeds": list(self.config.search.realization_seeds),
                "budget_checkpoints": list(self.config.benchmark.budget_checkpoints),
                "fairness_controls": fairness,
            },
        )
        return fairness_fingerprint, design_fingerprint

    def _observations(
        self,
        *,
        algorithm: AlgorithmName,
        search_seed: int,
        runner: SearchRunner,
        search_status: str,
        final_measures: SearchMeasures,
    ) -> list[BenchmarkObservation]:
        records = runner.store.load_evaluation_records()
        evaluations = [
            AggregateEvaluation.model_validate(record["evaluation"]) for record in records
        ]
        output: list[BenchmarkObservation] = []
        for checkpoint in self.config.benchmark.budget_checkpoints:
            if checkpoint > len(evaluations):
                break
            prefix = evaluations[:checkpoint]
            if checkpoint == len(evaluations):
                measures = final_measures
            else:
                last_record = records[checkpoint - 1]
                measures = calculate_search_measures(
                    prefix,
                    robot_count=self.capabilities.supported_robot_count,
                    map_config=self.config.map_elites,
                    cache_hit_count=int(last_record.get("cumulative_cache_hit_count", 0)),
                    wall_clock_runtime_seconds=float(
                        last_record.get("wall_clock_elapsed_seconds", 0.0)
                    ),
                )
            first_index = measures.first_qualified_failure_candidate
            first_time = (
                None
                if first_index is None
                else float(records[first_index - 1].get("wall_clock_elapsed_seconds", 0.0))
            )
            output.append(
                BenchmarkObservation(
                    algorithm=algorithm,
                    search_seed=search_seed,
                    budget_checkpoint=checkpoint,
                    search_status=search_status,
                    measures=measures,
                    time_to_first_qualified_failure_seconds=first_time,
                )
            )
        return output

    def _analyze(
        self,
        observations: list[BenchmarkObservation],
    ) -> tuple[list[MetricAggregate], list[PairedComparison]]:
        grouped: dict[tuple[str, int, str], list[tuple[int, float, bool]]] = defaultdict(list)
        for observation in observations:
            for metric, (value, censored) in _metric_values(observation).items():
                grouped[(observation.algorithm, observation.budget_checkpoint, metric)].append(
                    (observation.search_seed, value, censored)
                )

        aggregates: list[MetricAggregate] = []
        for (algorithm, checkpoint, metric), rows in sorted(grouped.items()):
            values = [value for _, value, _ in rows]
            aggregates.append(
                MetricAggregate(
                    algorithm=algorithm,
                    budget_checkpoint=checkpoint,
                    metric=metric,
                    direction=METRIC_DIRECTIONS[metric],
                    summary=summarize(
                        values,
                        confidence_level=self.config.benchmark.confidence_level,
                        resamples=self.config.benchmark.bootstrap_resamples,
                        seed=summary_seed(
                            self.config.benchmark.analysis_seed,
                            algorithm=algorithm,
                            checkpoint=checkpoint,
                            metric=metric,
                        ),
                    ),
                    censored_count=sum(censored for _, _, censored in rows),
                )
            )

        baseline = self.config.benchmark.baseline_algorithm
        paired: list[PairedComparison] = []
        for algorithm in self.config.benchmark.algorithms:
            if algorithm == baseline:
                continue
            for checkpoint in self.config.benchmark.budget_checkpoints:
                for metric, direction in METRIC_DIRECTIONS.items():
                    algorithm_rows = grouped.get((algorithm, checkpoint, metric), [])
                    baseline_rows = grouped.get((baseline, checkpoint, metric), [])
                    algorithm_values = {seed: value for seed, value, _ in algorithm_rows}
                    baseline_values = {seed: value for seed, value, _ in baseline_rows}
                    if not (set(algorithm_values) & set(baseline_values)):
                        continue
                    paired.append(
                        paired_comparison(
                            algorithm=algorithm,
                            baseline_algorithm=baseline,
                            budget_checkpoint=checkpoint,
                            metric=metric,
                            direction=direction,
                            algorithm_values=algorithm_values,
                            baseline_values=baseline_values,
                            confidence_level=self.config.benchmark.confidence_level,
                            resamples=self.config.benchmark.bootstrap_resamples,
                            seed=self.config.benchmark.analysis_seed,
                        )
                    )
        return aggregates, paired

    def _markdown_report(
        self,
        *,
        status: BenchmarkStatus,
        fairness_fingerprint: str,
        search_records: list[BenchmarkSearchRecord],
        aggregates: list[MetricAggregate],
        paired_comparisons: list[PairedComparison],
        runtime_seconds: float,
    ) -> str:
        final_checkpoint = self.config.benchmark.evaluation_budget
        selected_metrics = (
            "best_robust_severity",
            "unique_confirmed_behavior_count",
            "unique_failure_mechanism_count",
            "map_elites_coverage",
            "quality_diversity_score",
            "mean_reproducibility",
        )
        lookup = {
            (item.algorithm, item.budget_checkpoint, item.metric): item for item in aggregates
        }
        lines = [
            f"# Benchmark report: {self.benchmark_id}",
            "",
            f"- Status: `{status}`",
            f"- Evaluator: `{self.config.execution.evaluator}`",
            f"- Algorithms: {', '.join(self.config.benchmark.algorithms)}",
            f"- Search seeds: {', '.join(map(str, self.config.benchmark.search_seeds))}",
            f"- Candidate budget per search: {self.config.benchmark.evaluation_budget}",
            f"- Fairness fingerprint: `{fairness_fingerprint}`",
            f"- Coordinator wall time: {runtime_seconds:.6f} seconds",
            "",
        ]
        if self.config.execution.evaluator == "fake":
            lines.extend(
                [
                    "> This is a deterministic fake-evaluator smoke benchmark. "
                    "It is not evidence of live Open-RMF algorithm performance.",
                    "",
                ]
            )
        lines.extend(
            [
                "## Equal-budget completion",
                "",
                "| algorithm | seed | status | candidate sequence hash |",
                "| --- | ---: | --- | --- |",
            ]
        )
        for item in search_records:
            lines.append(
                f"| {item.algorithm} | {item.search_seed} | {item.status} | "
                f"`{item.candidate_sequence_hash}` |"
            )
        lines.extend(
            [
                "",
                "## Final-checkpoint summaries",
                "",
                "Values are median [IQR], followed by the configured bootstrap "
                "confidence interval for the median.",
                "",
                "| algorithm | metric | median [IQR] | confidence interval |",
                "| --- | --- | ---: | ---: |",
            ]
        )
        for algorithm in self.config.benchmark.algorithms:
            for metric in selected_metrics:
                aggregate = lookup.get((algorithm, final_checkpoint, metric))
                if aggregate is None:
                    continue
                summary = aggregate.summary
                lines.append(
                    f"| {algorithm} | {metric} | {summary.median:.6f} "
                    f"[{summary.percentile_25:.6f}, {summary.percentile_75:.6f}] | "
                    f"[{summary.confidence_interval_lower:.6f}, "
                    f"{summary.confidence_interval_upper:.6f}] |"
                )
        lines.extend(
            [
                "",
                f"## Paired final-checkpoint comparisons against "
                f"{self.config.benchmark.baseline_algorithm}",
                "",
                "Raw differences are algorithm minus baseline. Direction controls only "
                "the win/tie/loss interpretation.",
                "",
                "| algorithm | metric | direction | median difference | "
                "confidence interval | wins/ties/losses |",
                "| --- | --- | --- | ---: | ---: | ---: |",
            ]
        )
        for comparison in paired_comparisons:
            if (
                comparison.budget_checkpoint != final_checkpoint
                or comparison.metric not in selected_metrics
            ):
                continue
            lines.append(
                f"| {comparison.algorithm} | {comparison.metric} | "
                f"{comparison.direction} | {comparison.median_difference:.6f} | "
                f"[{comparison.confidence_interval_lower:.6f}, "
                f"{comparison.confidence_interval_upper:.6f}] | "
                f"{comparison.wins}/{comparison.ties}/{comparison.losses} |"
            )
        lines.extend(
            [
                "",
                "## Interpretation constraints",
                "",
                "- Candidate-evaluation budget, not wall time, is the primary comparison basis.",
                "- Failure-discovery times are right-censored at the checkpoint when no "
                "qualified failure is found.",
                "- Paired comparisons are descriptive; no hypothesis test, multiplicity "
                "correction, or superiority claim is applied.",
                "- Search caches start empty and are isolated per algorithm/seed run, "
                "preventing order-dependent cross-algorithm reuse.",
                "- The complete machine-readable aggregates and paired comparisons are "
                "stored beside this report.",
                "",
                "## Reproduction",
                "",
                "```text",
                "aft benchmark --benchmark-config benchmark_config.yaml "
                "--config simulator_config.yaml --output <new-empty-directory>",
                "```",
                "",
            ]
        )
        return "\n".join(lines)

    def run(self) -> BenchmarkRunReport:
        started = time.monotonic()
        fairness_fingerprint, design_fingerprint = self._initialize()
        observations: list[BenchmarkObservation] = []
        search_records: list[BenchmarkSearchRecord] = []
        expected_environment_hash: str | None = None
        status: BenchmarkStatus = "completed"

        for algorithm in self.config.benchmark.algorithms:
            for search_seed in self.config.benchmark.search_seeds:
                search_directory = (
                    self.benchmark_directory / "searches" / f"{algorithm}_seed_{search_seed}"
                )
                runner = SearchRunner(
                    app_config=self.app_config,
                    search_config=self._search_config(algorithm, search_seed),
                    capabilities=self.capabilities,
                    search_directory=search_directory,
                )
                search_report = runner.run()
                records = runner.store.load_evaluation_records()
                environment = json.loads(
                    (search_directory / "environment.json").read_text(encoding="utf-8")
                )
                environment_hash = configuration_hash(environment)
                if expected_environment_hash is None:
                    expected_environment_hash = environment_hash
                    _atomic_json(
                        self.benchmark_directory / "environment.json",
                        environment,
                    )
                elif environment_hash != expected_environment_hash:
                    status = "failed"
                search_records.append(
                    BenchmarkSearchRecord(
                        algorithm=algorithm,
                        search_seed=search_seed,
                        status=search_report.status,
                        candidate_sequence_hash=_candidate_sequence_hash(records),
                        search_directory=str(search_directory),
                    )
                )
                observations.extend(
                    self._observations(
                        algorithm=algorithm,
                        search_seed=search_seed,
                        runner=runner,
                        search_status=search_report.status,
                        final_measures=search_report.measures,
                    )
                )
                if search_report.status != "completed":
                    status = "failed"
                    break
            if status == "failed":
                break

        aggregates, paired = self._analyze(observations)
        runtime = time.monotonic() - started
        scientific_fingerprint = _scientific_result_fingerprint(
            observations,
            search_records,
        )
        report_path = self.benchmark_directory / "report.md"
        report_path.write_text(
            self._markdown_report(
                status=status,
                fairness_fingerprint=fairness_fingerprint,
                search_records=search_records,
                aggregates=aggregates,
                paired_comparisons=paired,
                runtime_seconds=runtime,
            ),
            encoding="utf-8",
        )
        completed_count = sum(item.status == "completed" for item in search_records)
        final_observations = [
            item
            for item in observations
            if item.budget_checkpoint == self.config.benchmark.evaluation_budget
        ]
        report = BenchmarkRunReport(
            benchmark_id=self.benchmark_id,
            status=status,
            evaluator=self.config.execution.evaluator,
            fairness_fingerprint=fairness_fingerprint,
            design_fingerprint=design_fingerprint,
            scientific_result_fingerprint=scientific_fingerprint,
            algorithm_count=len(self.config.benchmark.algorithms),
            search_seed_count=len(self.config.benchmark.search_seeds),
            completed_search_count=completed_count,
            failed_search_count=len(search_records) - completed_count,
            evaluation_budget_per_search=self.config.benchmark.evaluation_budget,
            total_candidate_budget=(
                len(self.config.benchmark.algorithms)
                * len(self.config.benchmark.search_seeds)
                * self.config.benchmark.evaluation_budget
            ),
            total_candidates_evaluated=sum(
                item.measures.candidate_count for item in final_observations
            ),
            total_realization_evaluations=sum(
                item.measures.realization_evaluation_count for item in final_observations
            ),
            search_records=tuple(search_records),
            observations=tuple(observations),
            aggregates=tuple(aggregates),
            paired_comparisons=tuple(paired),
            wall_clock_runtime_seconds=runtime,
            benchmark_directory=str(self.benchmark_directory),
            report_path=str(report_path),
        )
        _atomic_json(
            self.benchmark_directory / "observations.json",
            [item.model_dump(mode="json") for item in observations],
        )
        _atomic_json(
            self.benchmark_directory / "aggregates.json",
            [item.model_dump(mode="json") for item in aggregates],
        )
        _atomic_json(
            self.benchmark_directory / "paired_comparisons.json",
            [item.model_dump(mode="json") for item in paired],
        )
        _atomic_json(
            self.benchmark_directory / "summary.json",
            report.model_dump(mode="json"),
        )
        _atomic_json(
            self.benchmark_directory / "manifest.json",
            {
                "schema_version": 1,
                "benchmark_id": self.benchmark_id,
                "status": status,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "platform": platform.platform(),
                "python": platform.python_version(),
                "ros_distro": os.environ.get("ROS_DISTRO"),
                "fairness_fingerprint": fairness_fingerprint,
                "design_fingerprint": design_fingerprint,
                "scientific_result_fingerprint": scientific_fingerprint,
                "completed_search_count": completed_count,
            },
        )
        return report
