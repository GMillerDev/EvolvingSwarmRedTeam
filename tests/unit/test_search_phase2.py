from __future__ import annotations

import random
from pathlib import Path

import pytest

from adversarial_fleet.scenarios import ScenarioCapabilities
from adversarial_fleet.search.algorithms import (
    FitnessSharingGeneticAlgorithm,
    SeverityGeneticAlgorithm,
)
from adversarial_fleet.search.config import (
    ConfirmationConfig,
    DescriptorConfig,
    GeneticAlgorithmConfig,
    GenomeBounds,
    VariationConfig,
)
from adversarial_fleet.search.coordinator import (
    evaluate_with_confirmation,
    run_search,
)
from adversarial_fleet.search.descriptors import behavior_distance, novelty_score
from adversarial_fleet.search.evaluation import BehaviorDescriptor, FailureMechanism
from adversarial_fleet.search.evaluator import DeterministicFakeEvaluator
from adversarial_fleet.search.persistence import SearchStore
from adversarial_fleet.search.variation import (
    crossover_genomes,
    mutate_genome,
    sample_genome,
)


CAPABILITIES = ScenarioCapabilities()
BOUNDS = GenomeBounds()
DESCRIPTOR_CONFIG = DescriptorConfig(novelty_k=3)
CONFIRMATION_CONFIG = ConfirmationConfig(confirm_all=True)
REALIZATION_SEEDS = (1042, 1043, 1044)


def _evaluate(genome):
    return evaluate_with_confirmation(
        genome,
        evaluator=DeterministicFakeEvaluator(CAPABILITIES),
        realization_seeds=REALIZATION_SEEDS,
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
        descriptor_config=DESCRIPTOR_CONFIG,
        confirmation_config=CONFIRMATION_CONFIG,
        mission_timeout_seconds=300.0,
    )


def test_behavior_distance_is_symmetric_bounded_and_mask_aware() -> None:
    first = BehaviorDescriptor(
        failure_mechanism=FailureMechanism.DEADLOCK,
        mission_result="failure",
        incomplete_task_ratio=0.5,
        p95_latency_ratio=0.4,
        availability_mask=frozenset(
            {
                "incomplete_task_ratio",
                "p95_latency_ratio",
            }
        ),
    )
    nearby = first.model_copy(update={"p95_latency_ratio": 0.5})
    masked = BehaviorDescriptor(
        failure_mechanism=FailureMechanism.DEADLOCK,
        mission_result="failure",
        incomplete_task_ratio=0.5,
        availability_mask=frozenset({"incomplete_task_ratio"}),
    )
    distant = first.model_copy(
        update={
            "failure_mechanism": FailureMechanism.TASK_STARVATION,
            "mission_result": "timeout",
        }
    )

    assert behavior_distance(first, first, config=DESCRIPTOR_CONFIG) == 0
    assert behavior_distance(first, nearby, config=DESCRIPTOR_CONFIG) == pytest.approx(
        behavior_distance(nearby, first, config=DESCRIPTOR_CONFIG)
    )
    assert 0 < behavior_distance(first, masked, config=DESCRIPTOR_CONFIG) < 1
    assert behavior_distance(first, distant, config=DESCRIPTOR_CONFIG) > behavior_distance(
        first,
        nearby,
        config=DESCRIPTOR_CONFIG,
    )
    assert novelty_score(first, [first, nearby, distant], config=DESCRIPTOR_CONFIG) <= 1


def test_sampling_mutation_and_crossover_are_deterministic_and_valid() -> None:
    variation = VariationConfig(
        mutation_probability=1.0,
        crossover_probability=1.0,
        numeric_sigma=0.2,
    )
    first_rng = random.Random(7001)
    second_rng = random.Random(7001)

    first_parent = sample_genome(first_rng, capabilities=CAPABILITIES, bounds=BOUNDS)
    second_parent = sample_genome(first_rng, capabilities=CAPABILITIES, bounds=BOUNDS)
    repeated_first = sample_genome(second_rng, capabilities=CAPABILITIES, bounds=BOUNDS)
    repeated_second = sample_genome(second_rng, capabilities=CAPABILITIES, bounds=BOUNDS)
    assert (first_parent, second_parent) == (repeated_first, repeated_second)

    child = crossover_genomes(
        first_parent,
        second_parent,
        first_rng,
        bounds=BOUNDS,
        config=variation,
    )
    repeated_child = crossover_genomes(
        repeated_first,
        repeated_second,
        second_rng,
        bounds=BOUNDS,
        config=variation,
    )
    mutated = mutate_genome(
        child,
        first_rng,
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
        config=variation,
    )
    repeated_mutated = mutate_genome(
        repeated_child,
        second_rng,
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
        config=variation,
    )

    assert mutated == repeated_mutated
    assert mutated.digest() != child.digest()
    for route in mutated.workload.patrol_routes:
        assert BOUNDS.route_length_min <= len(route) <= BOUNDS.route_length_max
        assert all(left != right for left, right in zip(route, route[1:]))
        assert set(route) <= CAPABILITIES.waypoints


