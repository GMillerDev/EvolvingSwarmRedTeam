# Scenario schema

The source of truth is `adversarial_fleet.scenarios.genome.ScenarioGenome`. Unknown fields are
rejected. The initial Office adapter accepts exactly two configured robots, patrol routes containing
known Office waypoints, and default values for fleet/facility/fault modifiers.

`failed_robot_id` and `failure_time_seconds` are conditional: the time must be absent when no robot
is selected and is required when a robot is selected. All generated tasks are deterministic for a
normalized scenario and seed.

