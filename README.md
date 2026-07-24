# Adversarial Fleet Testing

Prototype infrastructure for discovering reproducible fleet-level failures in Open-RMF. The live
vertical slice and the first evolutionary baselines now form this pipeline:

```text
evolutionary search -> capability-valid scenario -> launch Office demo -> submit patrol tasks
                    -> collect events -> calculate severity and behavior -> retain diverse failures
                    -> export replay package
```

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
pytest tests/unit/test_search_phase2.py
```

The `run-scenario` command refuses to start if the scenario requests a mutation the first RMF
adapter cannot apply safely. This prevents invalid setup failures from being rewarded as controller
failures.

## Current status

Implemented and live-validated: typed configuration, scenario validation, deterministic task
generation, unattended RMF Office launch, patrol submission, ROS message conversion, simulation-time
telemetry, fleet metrics, failure classification, MCAP capture, process cleanup, replay export, and
live replay verification. Three same-seed Office runs completed successfully with equivalent outcomes.

Evolutionary-search Phases 2 and 3 are implemented. The available algorithms are severity-only GA,
behavior-space fitness sharing, NSGA-II with explicit severity/novelty/reproducibility/complexity
objectives, and MAP-Elites with behavioral niches and coverage reporting. The search layer has a
deterministic ROS-free evaluator, atomic checkpoints, deterministic archive resume, and elite replay
verification hooks. Connecting the coordinator to the live RMF evaluator remains future integration
work. The complete contract for benchmarking and eventual defender coevolution is documented in
[docs/evolutionary_search_spec.md](docs/evolutionary_search_spec.md).

See [docs/live_validation_report.md](docs/live_validation_report.md),
[docs/phase2_validation_report.md](docs/phase2_validation_report.md),
[docs/phase3_validation_report.md](docs/phase3_validation_report.md),
[docs/rmf_interface_inspection.md](docs/rmf_interface_inspection.md), and
[docs/architecture.md](docs/architecture.md).
