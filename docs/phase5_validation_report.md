# Phase 5 benchmark implementation and validation

Date: 2026-08-06  
Result: **PASS for the Phase 5 reproducible fake-benchmark exit criterion**

This report is intentionally a validation of benchmark machinery, fairness controls,
accounting, statistics, and reproducibility. The evaluator is synthetic. None of the
numbers below are evidence that one algorithm performs better against live Open-RMF.

## Outcome

Phase 5 now provides the specified benchmark coordinator and CLI:

```powershell
aft benchmark `
  --benchmark-config configs/benchmarks/phase5_fake_validation.yaml `
  --config configs/default.yaml `
  --output results/benchmarks/phase5_fake_validation_final_primary
```

Result:

```text
exit code: 0
status: completed
algorithms: 5
independent search seeds per algorithm: 5
completed searches: 25 / 25
candidate budget per search: 64
total candidate budget: 1,600
total candidates evaluated: 1,600
realizations per candidate: 3
total realization evaluations: 4,800
infrastructure failures: 0
cleanup failures: 0
orphan processes: 0
coordinator wall time: 25.516 seconds
```

All searches used the same ordered realization seeds `[1042, 1043, 1044]` and
reported checkpoints at 16, 32, and 64 candidate evaluations.

## Implemented architecture

The Phase 5 package contains three public layers:

```text
BenchmarkFileConfig
    -> validates complete algorithm/seed/checkpoint design
BenchmarkRunner
    -> expands algorithm x search-seed grid
    -> builds one immutable SearchFileConfig per cell
    -> delegates every candidate to SearchRunner
    -> reconstructs common budget checkpoints
statistics
    -> median and IQR
    -> deterministic percentile-bootstrap interval for the median
    -> paired common-seed differences and win/tie/loss counts
```

The required algorithms all use the existing common ask/tell and evaluation path:

- random search;
- severity-only GA;
- behavior-space fitness-sharing GA;
- NSGA-II with crowding;
- MAP-Elites.

Every algorithm is scored with the same post-hoc MAP-Elites archive. MAP-Elites does
not receive exclusive access to coverage or quality-diversity measures.

The CLI supports an optional `--output` override. This changes only the destination
directory, allowing an immutable persisted benchmark configuration to be reproduced
without colliding with its original artifact directory.

## Fairness controls

The coordinator hashes and persists the following common envelope:

| Control | Validation setting |
| --- | --- |
| Capability document | Same version and SHA-256 for all searches |
| Genome bounds | Same typed `GenomeBounds` |
| Candidate budget | 64 per algorithm/seed |
| Confirmation policy | Three valid runs; confirm every candidate |
| Realization seeds | Ordered `[1042, 1043, 1044]` |
| Search seeds | Paired labels `9101` through `9105`; recorded independently per search |
| Descriptor and MAP bins | Identical serialized configuration |
| Metric/failure configuration | Identical simulator configuration |
| Evaluator/defender | `fake` / `deterministic_fake_v1` |
| Cache policy | Disabled; isolated empty cache directory still assigned per search |
| Parallelism | One; no shared ROS-domain concurrency |
| Checkpoints | 16, 32, and 64 candidates |

Fingerprints from the primary run:

```text
design:
d56bfeaa1c85efc40fb63b4276a9d7d3dcc190837ff4662a3801fa3b9bc8cdd3

fairness:
c4562a52a33b100d58673d5b02f14954bcedf4434f20aafd956f61023cee4b22

