from __future__ import annotations

import random

from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities

from .config import GenomeBounds, VariationConfig
from .models import AdversarialGenome, WorkloadGenome


def _random_route(
    rng: random.Random,
    waypoints: tuple[str, ...],
    length: int,
) -> tuple[str, ...]:
    route = [rng.choice(waypoints)]
    while len(route) < length:
        route.append(rng.choice(tuple(item for item in waypoints if item != route[-1])))
    return tuple(route)


def sample_genome(
    rng: random.Random,
    *,
    capabilities: ScenarioCapabilities,
    bounds: GenomeBounds,
) -> AdversarialGenome:
    waypoints = tuple(sorted(capabilities.waypoints))
    if len(waypoints) < 2:
        raise ValueError("genome sampling requires at least two capability waypoints")
    route_count = rng.randint(bounds.route_count_min, bounds.route_count_max)
    routes = tuple(
        _random_route(
            rng,
            waypoints,
            rng.randint(bounds.route_length_min, bounds.route_length_max),
        )
        for _ in range(route_count)
    )
    return AdversarialGenome(
        workload=WorkloadGenome(
            task_count=rng.randint(bounds.task_count_min, bounds.task_count_max),
            arrival_interval_seconds=rng.uniform(
                bounds.arrival_interval_min,
                bounds.arrival_interval_max,
            ),
            priority_skew=rng.uniform(
                bounds.priority_skew_min,
                bounds.priority_skew_max,
            ),
            patrol_routes=routes,
        )
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _repair_route(route: list[str]) -> list[str]:
    repaired: list[str] = []
    for waypoint in route:
        if not repaired or repaired[-1] != waypoint:
            repaired.append(waypoint)
    return repaired


def _crossover_route(
    left: tuple[str, ...],
    right: tuple[str, ...],
    rng: random.Random,
    *,
    bounds: GenomeBounds,
) -> tuple[str, ...] | None:
    left_cut = rng.randrange(1, len(left))
    right_cut = rng.randrange(1, len(right))
    route = _repair_route(list(left[:left_cut] + right[right_cut:]))
    route = route[: bounds.route_length_max]
    if len(route) < bounds.route_length_min:
        return None
    return tuple(route)


def _mutate_routes(
    routes: list[list[str]],
    *,
    rng: random.Random,
    capabilities: ScenarioCapabilities,
    bounds: GenomeBounds,
) -> None:
    original = [route.copy() for route in routes]
    waypoints = tuple(sorted(capabilities.waypoints))
    operation = rng.choice(("substitute", "insert", "delete", "reverse", "add", "remove"))
    route_index = rng.randrange(len(routes))
    route = routes[route_index]
    if operation == "substitute":
        index = rng.randrange(len(route))
        excluded = {route[index]}
        if index > 0:
            excluded.add(route[index - 1])
        if index + 1 < len(route):
            excluded.add(route[index + 1])
        choices = tuple(item for item in waypoints if item not in excluded)
        if choices:
            route[index] = rng.choice(choices)
    elif operation == "insert" and len(route) < bounds.route_length_max:
        index = rng.randrange(len(route) + 1)
        excluded = set()
        if index > 0:
            excluded.add(route[index - 1])
        if index < len(route):
            excluded.add(route[index])
        route.insert(index, rng.choice(tuple(item for item in waypoints if item not in excluded)))
    elif operation == "delete" and len(route) > bounds.route_length_min:
        del route[rng.randrange(len(route))]
    elif operation == "reverse" and len(route) > 2:
        left, right = sorted(rng.sample(range(len(route)), 2))
        route[left : right + 1] = reversed(route[left : right + 1])
        routes[route_index] = _repair_route(route)
    elif operation == "add" and len(routes) < bounds.route_count_max:
        routes.append(
            list(
                _random_route(
                    rng,
                    waypoints,
                    rng.randint(bounds.route_length_min, bounds.route_length_max),
                )
            )
        )
    elif operation == "remove" and len(routes) > bounds.route_count_min:
        del routes[route_index]
    if not (
        bounds.route_count_min <= len(routes) <= bounds.route_count_max
        and all(
            bounds.route_length_min <= len(item) <= bounds.route_length_max
            and all(left != right for left, right in zip(item, item[1:]))
            for item in routes
        )
    ):
        routes[:] = original


def mutate_genome(
    genome: AdversarialGenome,
    rng: random.Random,
    *,
    capabilities: ScenarioCapabilities,
    bounds: GenomeBounds,
    config: VariationConfig,
) -> AdversarialGenome:
    workload = genome.workload
    task_count = workload.task_count
    interval = workload.arrival_interval_seconds
    priority = workload.priority_skew
    routes = [list(route) for route in workload.patrol_routes]
    probability = config.mutation_probability

    if rng.random() < probability:
        task_count = int(
            _clamp(
                task_count + rng.choice((-2, -1, 1, 2)),
                bounds.task_count_min,
                bounds.task_count_max,
            )
        )
    if rng.random() < probability:
        span = bounds.arrival_interval_max - bounds.arrival_interval_min
        interval = _clamp(
            interval + rng.gauss(0, config.numeric_sigma * span),
            bounds.arrival_interval_min,
            bounds.arrival_interval_max,
        )
    if rng.random() < probability:
        span = bounds.priority_skew_max - bounds.priority_skew_min
        priority = _clamp(
            priority + rng.gauss(0, config.numeric_sigma * span),
            bounds.priority_skew_min,
            bounds.priority_skew_max,
        )
    if rng.random() < probability:
        _mutate_routes(
            routes,
            rng=rng,
            capabilities=capabilities,
            bounds=bounds,
        )

    candidate = AdversarialGenome(
        workload=WorkloadGenome(
            task_count=task_count,
            arrival_interval_seconds=interval,
            priority_skew=priority,
            patrol_routes=tuple(tuple(route) for route in routes),
        )
    )
    if candidate.digest() == genome.digest():
        if bounds.task_count_min < bounds.task_count_max:
            forced_task_count = (
                task_count + 1 if task_count < bounds.task_count_max else task_count - 1
            )
            candidate = AdversarialGenome(
                workload=WorkloadGenome(
                    **candidate.workload.model_dump(exclude={"task_count"}),
                    task_count=forced_task_count,
                )
            )
        else:
            waypoints = tuple(sorted(capabilities.waypoints))
            for _ in range(20):
                forced_routes = [list(route) for route in routes]
                route_index = rng.randrange(len(forced_routes))
                forced_routes[route_index] = list(
                    _random_route(rng, waypoints, len(forced_routes[route_index]))
                )
                candidate = AdversarialGenome(
                    workload=WorkloadGenome(
                        **candidate.workload.model_dump(exclude={"patrol_routes"}),
                        patrol_routes=tuple(tuple(route) for route in forced_routes),
                    )
                )
                if candidate.digest() != genome.digest():
                    break
    if candidate.digest() == genome.digest():
        raise RuntimeError("unable to mutate genome within the configured search space")
    return candidate


def crossover_genomes(
    left: AdversarialGenome,
    right: AdversarialGenome,
    rng: random.Random,
    *,
    bounds: GenomeBounds,
    config: VariationConfig,
) -> AdversarialGenome:
    if rng.random() >= config.crossover_probability:
        return left
    left_routes = left.workload.patrol_routes
    right_routes = right.workload.patrol_routes
    left_cut = rng.randrange(len(left_routes) + 1)
    right_cut = rng.randrange(len(right_routes) + 1)
    routes = list(left_routes[:left_cut] + right_routes[right_cut:])
    if len(routes) < bounds.route_count_min:
        routes = list(left_routes[: bounds.route_count_min])
    routes = routes[: bounds.route_count_max]
    mixed_route = _crossover_route(
        rng.choice(left_routes),
        rng.choice(right_routes),
        rng,
        bounds=bounds,
    )
    if mixed_route is not None:
        routes[rng.randrange(len(routes))] = mixed_route
    return AdversarialGenome(
        workload=WorkloadGenome(
            task_count=rng.choice((left.workload.task_count, right.workload.task_count)),
            arrival_interval_seconds=rng.choice(
                (
                    left.workload.arrival_interval_seconds,
                    right.workload.arrival_interval_seconds,
                )
            ),
            priority_skew=rng.choice((left.workload.priority_skew, right.workload.priority_skew)),
            patrol_routes=tuple(routes),
        )
    )
