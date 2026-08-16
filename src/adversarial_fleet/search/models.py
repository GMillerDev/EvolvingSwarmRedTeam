from __future__ import annotations

import hashlib
import json

from pydantic import ConfigDict, Field, model_validator

from adversarial_fleet.scenarios.genome import ScenarioGenome, StrictModel


class SearchModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkloadGenome(SearchModel):
    """Capability-safe workload genes for the first evolutionary milestone."""

    task_count: int = Field(ge=1, le=50)
    arrival_interval_seconds: float = Field(ge=0, le=30)
    priority_skew: float = Field(default=0.0, ge=0, le=1)
    patrol_routes: tuple[tuple[str, ...], ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_routes(self) -> "WorkloadGenome":
        for route in self.patrol_routes:
            if not 2 <= len(route) <= 8:
                raise ValueError("each patrol route must contain between two and eight places")
            if any(left == right for left, right in zip(route, route[1:])):
                raise ValueError("patrol routes may not contain consecutive duplicate places")
        return self


class FacilitySearchGenome(SearchModel):
    """Facility genes with a live actuator declared by the capability document."""

    blocked_lane_id: str = Field(min_length=1)


class AdversarialGenome(SearchModel):
    """Evolvable genes only; search and realization seeds are deliberately absent."""

    workload: WorkloadGenome
    facility: FacilitySearchGenome | None = None

    def normalized(self) -> dict[str, object]:
        # Excluding absent future genes preserves Phase 0-5 workload-only identities.
        return self.model_dump(mode="json", exclude_none=True)

    def digest(self) -> str:
        canonical = json.dumps(self.normalized(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ScenarioRealization(SearchModel):
    """A specific deterministic realization of a seed-free genotype."""

    genotype_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    realization_seed: int = Field(ge=0, le=2**32 - 1)

    @classmethod
    def from_genome(
        cls,
        genome: AdversarialGenome,
        *,
        realization_seed: int,
    ) -> "ScenarioRealization":
        return cls(genotype_hash=genome.digest(), realization_seed=realization_seed)

    def digest(self) -> str:
        canonical = json.dumps(
            {
                "genotype_hash": self.genotype_hash,
                "realization_seed": self.realization_seed,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ScenarioPhenotype(SearchModel):
    """Validated live scenario produced from one genotype realization."""

    realization: ScenarioRealization
    capabilities_version: str = Field(min_length=1)
    capabilities_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario: ScenarioGenome
    phenotype_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hashes(self) -> "ScenarioPhenotype":
        if self.phenotype_hash != self.scenario.digest():
            raise ValueError("phenotype_hash does not match the normalized scenario")
        if self.realization.realization_seed != self.scenario.seed:
            raise ValueError("realization seed does not match the scenario seed")
        return self

    @property
    def candidate_id(self) -> str:
        return self.realization.genotype_hash

    @property
    def realization_id(self) -> str:
        return self.realization.digest()