scientific result:
acc523ce2b6fc78cadc9dd3a8583ecb5ec2412bd16135d6581c4920bbb5ce44c
```

Cache directories are isolated by algorithm and search seed even when reuse is
enabled in a future benchmark. That prevents an algorithm executed later in the grid
from receiving an order-dependent warm cache. The validation disables reuse so all
4,800 realization evaluations are actual fake-evaluator calls.

## Persisted artifacts

Primary directory:

```text
results/benchmarks/phase5_fake_validation_final_primary/
```

Top-level artifacts:

```text
benchmark_config.yaml
simulator_config.yaml
capabilities.json
environment.json
fairness_manifest.json
observations.json
aggregates.json
paired_comparisons.json
summary.json
manifest.json
report.md
searches/<algorithm>_seed_<seed>/...
cache_state/<algorithm>/seed_<seed>/
```

Each child search preserves its complete Phase 4 evidence layout, including candidate
and evaluation streams, run references, algorithm checkpoint, archives, and summary.
Nondeterministic wall-clock/cache accounting is stored in
`evaluation_accounting.jsonl`; it is deliberately separated from
`evaluations.jsonl`, preserving byte-identical scientific evaluation streams across
interrupted and uninterrupted execution.

## Search completion and candidate identity

| Algorithm | Seed | Status | Candidate sequence SHA-256 |
| --- | ---: | --- | --- |
| random_search | 9101 | completed | `0993d26a9711016a68f68313c39a016bbaf9f0e6ccd85e449a1444a8dfc64bb2` |
| random_search | 9102 | completed | `d4843582235679e21567114860ed497888b301acd6f7d294596dd9d8be66f9a0` |
| random_search | 9103 | completed | `31164283442b4faa7da7a8b8a86b8c7be8cfd689ad56b123f69c22ec0a7ec67c` |
| random_search | 9104 | completed | `b9c95d5c35279f779c2906e34a48e2024830d0df1443ee32c21f2e1f03f0b66a` |
| random_search | 9105 | completed | `e08db58fd1403c2a4119e50c700d2bbf800aa7a69984d42d49f7b585142a052f` |
| severity_ga | 9101 | completed | `5ab54f4efd5715440d7f9b3520d8a5a4c9864e5ed40cb3b295116d7584d0bcba` |
| severity_ga | 9102 | completed | `efc425f8df0b9d9699a696d479254d0b7e5c72cca21ec661c9d02d8b573107aa` |
| severity_ga | 9103 | completed | `7a34ac0856b9e0fbd4a9ebebc14d747ff05d0d0ee1f3f34fb7aa658088b85072` |
| severity_ga | 9104 | completed | `7b65b3a99ae6b2f888820e72946784049a937b2870f58ba980e7f3de62d9bb27` |
| severity_ga | 9105 | completed | `22263775d49b9dc0fb83d3bc53cce4d8593a564125a3c4327de5cf7a159006a9` |
| fitness_sharing_ga | 9101 | completed | `67d8828f48cb874077459532e9526a3167eee144f2a4adb174efb3b89ea98484` |
| fitness_sharing_ga | 9102 | completed | `a5969060ee3961953807cbaa845384d66caf97d20a38cf52c2b609ed490a2ee1` |
| fitness_sharing_ga | 9103 | completed | `d0c66c4d51155145fdfbd3079f9460e7bae9a3f64c72fd8b882023bb949a2877` |
| fitness_sharing_ga | 9104 | completed | `90ae7db0ce58ea696ab3199de7b11585af8fdc2cefdb748b2bb2b0a4419f1175` |
| fitness_sharing_ga | 9105 | completed | `9edb2e074365eb96c0737fda944283aed5c0081e26601dafda704993771c72f7` |
| nsga2 | 9101 | completed | `39ee5037232f112c2f0073062d579b59c49bf7be347510560f8f8145bc212e6e` |
| nsga2 | 9102 | completed | `c973385565e339cf5c49a5994293ec8444d1aa5f0cbd2098f5369732fe9b3053` |
| nsga2 | 9103 | completed | `b1288a1820ede1837000b8f3be511e9825a3d8d326c5b63b82880b6d23074e16` |
| nsga2 | 9104 | completed | `2bb05e88528700712c33e45b958605ddeca74fa6d4e4361c9d22f8526c33f206` |
| nsga2 | 9105 | completed | `eb986dccb9dfcb12e33b6a6f7c3b1fd9b0a9342e915141ee72b938ea3ec4cce3` |
| map_elites | 9101 | completed | `08334c1aca23a211175597cc219bdd398851e9f88278557583f759e3fc505c65` |
| map_elites | 9102 | completed | `a5743c825e6ed63f2c93282cd705fedf8a4ccbfc31b98bb6e377c273570862fd` |
| map_elites | 9103 | completed | `c640f3ffca99d6f143c461384137b8d534480c9ed8f6555947b1d7f59e4ac04c` |
| map_elites | 9104 | completed | `f478c059a7b7a716241355ff71c1c93d13b3f72b3c36a4a74a17be807638eca9` |
| map_elites | 9105 | completed | `4ea308a33ba7aca87a2371258758e8d7ff14d129afde2c1c696978114fe24a8f` |

## Final-checkpoint descriptive results

Values are medians across five search seeds. Brackets contain the interquartile
range. These are synthetic diagnostics, not rankings.

| Algorithm | Best severity | Unique behaviors | Mechanisms | Coverage | QD score | Evenness | Elite complexity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| random_search | 6.7023 [6.6670, 6.8966] | 24 [21, 25] | 4 [3, 4] | 0.01823 [0.01823, 0.02083] | 27.433 [26.892, 30.745] | 0.8460 [0.7952, 0.8471] | 0.5639 [0.5243, 0.5806] |
| severity_ga | 7.0281 [7.0192, 7.0324] | 53 [44, 53] | 3 [3, 4] | 0.02604 [0.02083, 0.02865] | 41.297 [37.014, 47.253] | 0.8427 [0.8416, 0.8619] | 0.5229 [0.4160, 0.6375] |
| fitness_sharing_ga | 7.0050 [6.9855, 7.0386] | 51 [43, 53] | 3 [3, 4] | 0.02083 [0.02083, 0.02865] | 38.391 [38.253, 47.069] | 0.9046 [0.8820, 0.9120] | 0.6556 [0.5306, 0.7486] |
| nsga2 | 6.8817 [6.8200, 6.8817] | 34 [30, 39] | 4 [3, 4] | 0.02344 [0.02083, 0.02344] | 34.950 [34.698, 35.960] | 0.8182 [0.7999, 0.8673] | 0.4597 [0.4229, 0.4889] |
| map_elites | 7.0859 [7.0324, 7.0904] | 52 [48, 54] | 4 [2, 4] | 0.02344 [0.02083, 0.02604] | 40.064 [37.195, 40.189] | 0.8716 [0.8257, 0.8777] | 0.6507 [0.6097, 0.7285] |

All algorithms found a qualified synthetic failure on candidate 1 for all five
seeds. Median reproducibility was `1.0` for every algorithm. Those two measures are
saturated by this fake evaluator and provide no useful algorithm discrimination.

## Paired comparisons against random search

The table shows algorithm-minus-random median paired differences at budget 64 and
95% percentile-bootstrap intervals. A positive value favors the algorithm only for
higher-is-better measures. These are descriptive comparisons over five pairs; no
hypothesis test, multiplicity correction, or superiority decision is applied.

| Algorithm | Severity difference | Unique-behavior difference | Coverage difference | QD-score difference |
| --- | ---: | ---: | ---: | ---: |
| severity_ga | +0.3170 [0.0132, 0.3611] | +26 [16, 29] | +0.00521 [-0.00260, 0.01042] | +14.202 [0.843, 22.412] |
| fitness_sharing_ga | +0.2833 [-0.0142, 0.3716] | +24 [18, 29] | +0.00260 [0, 0.01042] | +10.819 [2.569, 22.229] |
| nsga2 | +0.1755 [-0.1376, 0.2146] | +9 [8, 15] | +0.00260 [-0.00521, 0.01302] | +4.205 [-0.137, 21.468] |
| map_elites | +0.3654 [-0.0337, 0.4690] | +27 [24, 31] | +0.00260 [0, 0.00781] | +9.444 [3.589, 15.224] |

The machine-readable file contains all measures, checkpoints, paired differences,
confidence intervals, and win/tie/loss counts.

## Reproduction verification

The exact persisted configuration was rerun with:

```powershell
aft benchmark `
  --benchmark-config results/benchmarks/phase5_fake_validation_final_primary/benchmark_config.yaml `
  --config results/benchmarks/phase5_fake_validation_final_primary/simulator_config.yaml `
  --output results/benchmarks/phase5_fake_validation_final_reproduction
```

