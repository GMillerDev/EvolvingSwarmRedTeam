from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from adversarial_fleet.coevolution.config import (
    CoevolutionFileConfig,
    CoevolutionSettings,
    DefenderBounds,
)
from adversarial_fleet.coevolution.evaluator import VersionedDefender, synthetic_defender
from adversarial_fleet.coevolution.models import DefenderGenome
from adversarial_fleet.coevolution.runner import CoevolutionRunner
from adversarial_fleet.coevolution.verifier import CrossplayVerifier
from adversarial_fleet.config import AppConfig, ProjectConfig
from adversarial_fleet.orchestrator.rmf_adapter import RmfDemoAdapter
from adversarial_fleet.scenarios import ScenarioCapabilities
from adversarial_fleet.search import AdversarialGenome, FacilitySearchGenome, WorkloadGenome
from adversarial_fleet.search.config import GenomeBounds, VariationConfig
from adversarial_fleet.search.encoding import decode_genome
from adversarial_fleet.search.variation import crossover_genomes, mutate_genome, sample_genome
from adversarial_fleet.telemetry.ros_topics import ROSBAG_TOPICS


def _workload_only() -> AdversarialGenome:
    return AdversarialGenome(
        workload=WorkloadGenome(
            task_count=4,
            arrival_interval_seconds=8.0,
            priority_skew=0.25,
            patrol_routes=(("coe", "lounge"), ("supplies", "pantry")),
        )
    )


def _small_config(experiment_id: str) -> CoevolutionFileConfig:
    return CoevolutionFileConfig(
        coevolution=CoevolutionSettings(
            experiment_id=experiment_id,
            seed=12001,
            generations=3,
            scenario_population_size=4,
            defender_population_size=4,
            scenario_elite_count=1,
            defender_elite_count=1,
            severe_archive_size=4,
            novel_archive_size=4,
            defender_hall_of_fame_size=4,
            realization_seeds=(1042, 1043),
            verify_payoffs=True,
        )
    )


def test_lane_closure_gene_is_capability_gated_and_preserves_old_identity() -> None:
    workload = _workload_only()
    assert "facility" not in workload.normalized()
    enabled = ScenarioCapabilities(
        version="office-lane-test-v1",
        lane_ids=frozenset({"3", "7"}),
        supports_lane_closure=True,
    )
    lane_genome = workload.model_copy(
        update={"facility": FacilitySearchGenome(blocked_lane_id="3")}
    )
    phenotype = decode_genome(lane_genome, capabilities=enabled, realization_seed=1042)
    assert phenotype.scenario.facility.blocked_lane_id == "3"
    assert phenotype.candidate_id != workload.digest()

    with pytest.raises(ValueError, match="not in the verified navigable lane set"):
        decode_genome(
            lane_genome.model_copy(update={"facility": FacilitySearchGenome(blocked_lane_id="99")}),
            capabilities=enabled,
            realization_seed=1042,
        )
    with pytest.raises(ValueError, match="lane closure is not verified"):
        decode_genome(
            lane_genome,
            capabilities=enabled.model_copy(update={"supports_lane_closure": False}),
            realization_seed=1042,
        )


def test_lane_closure_sampling_mutation_and_crossover_are_valid() -> None:
    capabilities = ScenarioCapabilities(
        version="office-lane-test-v1",
        lane_ids=frozenset({"3", "7"}),
        supports_lane_closure=True,
    )
    bounds = GenomeBounds(lane_closure_probability=1.0)
    first_rng = random.Random(6001)
    second_rng = random.Random(6001)
    first = sample_genome(first_rng, capabilities=capabilities, bounds=bounds)
    repeated = sample_genome(second_rng, capabilities=capabilities, bounds=bounds)
    assert first == repeated
    assert first.facility is not None
    assert first.facility.blocked_lane_id in capabilities.lane_ids

    mutation = mutate_genome(
        first,
        random.Random(6002),
        capabilities=capabilities,
        bounds=bounds,
        config=VariationConfig(mutation_probability=1.0),
    )
    decode_genome(mutation, capabilities=capabilities, realization_seed=1042)
    child = crossover_genomes(
        first,
        first.model_copy(update={"facility": None}),
        random.Random(6003),
        bounds=bounds,
        config=VariationConfig(crossover_probability=1.0),
    )
    decode_genome(child, capabilities=capabilities, realization_seed=1042)


def test_lane_closure_telemetry_parser_requires_fleet_and_lane() -> None:
    output = "fleet_name: tinyRobot\nclosed_lanes:\n- 3\n- 7\n---\n"
    assert RmfDemoAdapter._closed_lane_is_reported(
        output,
        fleet_name="tinyRobot",
        lane_id="3",
    )
    assert not RmfDemoAdapter._closed_lane_is_reported(
        output,
        fleet_name="otherFleet",
        lane_id="3",
    )
    assert not RmfDemoAdapter._closed_lane_is_reported(
        output,
        fleet_name="tinyRobot",
        lane_id="8",
    )


def test_lane_closure_command_and_state_are_both_recorded() -> None:
    assert "/lane_closure_requests" in ROSBAG_TOPICS
    assert "/closed_lanes" in ROSBAG_TOPICS


