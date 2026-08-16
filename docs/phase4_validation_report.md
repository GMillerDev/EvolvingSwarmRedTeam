# Phase 4 live workload-search validation

Date: 2026-07-23/24  
Result: **PASS for the bounded Phase 4 live-search exit criterion**

This report separates live evidence, deterministic algorithm diagnostics, and known
weaknesses. The one-candidate live run proves search-to-Open-RMF integration and
cleanup; it is not evidence that one search algorithm outperforms another.

## Outcome

The exact Phase 4 search command completed without manual intervention:

```powershell
docker compose -f docker/docker-compose.yml run --rm aft search `
  --search-config configs/search/phase4_live_smoke.yaml `
  --config configs/default.yaml
```

Result:

```text
search_id: search_2026-07-24T03-04-29-038496Z_random_search_seed_7401
status: completed
algorithm: random_search
evaluator: live
evaluation_budget: 1
candidate_count: 1
realization_evaluation_count: 1
executed_realization_count: 1
cache_hit_count: 0
infrastructure_failure_count: 0
cleanup_failure_count: 0
orphan_process_count: 0
simulation_runtime_seconds: 91.39
search_wall_clock_runtime_seconds: 121.2744
```

The candidate was accepted by RMF, completed its patrol, generated telemetry,
metrics, a replay package, and an MCAP rosbag, and shut down with zero orphans.

The candidate package was then replayed with:

```powershell
docker compose -f docker/docker-compose.yml run --rm aft replay `
  --package /opt/adversarial-fleet-testing/results/runs/`
run_2026-07-24T03-04-29-217752Z_seed_1042_4b094cd61359
```

Replay result: `verified: true`, `replay_status: completed`, and every prerequisite
and comparison passed, including the new original/replay cleanup checks.

## Environment

The run used the existing pinned environment:

```text
Ubuntu: 24.04
ROS: Kilted
Gazebo: Ionic 9.5.0
rmf_demos_gz: 2.9.0
rmf_fleet_adapter: 2.13.0
Python in container: 3.12.3
ROS_DOMAIN_ID: 0
```

Pinned upstream image:

```text
ghcr.io/open-rmf/rmf/rmf_demos@
sha256:a6ed4f30b6f86833b54037aa5ce3535a078ea304de776b0d6b5ddb01b1e94478
```

Derived AFT image used for the live run:

```text
adversarial-fleet-testing@
sha256:b43b219ba33404d668ad66b8c998e90327916f5a2915518584adeac02174176e
```

Preflight command:

```powershell
docker compose -f docker/docker-compose.yml run --rm aft `
  health-check --config configs/default.yaml
```

Preflight exited zero with `healthy: true`.

The image build emitted a dependency-resolver warning concerning an upstream
FastAPI/Starlette combination. Neither package is used by the Phase 4 search path,
but the system-site-package venv remains a packaging risk for later services and
should be isolated or pinned before adding an API.

## Live candidate

Search candidate:

```text
candidate_id:
  4b094cd6135990d731022f5825840406bd9c6876e9495c4635fe3e72faebd10a
realization_id:
  83347b6fd26476fbd30c99738fecb7b733e4050547ab541991c3d70f60a993ed
phenotype/scenario hash:
  4354c919420d90ffb610d24c947d29f4ed09a14fef7a7b53b6633569d2f799d0
realization seed: 1042
```

Decoded workload:

```yaml
task_count: 1
arrival_interval_seconds: 8.0
priority_skew: 0.0
patrol_routes:
  - [lounge, hardware_2]
```

Generated task:

```text
task_0000
category: patrol
places: lounge -> hardware_2
rounds: 1
priority: 0
start_offset_seconds: 0
task_sequence_hash:
  74eccf5d0d9bf95fa2cafce36ecf0a19c2094aa434c9ea6fda40a16dc4a36f15