Result:

```text
exit code: 0
status: completed
completed searches: 25 / 25
candidates: 1,600 / 1,600
realizations: 4,800
design fingerprint match: true
fairness fingerprint match: true
scientific result fingerprint match: true
candidate sequence hashes: 25 / 25 exact
primary wall time: 25.516 seconds
reproduction wall time: 26.578 seconds
```

Wall time and timestamps are deliberately excluded from the scientific fingerprint.
Simulation-runtime metrics remain included; the deterministic fake evaluator
reproduced those exactly.

## Statistical implementation

For every algorithm and checkpoint, the coordinator reports:

- evaluations and wall time to first qualified failure, with right-censor count;
- best robust severity;
- confirmed failures and exact descriptor hashes;
- failure-mechanism count;
- post-hoc archive coverage and QD score;
- novelty archive size and niche-occupancy evenness;
- mean reproducibility and median elite complexity;
- infrastructure, cleanup, orphan, execution, and cache counts;
- simulation and wall-clock time.

Across seeds it calculates minimum, maximum, mean, median, 25th/75th percentiles,
and a seeded percentile-bootstrap confidence interval for the median. Paired
comparisons use only common search-seed labels. Their raw difference is always
algorithm minus baseline; configured direction is used only to derive win/tie/loss
counts.

