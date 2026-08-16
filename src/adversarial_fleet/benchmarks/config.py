from __future__ import annotations

from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import Field, model_validator

from adversarial_fleet.search.config import (
    ConfirmationConfig,
    DescriptorConfig,
    GenomeBounds,
    MapElitesConfig,
    SearchExecutionConfig,
)
from adversarial_fleet.search.models import SearchModel


AlgorithmName: TypeAlias = Literal[
    "random_search",
    "severity_ga",
    "fitness_sharing_ga",
    "nsga2",
    "map_elites",
]

REQUIRED_ALGORITHMS: tuple[AlgorithmName, ...] = (
    "random_search",
    "severity_ga",
    "fitness_sharing_ga",
    "nsga2",
    "map_elites",
)


class BenchmarkSettings(SearchModel):
    benchmark_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    algorithms: tuple[AlgorithmName, ...] = REQUIRED_ALGORITHMS
    search_seeds: tuple[int, ...] = Field(
        default=(9101, 9102, 9103),
        min_length=2,
    )
    evaluation_budget: int = Field(default=48, ge=1)
    budget_checkpoints: tuple[int, ...] = (12, 24, 48)
    baseline_algorithm: AlgorithmName = "random_search"
    confidence_level: float = Field(default=0.95, gt=0, lt=1)
    bootstrap_resamples: int = Field(default=2000, ge=100, le=100_000)
    analysis_seed: int = Field(default=5519, ge=0, le=2**32 - 1)
    require_complete_suite: bool = True

    @model_validator(mode="after")
    def validate_design(self) -> "BenchmarkSettings":
        if len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError("benchmark algorithms must be unique")
        if self.require_complete_suite and not set(REQUIRED_ALGORITHMS) <= set(self.algorithms):
            missing = sorted(set(REQUIRED_ALGORITHMS) - set(self.algorithms))
            raise ValueError(f"complete benchmark suite is missing: {', '.join(missing)}")
        if self.baseline_algorithm not in self.algorithms:
            raise ValueError("baseline_algorithm must be included in algorithms")
        if len(set(self.search_seeds)) != len(self.search_seeds):
            raise ValueError("benchmark search seeds must be unique")
        if any(seed < 0 or seed > 2**32 - 1 for seed in self.search_seeds):
            raise ValueError("benchmark search seeds must be unsigned 32-bit integers")
        if not self.budget_checkpoints:
            raise ValueError("budget_checkpoints must not be empty")
        if tuple(sorted(set(self.budget_checkpoints))) != self.budget_checkpoints:
            raise ValueError("budget_checkpoints must be unique and strictly increasing")
        if self.budget_checkpoints[-1] != self.evaluation_budget:
            raise ValueError("the final budget checkpoint must equal evaluation_budget")
        if self.budget_checkpoints[0] < 1:
            raise ValueError("budget checkpoints must be positive")
        return self


class BenchmarkSearchSettings(SearchModel):
    population_size: int = Field(default=20, ge=2)
    offspring_size: int = Field(default=20, ge=1)
    tournament_size: int = Field(default=3, ge=2)
    checkpoint_interval: int = Field(default=1, ge=1)
    realization_seeds: tuple[int, ...] = Field(
        default=(1042, 1043, 1044),
        min_length=1,
    )


class BenchmarkFileConfig(SearchModel):
    benchmark: BenchmarkSettings = Field(default_factory=BenchmarkSettings)
    search: BenchmarkSearchSettings = Field(default_factory=BenchmarkSearchSettings)
    genome: GenomeBounds = Field(default_factory=GenomeBounds)
    descriptor: DescriptorConfig = Field(default_factory=DescriptorConfig)
    confirmation: ConfirmationConfig = Field(default_factory=ConfirmationConfig)
    map_elites: MapElitesConfig = Field(default_factory=MapElitesConfig)
    execution: SearchExecutionConfig = Field(default_factory=SearchExecutionConfig)

    @model_validator(mode="after")
    def validate_confirmation_seeds(self) -> "BenchmarkFileConfig":
        if len(self.search.realization_seeds) < self.confirmation.total_runs:
            raise ValueError("realization seed count must cover confirmation total_runs")
        return self


def load_benchmark_config(path: Path) -> BenchmarkFileConfig:
    from adversarial_fleet.config import load_document

    return BenchmarkFileConfig.model_validate(load_document(path))
