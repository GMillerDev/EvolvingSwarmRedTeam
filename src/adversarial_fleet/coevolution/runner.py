from __future__ import annotations

import hashlib
import json
import random
import statistics
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
from adversarial_fleet.search.models import AdversarialGenome, SearchModel, WorkloadGenome
from adversarial_fleet.search.variation import crossover_genomes, mutate_genome, sample_genome

from .config import CoevolutionFileConfig, DefenderBounds
from .evaluator import (
    CompetitiveFakeCrossplayEvaluator,
    VersionedDefender,
    baseline_defender,
    synthetic_defender,
)
from .models import (
    CrossplayPayoff,
    DefenderArtifact,
    DefenderGenome,
    DefenderRole,
    GenerationSummary,
    ParticipantRegistry,
    ScenarioRole,
)
from .verifier import CrossplayVerificationReport, CrossplayVerifier


CoevolutionStatus = Literal["completed", "verification_failure"]


class CoevolutionRunReport(SearchModel):
    experiment_id: str
    status: CoevolutionStatus
    generations: int = Field(ge=2)
    scenario_population_size: int = Field(ge=4)
    defender_population_size: int = Field(ge=4)
    payoff_count: int = Field(ge=1)
    unique_scenario_count: int = Field(ge=1)
    unique_defender_count: int = Field(ge=1)
    severe_archive_size: int = Field(ge=1)
    novel_archive_size: int = Field(ge=1)
    defender_hall_of_fame_size: int = Field(ge=1)
    scenario_population_adapted: bool
    defender_population_adapted: bool
    final_best_standard_retention: float = Field(ge=0, le=1)
    retention_requirement_met: bool
    verification: CrossplayVerificationReport
    scientific_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    wall_clock_runtime_seconds: float = Field(ge=0)
    experiment_directory: str


def _hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _experiment_id(config: CoevolutionFileConfig) -> str:
    if config.coevolution.experiment_id is not None:
        return config.coevolution.experiment_id
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    return f"coevolution_{stamp}_seed_{config.coevolution.seed}"


def _standard_scenarios() -> tuple[AdversarialGenome, ...]:
    return (
        AdversarialGenome(
            workload=WorkloadGenome(
                task_count=1,
                arrival_interval_seconds=10.0,
                priority_skew=0.0,
                patrol_routes=(("coe", "lounge"),),
            )
        ),
        AdversarialGenome(
            workload=WorkloadGenome(
                task_count=2,
                arrival_interval_seconds=12.0,
                priority_skew=0.0,
                patrol_routes=(("supplies", "pantry"), ("pantry", "hardware_2")),
            )
        ),
        AdversarialGenome(
            workload=WorkloadGenome(
                task_count=3,
                arrival_interval_seconds=8.0,
                priority_skew=0.1,
                patrol_routes=(("coe", "supplies", "hardware_2"),),
            )
        ),
    )