When a checkpoint contains no failure, evaluations-to-failure is represented as
`checkpoint + 1`, time-to-failure is represented by checkpoint elapsed time, and the
observation is explicitly counted as right-censored. This is auditable but is not a
replacement for Kaplan-Meier or another survival-analysis method.

## Test results

Focused benchmark and Phase 4 compatibility tests:

```powershell
.\.venv\Scripts\pytest.exe `
  tests/unit/test_benchmarks_phase5.py `
  tests/unit/test_search_phase4.py::test_interrupted_resume_matches_uninterrupted_candidate_and_archive_state `
  -q
```

Result: `6 passed`.

The focused tests cover:

- rejection of incomplete, duplicate-seed, or invalid-checkpoint designs;
- deterministic bootstrap intervals;
- paired common-seed direction and win/tie/loss accounting;
- CLI reproduction-output parsing;
- exact budgets across all five algorithms;
- complete benchmark/search artifact creation;
- common realization seeds and isolated cache state;
- deterministic scientific and candidate-sequence fingerprints;
- compatibility with Phase 4 byte-identical resume behavior.

Complete repository suite after the accounting-sidecar correction:

```powershell
.\.venv\Scripts\pytest.exe
```

Result: `44 passed`.

Benchmark-package coverage:

```powershell
.\.venv\Scripts\pytest.exe tests/unit/test_benchmarks_phase5.py `
  --cov=adversarial_fleet.benchmarks --cov-report=term-missing -q
```

Result: `5 passed`; benchmark-package statement coverage: `94%`.

Static validation:

```powershell
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\python.exe -m compileall -q src
git diff --check
```

All three commands passed.

## Weakness analysis

### 1. This is not a live Open-RMF performance benchmark

The Phase 5 specification permits fake-evaluator smoke acceptance, and the live
vertical slice was proved in Phase 4. The current 25-search result validates the
coordinator, not ROS timing, Gazebo physics, controller behavior, process cleanup, or
real failure discovery. A live multi-seed benchmark remains required before any
algorithm-performance claim.

### 2. Five seeds are adequate for plumbing, not publication

With five paired observations, bootstrap distributions are discrete and intervals
are unstable. The report deliberately exposes intervals without treating them as
inferential proof. Power analysis and substantially more independent seeds are
needed for publication.

### 3. First-failure and reproducibility measures are saturated

Every search found a synthetic failure on its first candidate, and median
reproducibility was 1.0. The synthetic landscape therefore cannot test early
discovery or robustness. Live stochastic repetitions and a harder synthetic
acceptance threshold are needed.

### 4. Only four synthetic mechanisms are reachable

The evaluator can emit deadlock, task starvation, task timeout/incompletion, and
latency degradation. Negotiation, collision, recovery, communication, energy,
facility, and injected-fault behavior remains unreachable. The deferred Phase 6
review in the specification remains controlling.

