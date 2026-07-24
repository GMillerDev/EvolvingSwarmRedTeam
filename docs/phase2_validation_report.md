# Phase 2 evolutionary-search validation

Date: 2026-07-23  
Platform: Windows development environment, Python 3.12.13

## Result

Phase 2 passed all validation available without launching ROS, Gazebo, or Open-RMF.
The deterministic fixture completed a three-generation behavior-space
fitness-sharing search twice with byte-equivalent structured results.

The smoke-search result was:

```text
candidate_count: 24
realization_run_count: 72
confirmed_failure_count: 18
unique_failure_mechanisms:
  - deadlock
  - task_starvation
  - task_timeout_or_incomplete
best_robust_severity: 7.044642857142857
```

This satisfies the Phase 2 exit criterion that distinct behaviors are preserved in a
deterministic fixture.

## Implemented surface

- Immutable typed bounds, descriptor, confirmation, and GA configuration.
- Deterministic capability-valid sampling, crossover, numeric mutation, and route
  mutation using an injected random-number generator.
- Candidate evaluation states and separate candidate, realization, and phenotype
  identities.
- Observed-behavior descriptors with explicit telemetry availability masks.
- Configured mixed categorical, weighted continuous, and availability-mask distance.
- Population-plus-archive novelty and within-failure-mechanism novelty.
- Screening and common-seed confirmation runs.
- Median robust severity plus minimum, maximum, mean, standard deviation, and
  25th-percentile summaries.
- Modal outcome reproducibility and separately reported continuous-metric agreement.
- Normalized scenario complexity.
- Shared ask/tell interface, severity-only GA, and behavior-space fitness-sharing GA.
- JSONL evaluation persistence and atomic checkpoint/resume.
- Deterministic ROS-free evaluator for repeatable algorithm validation.

## Commands and outcomes

Focused Phase 2 suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_search_phase2.py -q
```

Result: `6 passed`.

Complete repository regression suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result: `25 passed`.

Phase 0 and Phase 2 search coverage:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_search_phase0.py `
  tests\unit\test_search_phase2.py `
  --cov=adversarial_fleet.search `
  --cov-report=term-missing -q
```

Result: `11 passed`; total search-package statement coverage: `91%`.

Static checks:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check `
  src\adversarial_fleet\search `
  tests\unit\test_search_phase0.py `
  tests\unit\test_search_phase2.py
.\.venv\Scripts\python.exe -m compileall -q src
git diff --check
```

Result: all checks passed. All Phase 0/2 search files are formatted, and the repository
has no lint, import, bytecode-compilation, or changed-line whitespace errors.

## Validated properties

| Property | Evidence |
| --- | --- |
| Deterministic sampling and variation | Two fixed-seed operator streams produced identical parents and offspring. |
| Capability validity | Every tested route stayed within waypoint and route bounds and rejected consecutive duplicates. |
| Behavior distance | Identity, symmetry, bounds, categorical separation, and missing-data mask behavior passed. |
| Confirmation | Three common realization seeds were retained and aggregated deterministically. |
| Reproducibility | Modal outcome agreement and configured continuous-metric agreement were calculated and checked. |
| Diversity pressure | Two candidates in the same niche received a niche count of 2 and half the shared severity of an equally severe isolated behavior. |
| Search diversity | The deterministic smoke search retained three distinct confirmed failure mechanisms. |
| Resume | A serialized checkpoint resumed with the exact same next offspring batch as the uninterrupted algorithm. |
| Regression safety | All pre-existing scenario, metrics, replay, ROS collector, and event tests passed. |

## Boundaries and remaining integration

This validation does not claim a live evolutionary run. ROS, Gazebo, and Open-RMF
were deliberately not launched because the Phase 2 objective and algorithm layer is
pure Python. The existing live vertical slice remains separate.

Before search can drive live RMF experiments, the remaining Phase 1 integration work
is:

1. Implement a live `CandidateEvaluator` that decodes a genome and delegates to
   `ExperimentOrchestrator`.
2. Add the environment-aware terminal evaluation cache required by the specification.
3. Add CLI/config wiring for starting, stopping, resuming, and inspecting search runs.
4. Run a bounded live smoke search and compare its persisted artifacts with the
   deterministic fixture contract.

NSGA-II, MAP-Elites, benchmarking, and defender coevolution are Phase 3 and later and
were not implemented in this phase.
