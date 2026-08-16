from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator

from adversarial_fleet.search.config import GenomeBounds, VariationConfig
from adversarial_fleet.search.models import SearchModel


class CoevolutionSettings(SearchModel):
    experiment_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    seed: int = Field(default=12001, ge=0, le=2**32 - 1)
    generations: int = Field(default=5, ge=2)
    scenario_population_size: int = Field(default=8, ge=4)
    defender_population_size: int = Field(default=8, ge=4)
    scenario_elite_count: int = Field(default=2, ge=1)
    defender_elite_count: int = Field(default=2, ge=1)
    severe_archive_size: int = Field(default=8, ge=1)
    novel_archive_size: int = Field(default=8, ge=1)
    defender_hall_of_fame_size: int = Field(default=8, ge=1)
    realization_seeds: tuple[int, ...] = Field(default=(1042, 1043, 1044), min_length=1)
    scenario_novelty_weight: float = Field(default=0.15, ge=0, le=1)
    defender_retention_weight: float = Field(default=0.35, ge=0, le=1)
    minimum_standard_retention: float = Field(default=0.80, ge=0, le=1)
    verify_payoffs: bool = True

    @model_validator(mode="after")
    def validate_population_controls(self) -> "CoevolutionSettings":
        if self.scenario_elite_count >= self.scenario_population_size:
            raise ValueError("scenario_elite_count must be below scenario_population_size")
        if self.defender_elite_count >= self.defender_population_size:
            raise ValueError("defender_elite_count must be below defender_population_size")
        if len(set(self.realization_seeds)) != len(self.realization_seeds):
            raise ValueError("realization seeds must be unique")
        return self


class DefenderBounds(SearchModel):
    congestion_resilience_min: float = Field(default=0.0, ge=0, le=1)
    congestion_resilience_max: float = Field(default=1.0, ge=0, le=1)
    priority_fairness_min: float = Field(default=0.0, ge=0, le=1)
    priority_fairness_max: float = Field(default=1.0, ge=0, le=1)
    coordination_horizon_min: float = Field(default=0.0, ge=0, le=1)
    coordination_horizon_max: float = Field(default=1.0, ge=0, le=1)
    recovery_aggressiveness_min: float = Field(default=0.0, ge=0, le=1)
    recovery_aggressiveness_max: float = Field(default=1.0, ge=0, le=1)
    mutation_probability: float = Field(default=0.35, ge=0, le=1)
    mutation_sigma: float = Field(default=0.12, gt=0, le=1)
    operational_cost_scale: float = Field(default=0.40, ge=0, le=2)

    @model_validator(mode="after")
    def validate_ranges(self) -> "DefenderBounds":
        for name in (
            "congestion_resilience",
            "priority_fairness",
            "coordination_horizon",
            "recovery_aggressiveness",
        ):
            if getattr(self, f"{name}_min") > getattr(self, f"{name}_max"):
                raise ValueError(f"{name}_min must not exceed {name}_max")
        return self


class CoevolutionFileConfig(SearchModel):
    coevolution: CoevolutionSettings = Field(default_factory=CoevolutionSettings)
    genome: GenomeBounds = Field(default_factory=GenomeBounds)
    scenario_variation: VariationConfig = Field(default_factory=VariationConfig)
    defender: DefenderBounds = Field(default_factory=DefenderBounds)


def load_coevolution_config(path: Path) -> CoevolutionFileConfig:
    from adversarial_fleet.config import load_document

    return CoevolutionFileConfig.model_validate(load_document(path))
