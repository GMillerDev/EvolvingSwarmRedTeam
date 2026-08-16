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
aft search --search-config configs/search/phase4_fake_review.yaml --config configs/default.yaml
aft inspect-archive --search results/searches/<search_id> --format markdown
aft benchmark --benchmark-config configs/benchmarks/phase5_fake_validation.yaml --config configs/default.yaml
aft coevolve --coevolution-config configs/coevolution/phase6_fake_validation.yaml --config configs/default.yaml
aft verify-crossplay --package results/coevolution/<experiment_id>
pytest tests/unit/test_benchmarks_phase5.py
```

The bounded live Office search is run inside the pinned container:

```powershell
docker compose -f docker/docker-compose.yml run --rm aft search `
  --search-config configs/search/phase4_live_smoke.yaml `
  --config configs/default.yaml
```

The `run-scenario` command refuses to start if the scenario requests a mutation the first RMF
adapter cannot apply safely. This prevents invalid setup failures from being rewarded as controller
failures.

## Current status

Implemented and live-validated: typed configuration, scenario validation, deterministic task
generation, unattended RMF Office launch, patrol submission, ROS message conversion, simulation-time
telemetry, fleet metrics, failure classification, MCAP capture, process cleanup, replay export, and
live replay verification. Three same-seed Office runs completed successfully with equivalent outcomes.

Evolutionary-search Phases 2 through 6 are implemented. The available algorithms are severity-only
GA, behavior-space fitness sharing, NSGA-II, and MAP-Elites. The Phase 4 runner connects the same
ask/tell layer to the real Open-RMF orchestrator with exact budgets, environment-aware caching,
batch-boundary resume, complete search artifacts, archive inspection, weakness diagnostics, replay
verification, and cleanup accounting. A bounded live Office search and its replay have completed
unattended with zero orphan processes. Phase 5 adds equal-budget multi-seed benchmarking, fairness
fingerprints, budget-checkpoint measures, deterministic bootstrap uncertainty, paired comparisons,
and reproducibility verification from persisted configurations. Its validation uses the fake
evaluator and therefore makes no live performance or superiority claim. Phase 6 adds a
capability-gated lane-closure gene and live RMF actuator, exact capability-aware replay, versioned
defender artifacts, two-population cross-play, severe/novel archives, a defender hall of fame,
standard-mission retention, and full payoff recomputation. The lane actuator and replay are live
validated; evolved defenders remain synthetic and do not yet train a live RMF controller. The
complete contract is in [docs/evolutionary_search_spec.md](docs/evolutionary_search_spec.md).

See [docs/live_validation_report.md](docs/live_validation_report.md),
[docs/phase2_validation_report.md](docs/phase2_validation_report.md),
[docs/phase3_validation_report.md](docs/phase3_validation_report.md),
[docs/phase4_validation_report.md](docs/phase4_validation_report.md),
[docs/phase5_validation_report.md](docs/phase5_validation_report.md),
[docs/phase6_validation_report.md](docs/phase6_validation_report.md),
[docs/rmf_interface_inspection.md](docs/rmf_interface_inspection.md), and
[docs/architecture.md](docs/architecture.md).
