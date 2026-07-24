# Scenario schema

The source of truth is `adversarial_fleet.scenarios.genome.ScenarioGenome`. Unknown fields are
rejected. The initial Office adapter accepts exactly two configured robots, patrol routes containing
known Office waypoints, and default values for fleet/facility/fault modifiers. This includes the
default charger count of two; changing `charger_count` is rejected because the Office adapter does
not yet have a verified actuator for it.

`failed_robot_id` and `failure_time_seconds` are conditional: the time must be absent when no robot
is selected and is required when a robot is selected. All generated tasks are deterministic for a
normalized scenario and seed.

Evolutionary search uses a separate, seed-free `AdversarialGenome`. Its Phase 0 workload genes are
decoded with a supplied realization seed and a versioned `ScenarioCapabilities` document into a
validated `ScenarioPhenotype`. Candidate identity hashes the genotype; realization identity hashes
the genotype plus realization seed; phenotype identity hashes the resulting `ScenarioGenome`.