def test_confirmation_aggregation_is_reproducible() -> None:
    genome = sample_genome(
        random.Random(27),
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
    )

    first = _evaluate(genome)
    repeated = _evaluate(genome)

    assert first == repeated
    assert len(first.runs) == 3
    assert first.reproducibility.valid_run_count == 3
    assert first.reproducibility.score >= 2 / 3
    assert first.robust_severity == first.severity.median
    assert 0 <= first.complexity <= 1
    assert first.reproducibility.continuous_metric_agreement["tasks_completed"]


def test_fitness_sharing_penalizes_a_dense_behavior_niche() -> None:
    genomes = [
        sample_genome(
            random.Random(seed),
            capabilities=CAPABILITIES,
            bounds=BOUNDS,
        )
        for seed in (11, 12, 13)
    ]
    evaluated = [_evaluate(genome) for genome in genomes]
    shared_descriptor = evaluated[0].descriptor
    isolated_descriptor = shared_descriptor.model_copy(
        update={
            "failure_mechanism": FailureMechanism.NEGOTIATION_FAILURE,
            "mission_result": "failure",
        }
    )
    same_severity = evaluated[0].robust_severity
    population = [
        evaluated[0],
        evaluated[1].model_copy(
            update={
                "descriptor": shared_descriptor,
                "robust_severity": same_severity,
                "shared_severity": same_severity,
            }
        ),
        evaluated[2].model_copy(
            update={
                "descriptor": isolated_descriptor,
                "robust_severity": same_severity,
                "shared_severity": same_severity,
            }
        ),
    ]
    algorithm = FitnessSharingGeneticAlgorithm(
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
        config=GeneticAlgorithmConfig(
            population_size=3,
            sharing_radius=0.2,
        ),
        descriptor_config=DESCRIPTOR_CONFIG,
    )

    prepared = algorithm._prepare_population(population)

    assert prepared[0].niche_count == pytest.approx(2.0)
    assert prepared[1].niche_count == pytest.approx(2.0)
    assert prepared[2].niche_count == pytest.approx(1.0)
    assert prepared[0].shared_severity == pytest.approx(same_severity / 2)
    assert prepared[2].shared_severity == pytest.approx(same_severity)


def test_ga_checkpoint_resume_preserves_the_next_generation(tmp_path: Path) -> None:
    config = GeneticAlgorithmConfig(
        search_seed=8201,
        population_size=6,
        offspring_size=4,
    )
    original = SeverityGeneticAlgorithm(
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
        config=config,
    )
    initial = original.ask(6)
    evaluated = [_evaluate(genome) for genome in initial]
    original.tell(evaluated)
    store = SearchStore(tmp_path / "search")
    for item in evaluated:
        store.append_evaluation(item)
    store.save_checkpoint(original.state_dict())

    resumed = SeverityGeneticAlgorithm(
        capabilities=CAPABILITIES,
        bounds=BOUNDS,
        config=config,
    )
    resumed.load_state_dict(store.load_checkpoint())

    assert store.load_evaluations() == evaluated
    assert original.ask(4) == resumed.ask(4)


def test_phase2_search_is_deterministic_and_preserves_distinct_behaviors() -> None:
    algorithm_config = GeneticAlgorithmConfig(
        search_seed=9100,
        population_size=8,
        offspring_size=8,
        tournament_size=3,
        sharing_radius=0.2,
    )

    def execute():
        return run_search(
            FitnessSharingGeneticAlgorithm(
                capabilities=CAPABILITIES,
                bounds=BOUNDS,
                config=algorithm_config,
                descriptor_config=DESCRIPTOR_CONFIG,
            ),
            evaluator=DeterministicFakeEvaluator(CAPABILITIES),
            capabilities=CAPABILITIES,
            bounds=BOUNDS,
            descriptor_config=DESCRIPTOR_CONFIG,
            confirmation_config=CONFIRMATION_CONFIG,
            realization_seeds=REALIZATION_SEEDS,
            iterations=3,
            batch_size=8,
        )

    first = execute()
    repeated = execute()

    assert first == repeated
    assert first.candidate_count == 24
    assert first.realization_run_count == 72
    assert first.confirmed_failure_count > 0
    assert len(first.unique_failure_mechanisms) >= 2
    assert first.best_robust_severity > 0
    assert all(0 <= item.novelty_score <= 1 for item in first.evaluations)