### 5. The coverage denominator includes currently unreachable mechanisms

Coverage uses 384 standard cells: eight non-`none` mechanism categories times three
robot-impact, four onset, and four incomplete-task buckets. Because the fake
evaluator can reach only four mechanisms, absolute coverage is structurally capped
below the nominal denominator. Comparisons are fair within this configuration, but
the numerical percentage should not be interpreted as reachable-space coverage.

### 6. Exact descriptor hashes can overcount behavioral uniqueness

`unique_confirmed_behavior_count` hashes all floating descriptor fields exactly.
Small continuous changes can make two operationally equivalent failures unique. The
very high counts for the genetic algorithms should be reviewed using tolerance bins,
clustering, or niche identity before being presented as distinct mechanisms.

### 7. Archive-cell count and mechanism count answer different questions

MAP-Elites occupied multiple onset/impact/loss cells inside the same primary
mechanism. This is useful behavioral diversity, but it cannot compensate for missing
mechanisms. Both measures must remain visible; neither should be used alone.

### 8. Single-label classification still compresses co-occurring symptoms

The benchmark consumes one primary failure mechanism. Descriptor variation can
preserve some symptom differences, but mechanism counts cannot reveal multiple
simultaneous causes. Phase 6's primary-plus-secondary failure signature remains
necessary.

### 9. Candidate and realization budgets diverge under conditional confirmation

This validation confirms every candidate, so each algorithm receives exactly 192
realizations per seed. With the normal screening policy, algorithms that trigger more
confirmations consume more simulator runs under the same candidate budget. Future
live comparisons must either fix both budgets or report and analyze the difference.

### 10. Cache efficiency is not validated

Cache reuse was disabled to make execution accounting unambiguous. Isolation logic
is tested, but hit rates, cache-related runtime effects, and persisted live-run reuse
are not benchmarked.

### 11. Runtime comparisons are descriptive only

Algorithms ran serially in a fixed order on one Windows host. File-system caching,
background load, and order effects remain. Candidate budget is the primary basis;
wall time is recorded but excluded from the scientific fingerprint.

### 12. The bootstrap interval is basic

The implementation uses a deterministic percentile bootstrap for the median. It is
transparent and dependency-free, but it is not bias-corrected/accelerated and does
not account for multiple measures or repeated checkpoint looks.

### 13. Censored failure timing uses an auditable sentinel

`checkpoint + 1` is suitable for machine-readable smoke comparisons but not formal
time-to-event inference. A publication benchmark should add survival curves and a
paired censored-data method.

### 14. Search-seed pairing is a common-random-number design, not identical search

The same seed labels are used across algorithms to enable paired comparisons, but
algorithms consume random draws differently after initialization. Candidate streams
are expected to differ across algorithms and should not be described as matched
scenarios.

### 15. Optional space-filling baseline remains open

The five required algorithms are implemented. Latin hypercube or Sobol sampling is
recommended, but not required by the Phase 5 exit criterion, and has not been added.
It remains useful for separating evolutionary effects from improved mixed-space
coverage.

### 16. Crash recovery remains batch-boundary based

The Phase 5 coordinator persists completed child searches and analyses only terminal
artifacts, but it has no benchmark-level resume protocol. A host failure mid-grid
requires a new destination and rerun. Search-level batch resume remains available.

## Exit-criterion decision

The Phase 5 exit criterion is satisfied for benchmark infrastructure:

- the required five algorithms share one coordinator and accounting path;
- budgets, confirmation, realization seeds, environment, metrics, descriptors, and
  cache policy are checked and fingerprinted;
- five search seeds complete for every algorithm;
- uncertainty, coverage, QD, diversity, reproducibility, failure, cache, runtime, and
  cleanup measures are persisted;
- a second run from the exact persisted configurations reproduces all design,
  fairness, scientific, and candidate-sequence fingerprints.

No live performance or algorithm-superiority claim is made. Before such a claim,
run the same benchmark with `execution.evaluator: live`, a scientifically justified
seed count and budget, a fixed realization-run budget policy, and the Phase 6
actuators/telemetry needed to expand the reachable failure space.
