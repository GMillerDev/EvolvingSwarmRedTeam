from __future__ import annotations

import hashlib
import json
import random

from .genome import ScenarioGenome, TaskSpec


def generate_tasks(scenario: ScenarioGenome) -> list[TaskSpec]:
    """Generate a stable task workload without mutating global random state."""
    rng = random.Random(scenario.seed)
    routes = scenario.tasks.patrol_routes
    tasks: list[TaskSpec] = []
    for index in range(scenario.tasks.task_count):
        route = list(routes[index % len(routes)])
        priority = 1 if rng.random() < scenario.tasks.priority_skew else 0
        tasks.append(
            TaskSpec(
                task_id=f"task_{index:04d}",
                places=route,
                start_offset_seconds=index * scenario.tasks.arrival_interval_seconds,
                priority=priority,
            )
        )
    return tasks


def task_sequence_hash(tasks: list[TaskSpec]) -> str:
    canonical = json.dumps(
        [task.model_dump(mode="json") for task in tasks],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
