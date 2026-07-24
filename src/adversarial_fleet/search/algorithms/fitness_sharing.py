from __future__ import annotations

from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities

from ..config import DescriptorConfig, GeneticAlgorithmConfig, GenomeBounds
from ..descriptors import behavior_distance
from ..evaluation import AggregateEvaluation
from .severity_ga import SeverityGeneticAlgorithm


class FitnessSharingGeneticAlgorithm(SeverityGeneticAlgorithm):
    algorithm_name = "fitness_sharing_ga"

    def __init__(
        self,
        *,
        capabilities: ScenarioCapabilities,
        bounds: GenomeBounds,
        config: GeneticAlgorithmConfig,
        descriptor_config: DescriptorConfig,
    ) -> None:
        super().__init__(
            capabilities=capabilities,
            bounds=bounds,
            config=config,
        )
        self.descriptor_config = descriptor_config

    def _rank_key(self, item: AggregateEvaluation) -> tuple[float, float, float, float]:
        return (
            item.shared_severity,
            item.reproducibility.score,
            -item.complexity,
            item.novelty_score,
        )

    def _prepare_population(
        self,
        evaluations: list[AggregateEvaluation],
    ) -> list[AggregateEvaluation]:
        output: list[AggregateEvaluation] = []
        radius = self.config.sharing_radius
        alpha = self.config.sharing_alpha
        for target in evaluations:
            niche_count = 0.0
            for neighbor in evaluations:
                distance = behavior_distance(
                    target.descriptor,
                    neighbor.descriptor,
                    config=self.descriptor_config,
                )
                if distance < radius:
                    niche_count += 1.0 - (distance / radius) ** alpha
            niche_count = max(1.0, niche_count)
            output.append(
                target.model_copy(
                    update={
                        "niche_count": niche_count,
                        "shared_severity": target.robust_severity / niche_count,
                    }
                )
            )
        return output
