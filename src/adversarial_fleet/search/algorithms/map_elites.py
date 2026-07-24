from __future__ import annotations

from typing import Any

from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities

from ..archives import MapElitesArchive, MapElitesArchiveReport
from ..config import GeneticAlgorithmConfig, GenomeBounds, MapElitesConfig
from ..evaluation import AggregateEvaluation
from ..models import AdversarialGenome
from .severity_ga import SeverityGeneticAlgorithm


class MapElitesAlgorithm(SeverityGeneticAlgorithm):
    algorithm_name = "map_elites"

    def __init__(
        self,
        *,
        capabilities: ScenarioCapabilities,
        bounds: GenomeBounds,
        config: GeneticAlgorithmConfig,
        map_config: MapElitesConfig | None = None,
    ) -> None:
        super().__init__(
            capabilities=capabilities,
            bounds=bounds,
            config=config,
        )
        self.map_config = map_config or MapElitesConfig()
        self.archive = MapElitesArchive(
            robot_count=capabilities.supported_robot_count,
            config=self.map_config,
        )

    def _tournament(self) -> AdversarialGenome:
        ordered = sorted(self.population, key=lambda item: item.candidate_id)
        return self.rng.choice(ordered).genome

    def tell(self, evaluations: list[AggregateEvaluation]) -> None:
        candidate_ids = [item.candidate_id for item in evaluations]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("evaluation batch contains duplicate candidate IDs")
        unknown = [
            candidate_id for candidate_id in candidate_ids if candidate_id not in self.pending
        ]
        if unknown:
            raise ValueError(f"candidate {unknown[0]} was not requested")
        for item in evaluations:
            del self.pending[item.candidate_id]
            self.archive.consider(item)
        self.population = sorted(
            self.archive.elites.values(),
            key=lambda item: item.candidate_id,
        )

    def archive_report(self) -> MapElitesArchiveReport:
        return self.archive.report()

    def state_dict(self) -> dict[str, Any]:
        state = super().state_dict()
        state["archive"] = self.archive.state_dict()
        return state

    def load_state_dict(self, state: dict[str, Any]) -> None:
        archive = MapElitesArchive.from_state_dict(state["archive"])
        if archive.robot_count != self.capabilities.supported_robot_count:
            raise ValueError("checkpoint robot count does not match capabilities")
        if archive.config != self.map_config:
            raise ValueError("checkpoint MAP-Elites configuration does not match")
        super().load_state_dict(state)
        self.archive = archive
        self.population = sorted(
            self.archive.elites.values(),
            key=lambda item: item.candidate_id,
        )
