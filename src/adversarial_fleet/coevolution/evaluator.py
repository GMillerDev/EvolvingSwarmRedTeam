from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Protocol

from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities
from adversarial_fleet.search.evaluator import DeterministicFakeEvaluator
from adversarial_fleet.search.models import AdversarialGenome

from .config import DefenderBounds
from .models import (
    CrossplayPayoff,
    DefenderArtifact,
    DefenderGenome,
    DefenderRole,
    DefenderRuntime,
    ScenarioRole,
)


class Defender(Protocol):
    @property
    def defender_id(self) -> str: ...

    def materialize(self, run_directory: Path) -> DefenderRuntime: ...


class VersionedDefender:
    def __init__(self, artifact: DefenderArtifact) -> None:
        self.artifact = artifact

    @property
    def defender_id(self) -> str:
        return self.artifact.defender_id

    def materialize(self, run_directory: Path) -> DefenderRuntime:
        run_directory.mkdir(parents=True, exist_ok=True)
        path = run_directory / "defender.json"
        path.write_text(
            json.dumps(self.artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return DefenderRuntime(
            defender_id=self.artifact.defender_id,
            artifact_version=self.artifact.artifact_version,
            artifact_path=str(path.resolve()),
        )


def baseline_defender() -> DefenderArtifact:
    return DefenderArtifact(
        defender_id="rmf_office_baseline",
        artifact_version="fixed-rmf-office-baseline-v1",
        kind="rmf_baseline",
        implementation="fixed Open-RMF Office controller",
    )


def synthetic_defender(genome: DefenderGenome) -> DefenderArtifact:
    digest = genome.digest()
    return DefenderArtifact(
        defender_id=f"synthetic_{digest[:16]}",
        artifact_version=digest,
        kind="synthetic_policy",
        genome=genome,
        implementation="deterministic-crossplay-v1",
    )


def payoff_digest(record: dict[str, object]) -> str:
    import hashlib

    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CompetitiveFakeCrossplayEvaluator:
    evaluator_version = "deterministic-crossplay-v1"

    def __init__(
        self,
        *,
        capabilities: ScenarioCapabilities,
        defender_bounds: DefenderBounds,
    ) -> None:
        self.capabilities = capabilities
        self.defender_bounds = defender_bounds

    def _adjusted_severity(
        self,
        scenario: AdversarialGenome,
        defender: DefenderArtifact,
        *,
        realization_seed: int,
    ) -> float:
        base = DeterministicFakeEvaluator(self.capabilities).evaluate(
            scenario,
            realization_seed=realization_seed,
            candidate_id=scenario.digest(),
        )
        if defender.genome is None:
            return base.severity_score
        workload = scenario.workload
        route_points = [point for route in workload.patrol_routes for point in route]
        overlap = 1.0 - len(set(route_points)) / len(route_points)
        density = min(
            1.0,
            workload.task_count / max(0.5, workload.arrival_interval_seconds) / 8.0,
        )
        incomplete = float(base.metrics.get("incomplete_task_ratio", 0.0))
        features = (density, workload.priority_skew, overlap, incomplete)
        genes = (
            defender.genome.congestion_resilience,
            defender.genome.priority_fairness,
            defender.genome.coordination_horizon,
            defender.genome.recovery_aggressiveness,
        )
        active_weight = sum(features)
        effectiveness = (
            sum(feature * gene for feature, gene in zip(features, genes)) / active_weight
            if active_weight > 0
            else 0.0
        )
        reduction = 0.72 * effectiveness
        policy_intensity = statistics.fmean(genes)
        operational_cost = self.defender_bounds.operational_cost_scale * policy_intensity**2
        return min(10.0, max(0.0, base.severity_score * (1.0 - reduction) + operational_cost))

    def evaluate(
        self,
        scenario: AdversarialGenome,
        defender: DefenderArtifact,
        *,
        generation: int,
        scenario_role: ScenarioRole,
        defender_role: DefenderRole,
        realization_seeds: tuple[int, ...],
    ) -> CrossplayPayoff:
        severities = tuple(
            self._adjusted_severity(
                scenario,
                defender,
                realization_seed=seed,
            )
            for seed in realization_seeds
        )
        robust = float(statistics.median(severities))
        scenario_payoff = robust / 10.0
        core: dict[str, object] = {
            "evaluator_version": self.evaluator_version,
            "generation": generation,
            "scenario_id": scenario.digest(),
            "scenario_role": scenario_role,
            "defender_id": defender.defender_id,
            "defender_version": defender.artifact_version,
            "defender_role": defender_role,
            "realization_seeds": realization_seeds,
            "realization_severities": severities,
            "robust_severity": robust,
            "scenario_payoff": scenario_payoff,
            "defender_payoff": 1.0 - scenario_payoff,
        }
        return CrossplayPayoff(
            **core,
            replay_digest=payoff_digest(core),
        )