def _sample_defender(rng: random.Random, bounds: DefenderBounds) -> DefenderArtifact:
    return synthetic_defender(
        DefenderGenome(
            congestion_resilience=rng.uniform(
                bounds.congestion_resilience_min,
                bounds.congestion_resilience_max,
            ),
            priority_fairness=rng.uniform(
                bounds.priority_fairness_min,
                bounds.priority_fairness_max,
            ),
            coordination_horizon=rng.uniform(
                bounds.coordination_horizon_min,
                bounds.coordination_horizon_max,
            ),
            recovery_aggressiveness=rng.uniform(
                bounds.recovery_aggressiveness_min,
                bounds.recovery_aggressiveness_max,
            ),
        )
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _vary_defender(
    left: DefenderArtifact,
    right: DefenderArtifact,
    *,
    rng: random.Random,
    bounds: DefenderBounds,
) -> DefenderArtifact:
    assert left.genome is not None and right.genome is not None
    values: dict[str, float] = {}
    for name in (
        "congestion_resilience",
        "priority_fairness",
        "coordination_horizon",
        "recovery_aggressiveness",
    ):
        value = rng.choice((getattr(left.genome, name), getattr(right.genome, name)))
        if rng.random() < bounds.mutation_probability:
            value += rng.gauss(0.0, bounds.mutation_sigma)
        values[name] = _clamp(
            value,
            getattr(bounds, f"{name}_min"),
            getattr(bounds, f"{name}_max"),
        )
    return synthetic_defender(DefenderGenome(**values))


def _novelty(vectors: dict[str, tuple[float, ...]]) -> dict[str, float]:
    output: dict[str, float] = {}
    for candidate_id, vector in vectors.items():
        distances = []
        for other_id, other in vectors.items():
            if other_id == candidate_id:
                continue
            distances.append(statistics.fmean(abs(a - b) for a, b in zip(vector, other)))
        output[candidate_id] = statistics.fmean(distances) if distances else 0.0
    return output


class CoevolutionRunner:
    def __init__(
        self,
        *,
        app_config: AppConfig,
        coevolution_config: CoevolutionFileConfig,
        capabilities: ScenarioCapabilities | None = None,
        experiment_directory: Path | None = None,
    ) -> None:
        self.app_config = app_config
        self.config = coevolution_config
        self.capabilities = capabilities or ScenarioCapabilities()
        self.experiment_id = _experiment_id(coevolution_config)
        self.root = (
            experiment_directory.resolve()
            if experiment_directory is not None
            else app_config.project.output_dir.resolve() / "coevolution" / self.experiment_id
        )
        self.rng = random.Random(coevolution_config.coevolution.seed)
        self.evaluator = CompetitiveFakeCrossplayEvaluator(
            capabilities=self.capabilities,
            defender_bounds=coevolution_config.defender,
        )
        self.scenario_registry: dict[str, AdversarialGenome] = {}
        self.defender_registry: dict[str, DefenderArtifact] = {}

    def _register_scenario(self, scenario: AdversarialGenome) -> None:
        self.scenario_registry[scenario.digest()] = scenario

    def _register_defender(self, defender: DefenderArtifact) -> None:
        self.defender_registry[defender.defender_id] = defender
        runtime_dir = self.root / "defenders" / defender.defender_id
        if not runtime_dir.exists():
            VersionedDefender(defender).materialize(runtime_dir)

    def _initialize(self) -> None:
        if self.root.exists() and any(self.root.iterdir()):
            raise FileExistsError(
                f"coevolution directory already exists and is not empty: {self.root}"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "defenders").mkdir()
        (self.root / "coevolution_config.yaml").write_text(
            yaml.safe_dump(self.config.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
        (self.root / "simulator_config.yaml").write_text(
            yaml.safe_dump(self.app_config.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
        _atomic_json(self.root / "capabilities.json", self.capabilities.normalized())

    def _matrix(
        self,
        *,
        generation: int,
        scenarios: list[tuple[AdversarialGenome, ScenarioRole]],
        defenders: list[tuple[DefenderArtifact, DefenderRole]],
    ) -> list[CrossplayPayoff]:
        output: list[CrossplayPayoff] = []
        for scenario, scenario_role in scenarios:
            self._register_scenario(scenario)
            for defender, defender_role in defenders:
                self._register_defender(defender)
                output.append(
                    self.evaluator.evaluate(
                        scenario,
                        defender,
                        generation=generation,
                        scenario_role=scenario_role,
                        defender_role=defender_role,
                        realization_seeds=self.config.coevolution.realization_seeds,
                    )
                )
        return output

    def _fitness(
        self,
        matrix: list[CrossplayPayoff],
    ) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
        current_scenario_rows: dict[str, list[CrossplayPayoff]] = defaultdict(list)
        current_defender_rows: dict[str, list[CrossplayPayoff]] = defaultdict(list)
        for row in matrix:
            if row.scenario_role == "current":
                current_scenario_rows[row.scenario_id].append(row)
            if row.defender_role == "current":
                current_defender_rows[row.defender_id].append(row)
        ordered_defenders = sorted(
            {row.defender_id for rows in current_scenario_rows.values() for row in rows}
        )
        vectors = {
            scenario_id: tuple(
                next(row.scenario_payoff for row in rows if row.defender_id == defender_id)
                for defender_id in ordered_defenders
            )
            for scenario_id, rows in current_scenario_rows.items()
        }
        novelty = _novelty(vectors)
        scenario_fitness = {
            scenario_id: statistics.fmean(row.scenario_payoff for row in rows)
            + self.config.coevolution.scenario_novelty_weight * novelty[scenario_id]
            for scenario_id, rows in current_scenario_rows.items()
        }
        defender_fitness: dict[str, float] = {}
        retention: dict[str, float] = {}
        for defender_id, rows in current_defender_rows.items():
            standard = [row.defender_payoff for row in rows if row.scenario_role == "standard"]
            adversarial = [row.defender_payoff for row in rows if row.scenario_role != "standard"]
            retention[defender_id] = statistics.fmean(standard)
            adversarial_score = statistics.fmean(adversarial)
            weight = self.config.coevolution.defender_retention_weight
            defender_fitness[defender_id] = (1.0 - weight) * adversarial_score + weight * retention[
                defender_id
            ]
        return scenario_fitness, defender_fitness, retention, novelty

    @staticmethod
    def _truncate_archive(
        archive: dict[str, tuple[Any, float]],
        maximum_size: int,
    ) -> dict[str, tuple[Any, float]]:
        return dict(
            sorted(
                archive.items(),
                key=lambda item: (-item[1][1], item[0]),
            )[:maximum_size]
        )

    def _next_scenarios(
        self,
        population: list[AdversarialGenome],
        fitness: dict[str, float],
    ) -> list[AdversarialGenome]:
        settings = self.config.coevolution
        ordered = sorted(population, key=lambda item: (-fitness[item.digest()], item.digest()))
        output = ordered[: settings.scenario_elite_count]
        known = {item.digest() for item in output}
        attempts = 0
        while len(output) < settings.scenario_population_size and attempts < 1000:
            attempts += 1
            left = max(self.rng.sample(population, 2), key=lambda item: fitness[item.digest()])
            right = max(self.rng.sample(population, 2), key=lambda item: fitness[item.digest()])
            child = crossover_genomes(
                left,
                right,
                self.rng,
                bounds=self.config.genome,
                config=self.config.scenario_variation,
            )
            child = mutate_genome(
                child,
                self.rng,
                capabilities=self.capabilities,
                bounds=self.config.genome,
                config=self.config.scenario_variation,
            )
            if child.digest() not in known:
                output.append(child)
                known.add(child.digest())
        if len(output) != settings.scenario_population_size:
            raise RuntimeError("unable to evolve a unique scenario population")
        return output

    def _next_defenders(
        self,
        population: list[DefenderArtifact],
        fitness: dict[str, float],
    ) -> list[DefenderArtifact]:
        settings = self.config.coevolution
        ordered = sorted(
            population, key=lambda item: (-fitness[item.defender_id], item.defender_id)
        )
        output = ordered[: settings.defender_elite_count]
        known = {item.defender_id for item in output}
        attempts = 0
        while len(output) < settings.defender_population_size and attempts < 1000:
            attempts += 1
            left = max(
                self.rng.sample(population, 2),
                key=lambda item: fitness[item.defender_id],
            )
            right = max(
                self.rng.sample(population, 2),
                key=lambda item: fitness[item.defender_id],
            )
            child = _vary_defender(
                left,
                right,
                rng=self.rng,
                bounds=self.config.defender,
            )
            if child.defender_id not in known:
                output.append(child)
                known.add(child.defender_id)
        if len(output) != settings.defender_population_size:
            raise RuntimeError("unable to evolve a unique defender population")
        return output

    def run(self) -> CoevolutionRunReport:
        started = time.monotonic()
        self._initialize()
        settings = self.config.coevolution
        scenarios = [
            sample_genome(
                self.rng,
                capabilities=self.capabilities,
                bounds=self.config.genome,
            )
            for _ in range(settings.scenario_population_size)
        ]
        defenders = [
            _sample_defender(self.rng, self.config.defender)
            for _ in range(settings.defender_population_size)
        ]
        initial_scenario_ids = {item.digest() for item in scenarios}
        initial_defender_ids = {item.defender_id for item in defenders}
        standards = _standard_scenarios()
        severe_archive: dict[str, tuple[AdversarialGenome, float]] = {}
        novel_archive: dict[str, tuple[AdversarialGenome, float]] = {}
        defender_hof: dict[str, tuple[DefenderArtifact, float]] = {}
        all_payoffs: list[CrossplayPayoff] = []
        summaries: list[GenerationSummary] = []

        baseline = baseline_defender()
        for generation in range(settings.generations):
            scenario_panel: list[tuple[AdversarialGenome, ScenarioRole]] = [
                (item, "current") for item in scenarios
            ]
            scenario_panel.extend((item, "severe_archive") for item, _ in severe_archive.values())
            scenario_panel.extend((item, "novel_archive") for item, _ in novel_archive.values())
            scenario_panel.extend((item, "standard") for item in standards)
            defender_panel: list[tuple[DefenderArtifact, DefenderRole]] = [
                (item, "current") for item in defenders
            ]
            defender_panel.extend((item, "hall_of_fame") for item, _ in defender_hof.values())
            defender_panel.append((baseline, "baseline"))
            matrix = self._matrix(
                generation=generation,
                scenarios=scenario_panel,
                defenders=defender_panel,
            )
            all_payoffs.extend(matrix)
            scenario_fitness, defender_fitness, retention, novelty = self._fitness(matrix)

            for scenario in sorted(
                scenarios,
                key=lambda item: (-scenario_fitness[item.digest()], item.digest()),
            )[:2]:
                scenario_id = scenario.digest()
                severe_archive[scenario_id] = (scenario, scenario_fitness[scenario_id])
            severe_archive = self._truncate_archive(
                severe_archive,
                settings.severe_archive_size,
            )
            for scenario in sorted(
                scenarios,
                key=lambda item: (-novelty[item.digest()], item.digest()),
            )[:2]:
                scenario_id = scenario.digest()
                novel_archive[scenario_id] = (scenario, novelty[scenario_id])
            novel_archive = self._truncate_archive(
                novel_archive,
                settings.novel_archive_size,
            )
            best_defender = max(
                defenders,
                key=lambda item: (defender_fitness[item.defender_id], item.defender_id),
            )
            defender_hof[best_defender.defender_id] = (
                best_defender,
                defender_fitness[best_defender.defender_id],
            )
            defender_hof = self._truncate_archive(
                defender_hof,
                settings.defender_hall_of_fame_size,
            )
            summaries.append(
                GenerationSummary(
                    generation=generation,
                    current_scenario_count=len(scenarios),
                    current_defender_count=len(defenders),
                    matrix_cell_count=len(matrix),
                    best_scenario_fitness=max(scenario_fitness.values()),
                    mean_scenario_fitness=statistics.fmean(scenario_fitness.values()),
                    best_defender_fitness=max(defender_fitness.values()),
                    mean_defender_fitness=statistics.fmean(defender_fitness.values()),
                    best_standard_retention=max(retention.values()),
                    mean_standard_retention=statistics.fmean(retention.values()),
                    severe_archive_size=len(severe_archive),
                    novel_archive_size=len(novel_archive),
                    defender_hall_of_fame_size=len(defender_hof),
                )
            )
            if generation + 1 < settings.generations:
                scenarios = self._next_scenarios(scenarios, scenario_fitness)
                defenders = self._next_defenders(defenders, defender_fitness)

        registry = ParticipantRegistry(
            scenarios=self.scenario_registry,
            defenders=self.defender_registry,
        )
        _atomic_json(self.root / "participants.json", registry.model_dump(mode="json"))
        with (self.root / "payoff_matrix.jsonl").open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            for payoff in all_payoffs:
                stream.write(json.dumps(payoff.model_dump(mode="json"), sort_keys=True) + "\n")
        _atomic_json(
            self.root / "generation_summaries.json",
            [item.model_dump(mode="json") for item in summaries],
        )
        verification = CrossplayVerifier().verify(self.root)
        status: CoevolutionStatus = (
            "completed"
            if verification.verified or not settings.verify_payoffs
            else "verification_failure"
        )
        final_scenario_ids = {item.digest() for item in scenarios}
        final_defender_ids = {item.defender_id for item in defenders}
        scientific_fingerprint = _hash(
            {
                "participants": registry.model_dump(mode="json"),
                "payoffs": [item.model_dump(mode="json") for item in all_payoffs],
                "generations": [item.model_dump(mode="json") for item in summaries],
            }
        )
        report = CoevolutionRunReport(
            experiment_id=self.experiment_id,
            status=status,
            generations=settings.generations,
            scenario_population_size=settings.scenario_population_size,
            defender_population_size=settings.defender_population_size,
            payoff_count=len(all_payoffs),
            unique_scenario_count=len(self.scenario_registry),
            unique_defender_count=len(self.defender_registry),
            severe_archive_size=len(severe_archive),
            novel_archive_size=len(novel_archive),
            defender_hall_of_fame_size=len(defender_hof),
            scenario_population_adapted=final_scenario_ids != initial_scenario_ids,
            defender_population_adapted=final_defender_ids != initial_defender_ids,
            final_best_standard_retention=summaries[-1].best_standard_retention,
            retention_requirement_met=(
                summaries[-1].best_standard_retention >= settings.minimum_standard_retention
            ),
            verification=verification,
            scientific_fingerprint=scientific_fingerprint,
            wall_clock_runtime_seconds=time.monotonic() - started,
            experiment_directory=str(self.root),
        )
        _atomic_json(self.root / "summary.json", report.model_dump(mode="json"))
        (self.root / "report.md").write_text(self._markdown(report, summaries), encoding="utf-8")
        _atomic_json(
            self.root / "checkpoint.json",
            {
                "schema_version": 1,
                "generation": settings.generations,
                "rng_state": repr(self.rng.getstate()),
                "scientific_fingerprint": scientific_fingerprint,
            },
        )
        return report

    @staticmethod
    def _markdown(
        report: CoevolutionRunReport,
        summaries: list[GenerationSummary],
    ) -> str:
        lines = [
            f"# Coevolution report: {report.experiment_id}",
            "",
            f"- Status: `{report.status}`",
            "- Evaluator: `deterministic-crossplay-v1`",
            f"- Payoff cells: {report.payoff_count}",
            f"- Scenario population adapted: {report.scenario_population_adapted}",
            f"- Defender population adapted: {report.defender_population_adapted}",
            f"- Payoff replay verification: {report.verification.verified}",
            f"- Scientific fingerprint: `{report.scientific_fingerprint}`",
            "",
            "> Synthetic defender evolution validates cross-play machinery only. The fixed "
            "RMF baseline is present, but no live controller is trained by this run.",
            "",
            "## Generation diagnostics",
            "",
            "| generation | matrix | best scenario | mean scenario | best defender | "
            "mean defender | best retention | severe/novel/defender HOF |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for item in summaries:
            lines.append(
                f"| {item.generation} | {item.matrix_cell_count} | "
                f"{item.best_scenario_fitness:.6f} | {item.mean_scenario_fitness:.6f} | "
                f"{item.best_defender_fitness:.6f} | {item.mean_defender_fitness:.6f} | "
                f"{item.best_standard_retention:.6f} | {item.severe_archive_size}/"
                f"{item.novel_archive_size}/{item.defender_hall_of_fame_size} |"
            )
        lines.extend(
            [
                "",
                "Every matrix cell records exact participant versions, ordered realization "
                "seeds, realization severities, both payoffs, and a replay digest. "
                "`CrossplayVerifier` recomputed the full matrix from persisted artifacts.",
                "",
            ]
        )
        return "\n".join(lines)