def test_lane_closure_actuator_publishes_and_verifies_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capabilities = ScenarioCapabilities(
        version="office-lane-test-v1",
        lane_ids=frozenset({"3"}),
        supports_lane_closure=True,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    adapter = RmfDemoAdapter(
        AppConfig(project=ProjectConfig(output_dir=tmp_path)),
        run_dir,
        capabilities=capabilities,
    )
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "/closed_lanes" in command[-1]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="fleet_name: tinyRobot\nclosed_lanes:\n- 3\n---\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="published", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    adapter._set_lane_closed("3", closed=True)

    assert len(calls) == 2
    assert "/lane_closure_requests" in calls[0][-1]
    assert "--wait-matching-subscriptions 2" in calls[0][-1]
    assert "close_lanes: [3]" in calls[0][-1]
    events = adapter.events_path.read_text(encoding="utf-8")
    assert '"event":"lane_closed"' in events
    assert '"actuator_verified":true' in events


def test_lane_closure_actuator_retries_a_discovery_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capabilities = ScenarioCapabilities(
        version="office-lane-test-v1",
        lane_ids=frozenset({"3"}),
        supports_lane_closure=True,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    adapter = RmfDemoAdapter(
        AppConfig(project=ProjectConfig(output_dir=tmp_path)),
        run_dir,
        capabilities=capabilities,
    )
    echo_attempts = 0

    def fake_run(command, **kwargs):
        nonlocal echo_attempts
        if "/closed_lanes" in command[-1]:
            echo_attempts += 1
            if echo_attempts == 1:
                return subprocess.CompletedProcess(command, 124, stdout="", stderr="")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="fleet_name: tinyRobot\nclosed_lanes:\n- 3\n---\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="published", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("adversarial_fleet.orchestrator.rmf_adapter.time.sleep", lambda _: None)
    adapter._set_lane_closed("3", closed=True)

    assert echo_attempts == 2


def test_defender_artifact_is_versioned_and_materializable(tmp_path: Path) -> None:
    genome = DefenderGenome(
        congestion_resilience=0.2,
        priority_fairness=0.4,
        coordination_horizon=0.6,
        recovery_aggressiveness=0.8,
    )
    artifact = synthetic_defender(genome)
    runtime = VersionedDefender(artifact).materialize(tmp_path / "defender")
    persisted = json.loads(Path(runtime.artifact_path).read_text(encoding="utf-8"))

    assert artifact.artifact_version == genome.digest()
    assert runtime.defender_id == artifact.defender_id
    assert persisted == artifact.model_dump(mode="json")


def test_coevolution_config_rejects_non_evolving_elitism() -> None:
    with pytest.raises(ValidationError, match="scenario_elite_count"):
        CoevolutionSettings(
            scenario_population_size=4,
            scenario_elite_count=4,
        )
    with pytest.raises(ValidationError, match="must not exceed"):
        DefenderBounds(
            congestion_resilience_min=0.8,
            congestion_resilience_max=0.2,
        )


def test_coevolution_crossplay_hall_of_fame_retention_and_replay(tmp_path: Path) -> None:
    output = tmp_path / "output"
    report = CoevolutionRunner(
        app_config=AppConfig(project=ProjectConfig(output_dir=output)),
        coevolution_config=_small_config("phase6-test"),
    ).run()
    root = output / "coevolution" / "phase6-test"

    assert report.status == "completed"
    assert report.scenario_population_adapted
    assert report.defender_population_adapted
    assert report.retention_requirement_met
    assert report.severe_archive_size > 0
    assert report.novel_archive_size > 0
    assert report.defender_hall_of_fame_size > 0
    assert report.verification.verified
    assert report.verification.matched_payoff_count == report.payoff_count
    assert report.unique_scenario_count > 4
    assert report.unique_defender_count > 5

    payoffs = [
        json.loads(line)
        for line in (root / "payoff_matrix.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {item["scenario_role"] for item in payoffs} == {
        "current",
        "severe_archive",
        "novel_archive",
        "standard",
    }
    assert {item["defender_role"] for item in payoffs} == {
        "current",
        "hall_of_fame",
        "baseline",
    }
    assert all(item["replay_digest"] for item in payoffs)
    assert CrossplayVerifier().verify(root).verified
    assert (root / "report.md").is_file()
    assert (root / "participants.json").is_file()


def test_fake_coevolution_is_deterministic_and_tamper_evident(tmp_path: Path) -> None:
    app = AppConfig(project=ProjectConfig(output_dir=tmp_path / "output"))
    first = CoevolutionRunner(
        app_config=app,
        coevolution_config=_small_config("repro-a"),
    ).run()
    second = CoevolutionRunner(
        app_config=app,
        coevolution_config=_small_config("repro-b"),
    ).run()
    assert first.scientific_fingerprint == second.scientific_fingerprint

    matrix = Path(first.experiment_directory) / "payoff_matrix.jsonl"
    lines = matrix.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["scenario_payoff"] += 0.01
    lines[0] = json.dumps(record, sort_keys=True)
    matrix.write_text("\n".join(lines) + "\n", encoding="utf-8")
    verification = CrossplayVerifier().verify(Path(first.experiment_directory))
    assert not verification.verified
    assert verification.mismatch_count == 1
