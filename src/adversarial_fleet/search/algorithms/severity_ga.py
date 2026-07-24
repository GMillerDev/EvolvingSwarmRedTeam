from __future__ import annotations

import ast
import random
from typing import Any

from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities

from ..config import GeneticAlgorithmConfig, GenomeBounds
from ..evaluation import AggregateEvaluation
from ..models import AdversarialGenome
from ..variation import crossover_genomes, mutate_genome, sample_genome


class SeverityGeneticAlgorithm:
    algorithm_name = "severity_ga"

    def __init__(
        self,
        *,
        capabilities: ScenarioCapabilities,
        bounds: GenomeBounds,
        config: GeneticAlgorithmConfig,
    ) -> None:
        self.capabilities = capabilities
        self.bounds = bounds
        self.config = config
        self.rng = random.Random(config.search_seed)
        self.population: list[AggregateEvaluation] = []
        self.pending: dict[str, AdversarialGenome] = {}

    def _rank_key(self, item: AggregateEvaluation) -> tuple[float, float, float, float]:
        return (
            item.robust_severity,
            item.reproducibility.score,
            -item.complexity,
            item.novelty_score,
        )

    def _tournament(self) -> AdversarialGenome:
        size = min(self.config.tournament_size, len(self.population))
        competitors = self.rng.sample(self.population, size)
        return max(competitors, key=self._rank_key).genome

    def _new_genome(self) -> AdversarialGenome:
        if len(self.population) < 2:
            return sample_genome(
                self.rng,
                capabilities=self.capabilities,
                bounds=self.bounds,
            )
        left = self._tournament()
        right = self._tournament()
        child = crossover_genomes(
            left,
            right,
            self.rng,
            bounds=self.bounds,
            config=self.config.variation,
        )
        return mutate_genome(
            child,
            self.rng,
            capabilities=self.capabilities,
            bounds=self.bounds,
            config=self.config.variation,
        )

    def ask(self, count: int) -> list[AdversarialGenome]:
        if count < 1:
            raise ValueError("count must be positive")
        output: list[AdversarialGenome] = []
        attempts = 0
        maximum_attempts = max(100, count * 20)
        known = {item.candidate_id for item in self.population} | set(self.pending)
        while len(output) < count and attempts < maximum_attempts:
            attempts += 1
            candidate = self._new_genome()
            if candidate.digest() in known:
                continue
            known.add(candidate.digest())
            self.pending[candidate.digest()] = candidate
            output.append(candidate)
        if len(output) != count:
            raise RuntimeError("unable to generate the requested number of unique genomes")
        return output

    def _prepare_population(
        self,
        evaluations: list[AggregateEvaluation],
    ) -> list[AggregateEvaluation]:
        return evaluations

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
        combined = self._prepare_population(self.population + evaluations)
        best_by_candidate: dict[str, AggregateEvaluation] = {}
        for item in combined:
            current = best_by_candidate.get(item.candidate_id)
            if current is None or self._rank_key(item) > self._rank_key(current):
                best_by_candidate[item.candidate_id] = item
        self.population = sorted(
            best_by_candidate.values(),
            key=self._rank_key,
            reverse=True,
        )[: self.config.population_size]

    def state_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm_name,
            "rng_state": repr(self.rng.getstate()),
            "population": [item.model_dump(mode="json") for item in self.population],
            "pending": [item.model_dump(mode="json") for item in self.pending.values()],
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if state.get("algorithm") != self.algorithm_name:
            raise ValueError(f"checkpoint algorithm does not match {self.algorithm_name}")
        self.rng.setstate(ast.literal_eval(str(state["rng_state"])))
        self.population = [
            AggregateEvaluation.model_validate(item) for item in state.get("population", [])
        ]
        pending = [AdversarialGenome.model_validate(item) for item in state.get("pending", [])]
        self.pending = {item.digest(): item for item in pending}
