from __future__ import annotations

import ast
import random
from typing import Any

from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities

from ..config import GenomeBounds
from ..evaluation import AggregateEvaluation
from ..models import AdversarialGenome
from ..variation import sample_genome


class RandomSearch:
    def __init__(
        self,
        *,
        capabilities: ScenarioCapabilities,
        bounds: GenomeBounds,
        search_seed: int,
    ) -> None:
        self.capabilities = capabilities
        self.bounds = bounds
        self.rng = random.Random(search_seed)
        self.evaluations: list[AggregateEvaluation] = []

    def ask(self, count: int) -> list[AdversarialGenome]:
        return [
            sample_genome(
                self.rng,
                capabilities=self.capabilities,
                bounds=self.bounds,
            )
            for _ in range(count)
        ]

    def tell(self, evaluations: list[AggregateEvaluation]) -> None:
        self.evaluations.extend(evaluations)

    def state_dict(self) -> dict[str, Any]:
        return {
            "algorithm": "random_search",
            "rng_state": repr(self.rng.getstate()),
            "evaluations": [item.model_dump(mode="json") for item in self.evaluations],
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if state.get("algorithm") != "random_search":
            raise ValueError("checkpoint algorithm does not match random_search")
        self.rng.setstate(ast.literal_eval(str(state["rng_state"])))
        self.evaluations = [
            AggregateEvaluation.model_validate(item) for item in state.get("evaluations", [])
        ]
