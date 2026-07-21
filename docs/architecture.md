# Architecture

`ExperimentOrchestrator` owns a single candidate lifecycle and depends only on the
`SimulationAdapter` protocol. `RmfDemoAdapter` is the concrete boundary for Open-RMF and delegates
all operating-system process work to `ProcessManager`. The rest of the pipeline consumes normalized
JSONL events, not ROS message objects.

This separation is deliberate: RMF's Kilted Python packages are present only inside a sourced ROS
environment, while scenario validation, metrics, failure detection, replay packaging, and search can
be deterministic ordinary Python.

The initial adapter launches a fresh Office process group per candidate. It does not reuse Gazebo
state. A candidate transitions through `created`, `starting`, `ready`, `running`, and one terminal
state. Shutdown is attempted in a `finally` block, followed by process-group termination and an
orphan check.

## Event contract

Events are newline-delimited JSON objects with at least `timestamp` (simulation seconds where
available) and `event`. Task events use `task_id`; robot observations use `robot_id`, `x`, `y`, and
`task_active`. The metrics and failure layers are pure functions over this contract.

## Trust boundaries

- Scenario files are validated before any process starts.
- Task locations are constrained to the selected world's allowlist.
- Shell setup paths and launch tokens originate from typed local configuration.
- Upstream launch failures produce a startup penalty, never a positive failure score.
- Runtime mutations that have not been verified against RMF are rejected rather than approximated.

