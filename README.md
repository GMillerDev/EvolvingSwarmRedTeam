# Adversarial Fleet Testing

Prototype infrastructure for discovering reproducible fleet-level failures in Open-RMF. The current
milestone is the smallest deterministic vertical slice:

```text
scenario.yaml -> launch Office demo -> submit patrol tasks -> collect events
              -> calculate metrics and score -> classify -> export replay package
```

The optimizer is intentionally deferred until this path has run end to end in the real simulator.

## Target environment

- Ubuntu 24.04
- ROS 2 Kilted
- Gazebo Ionic
- Open-RMF / `rmf_demos` 2.9.0 environment
- Python 3.12+

The repository can be developed and unit-tested without ROS, but a real scenario run requires the
target environment. The Compose configuration defaults to the exact RMF demos image digest used for
the live validation. See [docs/live_environment_setup.md](docs/live_environment_setup.md).

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
aft health-check --config configs/default.yaml
aft validate-scenario --scenario configs/example_scenario.yaml
aft run-scenario --scenario configs/example_scenario.yaml --config configs/default.yaml
```

The `run-scenario` command refuses to start if the scenario requests a mutation the first RMF
adapter cannot apply safely. This prevents invalid setup failures from being rewarded as controller
failures.

## Current status

Implemented and live-validated: typed configuration, scenario validation, deterministic task
generation, unattended RMF Office launch, patrol submission, ROS message conversion, simulation-time
telemetry, fleet metrics, failure classification, MCAP capture, process cleanup, replay export, and
live replay verification. Three same-seed Office runs completed successfully with equivalent outcomes.

Search algorithms remain intentionally unimplemented; this milestone covers only the live vertical
slice. The implementation contract for adversarial evolution, behavioral novelty, quality-diversity
search, benchmarking, and eventual defender coevolution is documented in
[docs/evolutionary_search_spec.md](docs/evolutionary_search_spec.md).

See [docs/live_validation_report.md](docs/live_validation_report.md),
[docs/rmf_interface_inspection.md](docs/rmf_interface_inspection.md), and
[docs/architecture.md](docs/architecture.md).
