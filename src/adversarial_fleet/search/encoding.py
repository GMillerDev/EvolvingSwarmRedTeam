from __future__ import annotations

from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities
from adversarial_fleet.scenarios.genome import (
    FacilityGenome,
    FaultGenome,
    FleetGenome,
    ScenarioGenome,
    TaskGenome,
)
from adversarial_fleet.scenarios.validation import validate_scenario

from .models import AdversarialGenome, ScenarioPhenotype, ScenarioRealization


def decode_genome(
    genome: AdversarialGenome,
    *,
    capabilities: ScenarioCapabilities,
    realization_seed: int,
) -> ScenarioPhenotype:
    """Decode capability-safe search genes into a validated live scenario."""

    realization = ScenarioRealization.from_genome(
        genome,
        realization_seed=realization_seed,
    )
    workload = genome.workload
    scenario = ScenarioGenome(
        seed=realization_seed,
        fleet=FleetGenome(
            robot_count=capabilities.supported_robot_count,
            max_speed_multiplier=1.0,
            acceleration_multiplier=1.0,
        ),
        tasks=TaskGenome(
            task_count=workload.task_count,
            arrival_interval_seconds=workload.arrival_interval_seconds,
            priority_skew=workload.priority_skew,
            patrol_routes=[list(route) for route in workload.patrol_routes],
        ),
        facility=FacilityGenome(
            blocked_lane_id=(None if genome.facility is None else genome.facility.blocked_lane_id),
            door_delay_seconds=0.0,
            charger_count=capabilities.default_charger_count,
        ),
        faults=FaultGenome(
            failed_robot_id=None,
            failure_time_seconds=None,
            state_update_latency_ms=0,
        ),
    )
    validate_scenario(scenario, capabilities).require_valid()
    return ScenarioPhenotype(
        realization=realization,
        capabilities_version=capabilities.version,
        capabilities_hash=capabilities.digest(),
        scenario=scenario,
        phenotype_hash=scenario.digest(),
    )
