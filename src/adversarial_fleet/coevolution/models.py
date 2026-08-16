from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from adversarial_fleet.search.models import AdversarialGenome, SearchModel


class DefenderGenome(SearchModel):
    congestion_resilience: float = Field(ge=0, le=1)
    priority_fairness: float = Field(ge=0, le=1)
    coordination_horizon: float = Field(ge=0, le=1)
    recovery_aggressiveness: float = Field(ge=0, le=1)

    def digest(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DefenderArtifact(SearchModel):
    defender_id: str = Field(min_length=1)
    artifact_version: str = Field(min_length=1)
    kind: Literal["rmf_baseline", "synthetic_policy"]
    genome: DefenderGenome | None = None
    implementation: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_kind(self) -> "DefenderArtifact":
        if self.kind == "synthetic_policy" and self.genome is None:
            raise ValueError("synthetic defender requires a genome")
        if self.kind == "rmf_baseline" and self.genome is not None:
            raise ValueError("RMF baseline must not contain synthetic policy genes")
        return self


class DefenderRuntime(SearchModel):
    defender_id: str
    artifact_version: str
    artifact_path: str


ScenarioRole = Literal["current", "severe_archive", "novel_archive", "standard"]
DefenderRole = Literal["current", "hall_of_fame", "baseline"]


class CrossplayPayoff(SearchModel):
    evaluator_version: str = Field(min_length=1)
    generation: int = Field(ge=0)
    scenario_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_role: ScenarioRole
    defender_id: str
    defender_version: str
    defender_role: DefenderRole
    realization_seeds: tuple[int, ...]
    realization_severities: tuple[float, ...]
    robust_severity: float = Field(ge=0, le=10)
    scenario_payoff: float = Field(ge=0, le=1)
    defender_payoff: float = Field(ge=0, le=1)
    replay_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class GenerationSummary(SearchModel):
    generation: int = Field(ge=0)
    current_scenario_count: int = Field(ge=1)
    current_defender_count: int = Field(ge=1)
    matrix_cell_count: int = Field(ge=1)
    best_scenario_fitness: float = Field(ge=0)
    mean_scenario_fitness: float = Field(ge=0)
    best_defender_fitness: float = Field(ge=0, le=1)
    mean_defender_fitness: float = Field(ge=0, le=1)
    best_standard_retention: float = Field(ge=0, le=1)
    mean_standard_retention: float = Field(ge=0, le=1)
    severe_archive_size: int = Field(ge=0)
    novel_archive_size: int = Field(ge=0)
    defender_hall_of_fame_size: int = Field(ge=0)


class ParticipantRegistry(SearchModel):
    scenarios: dict[str, AdversarialGenome]
    defenders: dict[str, DefenderArtifact]
