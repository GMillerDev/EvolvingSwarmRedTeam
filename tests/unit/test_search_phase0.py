from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from adversarial_fleet.scenarios import ScenarioCapabilities
from adversarial_fleet.search import AdversarialGenome, WorkloadGenome, decode_genome


def workload_genome() -> AdversarialGenome:
    return AdversarialGenome(
        workload=WorkloadGenome(
            task_count=4,
            arrival_interval_seconds=8.0,
            priority_skew=0.25,
            patrol_routes=(("coe", "lounge"), ("supplies", "pantry")),
        )
    )


def test_capabilities_are_stable_serializable_and_hashable() -> None:
    first = ScenarioCapabilities()
    second = ScenarioCapabilities(
        waypoints=frozenset(reversed(sorted(first.waypoints))),
        robot_ids=frozenset(reversed(sorted(first.robot_ids))),
    )
    assert first.normalized() == second.normalized()
    assert first.digest() == second.digest()
    assert first.normalized()["supports_charger_count"] is False
    assert ScenarioCapabilities.model_validate(json.loads(json.dumps(first.normalized()))) == first

    changed = first.model_copy(update={"supports_door_delay": True})
    assert changed.digest() != first.digest()


def test_genotype_excludes_seeds_and_has_a_stable_hash() -> None:
    genome = workload_genome()
    assert "seed" not in genome.model_dump_json()
    assert genome.digest() == workload_genome().digest()


def test_decode_separates_candidate_realization_and_phenotype() -> None:
    genome = workload_genome()
    capabilities = ScenarioCapabilities()
    first = decode_genome(genome, capabilities=capabilities, realization_seed=1042)
    repeated = decode_genome(genome, capabilities=capabilities, realization_seed=1042)
    second_seed = decode_genome(genome, capabilities=capabilities, realization_seed=1043)

    assert first == repeated
    assert first.candidate_id == genome.digest()
    assert first.candidate_id == second_seed.candidate_id
    assert first.realization_id != second_seed.realization_id
    assert first.phenotype_hash != second_seed.phenotype_hash
    assert first.capabilities_version == capabilities.version
    assert first.capabilities_hash == capabilities.digest()
    assert first.scenario.seed == 1042
    assert first.scenario.tasks.task_count == 4
    assert first.scenario.facility.charger_count == capabilities.default_charger_count


def test_decoder_rejects_waypoint_outside_capability_document() -> None:
    genome = workload_genome().model_copy(
        update={
            "workload": workload_genome().workload.model_copy(
                update={"patrol_routes": (("coe", "unknown_place"),)}
            )
        }
    )
    with pytest.raises(ValueError, match="unknown or unverified waypoints"):
        decode_genome(
            genome,
            capabilities=ScenarioCapabilities(),
            realization_seed=1042,
        )


def test_workload_genome_rejects_consecutive_duplicate_waypoints() -> None:
    with pytest.raises(ValidationError, match="consecutive duplicate"):
        WorkloadGenome(
            task_count=2,
            arrival_interval_seconds=1,
            priority_skew=0,
            patrol_routes=(("coe", "coe"),),
        )