```

The live run recorded 1,540 normalized events.

## Original and replay comparison

| Measure | Original | Replay | Difference | Result |
| --- | ---: | ---: | ---: | --- |
| Mission result | completed | completed | exact | pass |
| Failure type | none | none | exact | pass |
| Tasks completed | 1 | 1 | 0 | pass |
| Tasks incomplete | 0 | 0 | 0 | pass |
| Mean task latency | 67.53 s | 68.22 s | 0.69 s | pass |
| p95 task latency | 67.53 s | 68.22 s | 0.69 s | pass |
| Severity/legacy fitness | 0.4502 | 0.4548 | 0.0046 | pass |
| Deadlock duration | 0 s | 0 s | 0 s | pass |
| Simulation runtime | 91.39 s | 92.93 s | 1.54 s | diagnostic |
| Cleanup error | null | null | exact | pass |
| Orphan process count | 0 | 0 | exact | pass |

The scenario hash and task-sequence hash were exact. Numerical timing remained well
within the existing absolute/relative tolerances.

## Rosbag evidence

The original candidate's bag passed `ros2 bag info`:

```text
Storage: MCAP
ROS distribution: Kilted
Size: 968.1 KiB / 976,507 bytes
Duration: 72.893975177 seconds
Messages: 8,234
```

Selected topic counts:

| Topic | Messages |
| --- | ---: |
| `/clock` | 7,043 |
| `/fleet_states` | 783 |
| `/task_state_update` | 72 |
| `/dispatch_states` | 37 |
| `/door_states` | 210 |
| `/fleet_state_update` | 81 |
| bid notice/response | 1 each |
| dispatch request/ack | 1 each |

Zero negotiation proposals and conclusions are expected for this uncongested
single-task mission. The bag metadata SHA-256 was
`c29bc2546661b1f5f7eaa5ec4c05260a5fe989850de85824460a63ce95c89dc2`.

## Confirmation and replay policy

The live candidate completed normally with no classified failure, timeout, or
incomplete task. The screening policy therefore correctly stopped after one
realization. It did not count the candidate as a confirmed failure or insert it into
the failure archive.

Because there was no failure elite, the automatic elite-replay hook reported zero
eligible elites rather than claiming a vacuous verified elite. The candidate package
was replayed directly to validate package completeness and cleanup.

The three-run failure confirmation path remains covered by deterministic integration
tests, but a live failing candidate has not yet exercised all three confirmation
runs. That distinction must remain explicit.

## Search artifacts

Search directory:

```text
results/searches/
search_2026-07-24T03-04-29-038496Z_random_search_seed_7401/
```

Generated artifacts:

```text
search_config.yaml
simulator_config.yaml
environment.json
capabilities.json
manifest.json
candidates.jsonl
evaluations.jsonl
archive.json
novelty_archive.json
summary.json
checkpoints/latest.json
run_references/<candidate_id>.json
```

The manifest records the algorithm, evaluator, exact budget, search seed, ordered
realization seeds, capability version/hash, platform, and terminal status. The run
reference records candidate, realization, phenotype, terminal state, package path,
and orphan count.

The runtime cache key includes:

```text
phenotype hash
realization seed
simulator plus installed-source environment fingerprint
metric/descriptor configuration hash
failure-detector configuration hash
defender ID
```

Infrastructure and cleanup failures are not reusable cache evidence, and missing run
packages invalidate live cache entries. Cache reuse was disabled for this acceptance
run so the reported execution is unquestionably live.

## Deterministic review run

The detailed algorithm diagnostics used:

```powershell
aft search `
  --search-config configs/search/phase4_fake_review.yaml `
  --config configs/default.yaml
