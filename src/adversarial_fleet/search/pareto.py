from __future__ import annotations

from collections.abc import Iterable

from .evaluation import AggregateEvaluation


def is_feasible(evaluation: AggregateEvaluation) -> bool:
    return bool(evaluation.runs) and all(run.state.is_valid_run for run in evaluation.runs)


def objective_vector(evaluation: AggregateEvaluation) -> tuple[float, float, float, float]:
    """Return all canonical objectives in maximize orientation."""

    return (
        evaluation.robust_severity,
        evaluation.novelty_score,
        evaluation.reproducibility.score,
        1.0 - evaluation.complexity,
    )


def dominates(left: AggregateEvaluation, right: AggregateEvaluation) -> bool:
    left_feasible = is_feasible(left)
    right_feasible = is_feasible(right)
    if left_feasible != right_feasible:
        return left_feasible
    if not left_feasible:
        return False
    left_values = objective_vector(left)
    right_values = objective_vector(right)
    return all(a >= b for a, b in zip(left_values, right_values)) and any(
        a > b for a, b in zip(left_values, right_values)
    )


def non_dominated_sort(
    evaluations: Iterable[AggregateEvaluation],
) -> list[list[AggregateEvaluation]]:
    population = sorted(evaluations, key=lambda item: item.candidate_id)
    if len(population) != len({item.candidate_id for item in population}):
        raise ValueError("non-dominated sorting requires unique candidate IDs")
    dominated_by_count = {item.candidate_id: 0 for item in population}
    dominates_ids: dict[str, list[str]] = {item.candidate_id: [] for item in population}
    by_id = {item.candidate_id: item for item in population}

    for index, left in enumerate(population):
        for right in population[index + 1 :]:
            if dominates(left, right):
                dominates_ids[left.candidate_id].append(right.candidate_id)
                dominated_by_count[right.candidate_id] += 1
            elif dominates(right, left):
                dominates_ids[right.candidate_id].append(left.candidate_id)
                dominated_by_count[left.candidate_id] += 1

    current = sorted(
        candidate_id for candidate_id, count in dominated_by_count.items() if count == 0
    )
    fronts: list[list[AggregateEvaluation]] = []
    while current:
        fronts.append([by_id[candidate_id] for candidate_id in current])
        following: list[str] = []
        for candidate_id in current:
            for dominated_id in dominates_ids[candidate_id]:
                dominated_by_count[dominated_id] -= 1
                if dominated_by_count[dominated_id] == 0:
                    following.append(dominated_id)
        current = sorted(following)
    return fronts


def crowding_distances(
    front: Iterable[AggregateEvaluation],
) -> dict[str, float | None]:
    """Return normalized NSGA-II crowding; None represents an unbounded edge."""

    population = tuple(front)
    distances: dict[str, float | None] = {item.candidate_id: 0.0 for item in population}
    if len(population) <= 2:
        return {item.candidate_id: None for item in population}

    for objective_index in range(4):
        ordered = sorted(
            population,
            key=lambda item: (objective_vector(item)[objective_index], item.candidate_id),
        )
        values = [objective_vector(item)[objective_index] for item in ordered]
        lower = values[0]
        upper = values[-1]
        if upper == lower:
            continue
        for item, value in zip(ordered, values):
            if value == lower or value == upper:
                distances[item.candidate_id] = None
        for index in range(1, len(ordered) - 1):
            candidate_id = ordered[index].candidate_id
            if distances[candidate_id] is None:
                continue
            contribution = (values[index + 1] - values[index - 1]) / (upper - lower)
            distances[candidate_id] = float(distances[candidate_id]) + contribution
    return distances


def annotate_pareto_fronts(
    evaluations: Iterable[AggregateEvaluation],
) -> list[list[AggregateEvaluation]]:
    annotated: list[list[AggregateEvaluation]] = []
    for rank, front in enumerate(non_dominated_sort(evaluations)):
        crowding = crowding_distances(front)
        annotated.append(
            [
                item.model_copy(
                    update={
                        "pareto_rank": rank,
                        "crowding_distance": crowding[item.candidate_id],
                    }
                )
                for item in front
            ]
        )
    return annotated
