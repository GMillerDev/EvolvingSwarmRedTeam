from __future__ import annotations

from ..evaluation import AggregateEvaluation
from ..pareto import annotate_pareto_fronts
from .severity_ga import SeverityGeneticAlgorithm


class NSGA2Algorithm(SeverityGeneticAlgorithm):
    algorithm_name = "nsga2"

    @staticmethod
    def _selection_key(
        item: AggregateEvaluation,
    ) -> tuple[float, float, float, float, float, float, str]:
        rank = item.pareto_rank if item.pareto_rank is not None else 2**31
        boundary = item.crowding_distance is None
        crowding = item.crowding_distance or 0.0
        return (
            -float(rank),
            float(boundary),
            crowding,
            item.novelty_score,
            item.robust_severity,
            item.reproducibility.score,
            item.candidate_id,
        )

    def _rank_key(
        self,
        item: AggregateEvaluation,
    ) -> tuple[float, float, float, float, float, float, str]:
        return self._selection_key(item)

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

        best_by_candidate: dict[str, AggregateEvaluation] = {}
        for item in self.population + evaluations:
            current = best_by_candidate.get(item.candidate_id)
            if current is None or (
                item.robust_severity,
                item.novelty_score,
                item.reproducibility.score,
                -item.complexity,
            ) > (
                current.robust_severity,
                current.novelty_score,
                current.reproducibility.score,
                -current.complexity,
            ):
                best_by_candidate[item.candidate_id] = item

        survivors: list[AggregateEvaluation] = []
        for front in annotate_pareto_fronts(best_by_candidate.values()):
            remaining = self.config.population_size - len(survivors)
            if remaining <= 0:
                break
            if len(front) <= remaining:
                survivors.extend(front)
                continue
            survivors.extend(sorted(front, key=self._selection_key, reverse=True)[:remaining])
            break
        self.population = sorted(survivors, key=self._selection_key, reverse=True)