```

Result:

```text
algorithm: map_elites
candidate_count: 48
realization_evaluation_count: 144
confirmed_failure_count: 39
first_qualified_failure_candidate: 2
best_robust_severity: 6.680840007491316
occupied_cells: 5 / 384
coverage_ratio: 0.013020833333333334
quality_diversity_score: 20.203880883807685
behavioral_evenness: 0.8569644757744475
mechanism_dominance_ratio: 0.5128205128205128
```

Confirmed mechanism counts:

```text
deadlock: 20
latency_degradation: 6
task_starvation: 13
```

Generation diagnostics:

| Generation | Confirmed | Best severity | Mean novelty | Mean complexity | Cumulative cells | Mechanisms present |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 6 | 3.5096 | 0.07481 | 0.5049 | 2 | deadlock, starvation |
| 1 | 11 | 3.7423 | 0.03975 | 0.7194 | 3 | deadlock, latency, starvation |
| 2 | 11 | 6.5826 | 0.02269 | 0.8168 | 4 | deadlock, latency, starvation |
| 3 | 11 | 6.6808 | 0.00458 | 0.7493 | 5 | deadlock, starvation |

Observed objective correlations:

```text
severity vs novelty:          0.0019
severity vs reproducibility:  0.1326
severity vs complexity:       0.2464
novelty vs reproducibility:  -0.1466
novelty vs complexity:       -0.1728
reproducibility vs complexity: 0.1306
```

These are diagnostics from one deterministic synthetic run, not inferential
statistics or evidence of superiority.

## Algorithm weaknesses exposed

### 1. The live acceptance budget is intentionally too small for optimization

One random candidate proves the vertical slice only. It applies no evolutionary
selection and cannot evaluate discovery rate, convergence, or archive coverage.
A bounded multi-generation live run is still needed before making algorithm claims.

### 2. Synthetic novelty fell by approximately 94%

Mean novelty declined from `0.07481` to `0.00458` across four generations. Some
decline is expected as the archive fills, because novelty is relative to accumulated
neighbors, but this magnitude can also indicate local exploitation, descriptor
compression, or insufficient mutation. Absolute novelty is therefore not directly
comparable across generations without an archive-growth baseline.

### 3. Complexity pressure was weak

Mean complexity rose from `0.5049` to `0.8168` by generation 2 while severity
improved. MAP-Elites only applies complexity as a tie-breaker inside a niche, so a
slightly more severe but substantially more complex scenario replaces a simpler
elite. The implementation follows the specification, but it does not strongly favor
minimal counterexamples.

### 4. Rare behavior disappeared from the final generated batch

Latency degradation appeared in generations 1 and 2 but not generation 3. The
cumulative archive retained it, which is desirable, but the emitter population did
not continue sampling that mechanism in the last batch. Per-mechanism emitters or
archive-balanced parent sampling may be needed.

### 5. Five occupied cells are not broad behavioral coverage

Five of 384 standard cells were occupied. Three were deadlock cells, and deadlock
accounted for 51.3% of confirmed candidates. The archive prevented total collapse,
but most defined behavioral space remained unvisited.

### 6. The current descriptor can treat normal specialization as extreme imbalance

The successful one-task live mission produced `task_active_imbalance = 1.0` because
one robot executed the task while the other remained idle. This is expected behavior,
not a failure. Without conditioning on task count or opportunity to participate, the
descriptor can overstate novelty for small workloads.

### 7. Single-run reproducibility is numerically 1.0

The successful screening run received reproducibility `1.0` because the only outcome
matches its own mode. Archive eligibility still requires three valid runs, so it
cannot become a confirmed failure elite, but NSGA-II may use this optimistic value
during selection. Reproducibility should eventually include confidence or sample
count rather than reporting only modal agreement.

### 8. Complexity depends on configured maxima

The intentionally fixed minimal smoke-search genome received complexity `1.0`
because every gene equals the maximum of its narrowed search bounds. This is
mathematically consistent with the current formula but makes complexity incomparable
across configurations with different bounds. A stable capability-wide normalization
or explicit raw complexity should accompany the configured-bound score.

### 9. Failure classification is still single-label

The live adapter can observe multiple symptoms, but the aggregate evaluation stores
one primary mechanism. Co-occurring latency, starvation, negotiation, and deadlock
symptoms can therefore collapse into one category. The post-Phase-6 diversity note in
the specification records the required multi-symptom review.

### 10. Resume is deterministic only at completed batch boundaries

Controlled interruption after a checkpoint resumes to the exact same candidates and
archive as an uninterrupted run. A process crash in the middle of a live candidate or
batch is not transactionally reconciled: candidate JSONL records may exist without a
matching evaluation, and the last durable algorithm state precedes the batch.
Mid-batch journal recovery remains necessary for fault-tolerant long searches.

### 11. Variation lineage is not yet persisted

Candidate artifacts record generation, evaluation index, genotype, and candidate ID,
but the current ask/tell algorithms do not expose parent IDs and exact variation
operators. This limits post-hoc genealogy and selection-pressure analysis.

### 12. Cache identity requires operational discipline

The final implementation fingerprints the pinned RMF image and installed Python
source. The live acceptance artifact predates that hardening and used the upstream RMF
image reference alone; cache reuse was disabled, so the result is unaffected. Future
live runs should verify the composite fingerprint in `environment.json`.

### 13. Numerical threshold serialization can change eligibility

A YAML value of `0.6666667` is slightly greater than exact `2/3` and excluded one
synthetic candidate that scored exactly two agreeing runs out of three. The supplied
configs now omit that rounded override and use the typed exact default. Benchmark
config review must treat threshold serialization as scientifically material.

## Test results

Focused Phase 4 tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_search_phase4.py -q
```

Result: `6 passed`.

Complete repository suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result: `39 passed`.

Search-layer coverage:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_search_phase0.py `
  tests\unit\test_search_phase2.py `
  tests\unit\test_search_phase3.py `
  tests\unit\test_search_phase4.py `
  --cov=adversarial_fleet.search `
  --cov-report=term -q
```

Result: `25 passed`; search-package statement coverage: `92%`.

The Phase 4 tests verify:

- live run-result conversion;
- failure-mechanism mapping;
- failure onset and affected-robot extraction;
- cleanup/orphan conversion to zero-severity cleanup failure;
- cache hits and defender/config invalidation;
- exact candidate and realization accounting;
- complete artifact creation;
- controlled interruption and deterministic resume;
- common confirmation-seed validation;
- convergence and weakness diagnostics.

Static checks:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m compileall -q src
git diff --check
```

All passed.

## Remaining work

Phase 4's bounded live-search criterion is satisfied. Before Phase 5:

1. Run a small multi-generation live workload search with an evolutionary algorithm.
2. Exercise a live failure candidate through all confirmation runs and elite replay.
3. Add mid-batch transactional recovery.
4. Persist parent/operator lineage.
5. Normalize complexity against stable capability bounds.
6. Revisit single-run reproducibility treatment.
7. Add task-count-aware imbalance descriptors.
8. Resolve the container dependency warning.

No benchmark-superiority claim is made from the live smoke run or the single
synthetic diagnostic run.
