from __future__ import annotations

from pydantic import Field, model_validator

from .models import SearchModel


CONTINUOUS_DESCRIPTOR_FIELDS = (
    "incomplete_task_ratio",
    "p95_latency_ratio",
    "failure_onset_ratio",
    "deadlock_duration_ratio",
    "starvation_ratio",
    "blocked_time_ratio",
    "affected_robot_fraction",
    "task_active_imbalance",
    "recovery_ratio",
    "negotiation_failure_ratio",
)


class GenomeBounds(SearchModel):
    task_count_min: int = Field(default=1, ge=1, le=50)
    task_count_max: int = Field(default=20, ge=1, le=50)
    arrival_interval_min: float = Field(default=0.0, ge=0, le=30)
    arrival_interval_max: float = Field(default=30.0, ge=0, le=30)
    priority_skew_min: float = Field(default=0.0, ge=0, le=1)
    priority_skew_max: float = Field(default=1.0, ge=0, le=1)
    route_count_min: int = Field(default=1, ge=1, le=8)
    route_count_max: int = Field(default=6, ge=1, le=8)
    route_length_min: int = Field(default=2, ge=2, le=8)
    route_length_max: int = Field(default=6, ge=2, le=8)

    @model_validator(mode="after")
    def validate_ranges(self) -> "GenomeBounds":
        ranges = (
            ("task_count", self.task_count_min, self.task_count_max),
            ("arrival_interval", self.arrival_interval_min, self.arrival_interval_max),
            ("priority_skew", self.priority_skew_min, self.priority_skew_max),
            ("route_count", self.route_count_min, self.route_count_max),
            ("route_length", self.route_length_min, self.route_length_max),
        )
        for name, lower, upper in ranges:
            if lower > upper:
                raise ValueError(f"{name}_min must not exceed {name}_max")
        return self


class DescriptorConfig(SearchModel):
    latency_scale: float = Field(default=300.0, gt=0)
    deadlock_scale: float = Field(default=120.0, gt=0)
    starvation_scale: float = Field(default=10.0, gt=0)
    blocked_time_scale: float = Field(default=600.0, gt=0)
    recovery_scale: float = Field(default=10.0, gt=0)
    negotiation_failure_scale: float = Field(default=10.0, gt=0)
    categorical_weight: float = Field(default=0.30, ge=0)
    continuous_weight: float = Field(default=0.60, ge=0)
    mask_weight: float = Field(default=0.10, ge=0)
    novelty_k: int = Field(default=10, ge=1)
    continuous_feature_weights: tuple[tuple[str, float], ...] = tuple(
        (name, 1.0) for name in CONTINUOUS_DESCRIPTOR_FIELDS
    )

    @model_validator(mode="after")
    def validate_distance_weights(self) -> "DescriptorConfig":
        if self.categorical_weight + self.continuous_weight + self.mask_weight <= 0:
            raise ValueError("at least one descriptor distance weight must be positive")
        feature_weights = dict(self.continuous_feature_weights)
        if len(feature_weights) != len(self.continuous_feature_weights):
            raise ValueError("continuous descriptor feature weights must be unique")
        if set(feature_weights) != set(CONTINUOUS_DESCRIPTOR_FIELDS):
            raise ValueError("continuous descriptor feature weights must cover every field")
        if any(weight <= 0 for weight in feature_weights.values()):
            raise ValueError("continuous descriptor feature weights must be positive")
        return self


class ConfirmationConfig(SearchModel):
    total_runs: int = Field(default=3, ge=1)
    minimum_valid_runs: int = Field(default=3, ge=1)
    reproducibility_threshold: float = Field(default=2 / 3, ge=0, le=1)
    confirm_all: bool = False

    @model_validator(mode="after")
    def validate_run_counts(self) -> "ConfirmationConfig":
        if self.minimum_valid_runs > self.total_runs:
            raise ValueError("minimum_valid_runs must not exceed total_runs")
        return self


class VariationConfig(SearchModel):
    mutation_probability: float = Field(default=0.25, ge=0, le=1)
    crossover_probability: float = Field(default=0.80, ge=0, le=1)
    numeric_sigma: float = Field(default=0.15, gt=0)


class GeneticAlgorithmConfig(SearchModel):
    search_seed: int = Field(default=7001, ge=0, le=2**32 - 1)
    population_size: int = Field(default=20, ge=2)
    offspring_size: int = Field(default=20, ge=1)
    tournament_size: int = Field(default=3, ge=2)
    sharing_radius: float = Field(default=0.25, gt=0, le=1)
    sharing_alpha: float = Field(default=1.0, gt=0)
    variation: VariationConfig = Field(default_factory=VariationConfig)


class MapElitesConfig(SearchModel):
    early_onset_upper: float = Field(default=0.33, gt=0, lt=1)
    middle_onset_upper: float = Field(default=0.66, gt=0, lt=1)
    low_loss_upper: float = Field(default=0.25, gt=0, lt=1)
    medium_loss_upper: float = Field(default=0.75, gt=0, lt=1)
    include_unknown_telemetry_niches: bool = True

    @model_validator(mode="after")
    def validate_bucket_boundaries(self) -> "MapElitesConfig":
        if self.early_onset_upper >= self.middle_onset_upper:
            raise ValueError("early onset boundary must be below middle onset boundary")
        if self.low_loss_upper >= self.medium_loss_upper:
            raise ValueError("low loss boundary must be below medium loss boundary")
        return self
