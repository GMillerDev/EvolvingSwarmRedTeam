# Phase 3 quality-diversity validation

Date: 2026-07-23  
Platform: Windows development environment, Python 3.12.13

## Result

Phase 3 passed all deterministic validation available without launching ROS, Gazebo,
or Open-RMF. Both quality-diversity algorithms completed repeated four-generation
searches with identical candidate sequences, objective results, populations, and
archives.

NSGA-II smoke-search result:

```text
candidate_count: 48
realization_run_count: 144
confirmed_failure_count: 20
unique_failure_mechanisms:
  - deadlock
  - task_starvation
  - task_timeout_or_incomplete
best_robust_severity: 7.005
pareto_front_size: 12
```

MAP-Elites smoke-search result:

```text
candidate_count: 48
realization_run_count: 144
confirmed_failure_count: 39
unique_failure_mechanisms:
  - deadlock
  - latency_degradation
  - task_starvation
best_robust_severity: 6.680840007491316
occupied_cell_count: 5
standard_cell_count: 5
coverage_ratio: 0.013020833333333334
quality_diversity_score: 20.203880883807685
insertion_count: 14
replacement_count: 9
```

The five retained MAP-Elites cells covered three failure mechanisms. This satisfies
the Phase 3 exit criterion that the synthetic quality-diversity archive covers
multiple behavioral niches and resumes deterministically.

## Implemented surface

- Canonical four-objective vector:
  - maximize median robust severity;
  - maximize behavioral novelty;
  - maximize reproducibility;
  - minimize scenario complexity.
- Feasibility-first dominance that prevents infrastructure, cleanup, and invalid
  evaluations from dominating valid scenarios.
- Deterministic non-dominated sorting.
- Normalized objective-space crowding with explicit Pareto rank and boundary state.
- NSGA-II tournament selection and partial-front survivor selection.
- MAP-Elites niches over:
  - failure mechanism;
  - affected robot count: `0`, `1`, or `2+`;
  - failure onset: `none`, `early`, `middle`, or `late`;
  - incomplete tasks: `0`, `low`, `medium`, or `high`.
- Explicit `unknown` telemetry buckets when required descriptor data is unavailable.
- Confirmed-failure-only archive insertion.
- Per-cell replacement by robust severity, then reproducibility, then lower
  complexity.
- Duplicate phenotype rejection and deterministic tie resolution.
- Archive coverage by failure mechanism, quality-diversity score, insertion counts,
  replacement counts, and replay-reference counts.
- Complete MAP-Elites checkpoint state, including random state, elites, niches,
  decisions, seen phenotype hashes, and pending candidates.
- Elite replay verification adapter compatible with the existing live
  `ReplayVerifier`, including verified, failed, missing-reference, and error outcomes.

## Commands and outcomes

Focused Phase 3 suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_search_phase3.py -q
```

Result: `8 passed`.

Complete repository regression suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result: `33 passed`.

Phase 0 through Phase 3 search coverage:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_search_phase0.py `
  tests\unit\test_search_phase2.py `
  tests\unit\test_search_phase3.py `
  --cov=adversarial_fleet.search `
  --cov-report=term-missing -q
```

Result: `19 passed`; total search-package statement coverage: `93%`.

Static and integrity checks:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check `
  src\adversarial_fleet\search `
  tests\unit\test_search_phase0.py `
  tests\unit\test_search_phase2.py `
  tests\unit\test_search_phase3.py
.\.venv\Scripts\python.exe -m compileall -q src
git diff --check
```

Result: all checks passed.

## Validated properties

| Property | Evidence |
| --- | --- |
| Four-objective dominance | Synthetic tradeoffs remained non-dominated while strictly worse candidates moved to later fronts. |
| Validity constraint | A valid low-scoring evaluation dominated an infrastructure failure with artificial maximum objective values. |
| Crowding | Objective extrema received boundary status and interior candidates received normalized finite distances. |
| Explicit novelty | A less severe but more novel candidate survived on the first Pareto front. |
| NSGA-II determinism | Repeated 48-candidate runs produced identical summaries, populations, and random state. |
| NSGA-II resume | A serialized checkpoint produced the exact same next offspring as uninterrupted execution. |
| Niche assignment | Affected-robot, onset, and incomplete-task boundaries matched the specification. |
| Local competition | Higher severity replaced an incumbent only within the same behavioral cell. |
| Archive safeguards | Infrastructure failures and duplicate phenotype hashes were rejected. |
| MAP-Elites diversity | Five cells spanning three failure mechanisms were occupied. |
| MAP-Elites resume | Serialized elites, niches, decisions, seen hashes, and random state restored exactly. |
| Replay hooks | Available run-package references were verified through the adapter; missing references were reported without false success. |
| Regression safety | All 33 repository tests passed. |

## Boundaries and remaining integration

This is an algorithm-layer validation, not a live evolutionary RMF run. The
deterministic evaluator exercises the same genome, realization, confirmation,
descriptor, objective, and archive contracts without starting simulator processes.

The replay hook was validated using controlled package references and a deterministic
verification adapter. No live elite was replayed because fake evaluations do not
produce RMF run packages.

The remaining integration work before a live Phase 3 search is:

1. Implement the live `CandidateEvaluator` that delegates decoded scenarios to
   `ExperimentOrchestrator`.
2. Implement the environment-aware evaluation cache.
3. Add search and archive-inspection CLI/config wiring.
4. Persist the complete search-directory artifact layout from the specification.
5. Run a bounded live NSGA-II or MAP-Elites search, then replay at least one retained
   elite with rosbag and process-cleanup verification.

Phase 4 benchmarking, Phase 5 live optimization, and Phase 6 defender coevolution
remain out of scope.
