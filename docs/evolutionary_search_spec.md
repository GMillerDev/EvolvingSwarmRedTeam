# Evolutionary adversarial search and quality-diversity specification

Status: proposed implementation specification  
Version: 0.1  
Target repository version: `adversarial-fleet-testing` 0.1.0  
Primary live environment: Open-RMF Office on ROS 2 Kilted and Gazebo Ionic

Implementation status as of 2026-07-23:

- Phase 0 implemented: charger-count no-op rejection, versioned capability
  serialization/hashing, seed-free adversarial genotype, explicit realization and
  phenotype identities, and search-facing severity terminology.
- Phase 1 enabling subset implemented: typed search configuration, deterministic
  sampling and variation, ask/tell interfaces, deterministic fake evaluation, JSONL
  result storage, and atomic checkpoint/resume. The previously deferred live
  evaluator, environment-aware cache, and search CLI were completed during Phase 4.
- Phase 2 implemented: behavior descriptors and distance, population/archive novelty,
  reproducibility and robust-severity aggregation, complexity, screening/confirmation,
  severity-only GA, and behavior-space fitness-sharing GA.
- Phase 3 implemented: feasibility-constrained NSGA-II with explicit novelty and
  objective-space crowding, MAP-Elites behavioral niches, deterministic archive
  persistence/reporting, duplicate-phenotype safeguards, and elite replay
  verification hooks.
- Phase 4 implemented and live-validated: exact-budget search runner, real
  `ExperimentOrchestrator` evaluator, environment-aware evaluation cache, resumable
  batch checkpoints, search CLI, search-directory artifacts, per-generation weakness
  diagnostics, rosbag-backed replay verification, and cleanup accounting. A bounded
  one-candidate Office search and its replay completed unattended with zero orphans.
- Phases 5-6 remain pending.

## 1. Purpose

This specification defines the next implementation phase of the adversarial fleet
testing system. The system shall evolve valid Open-RMF scenarios that expose severe,
novel, and reproducible fleet-level failures. It shall also benchmark the evolutionary
method against standard search approaches under equal simulation budgets.

The first implementation shall search only variables that the live Office adapter can
actually apply. Simulator, facility, fleet, and fault genes shall remain capability-
gated until their actuators have been implemented and live-validated.

The intended long-term system is competitive coevolution:

```text
adversarial scenario population  <->  learning swarm/controller population
```

The initial milestone is adversarial scenario evolution against a fixed Open-RMF
defender. It shall not be described as full coevolution until a versioned defender
population and cross-play evaluation are implemented.

## 2. Goals

The implementation shall:

1. Evolve valid, executable scenario workloads.
2. Maximize observed fleet degradation or failure severity.
3. Preserve behaviorally distinct failures instead of converging on one category.
4. Prefer reproducible failures over one-off timing artifacts.
5. Prefer smaller explanatory counterexamples when severity is equivalent.
6. Exclude infrastructure failures from positive fitness.
7. Preserve every elite as a replayable evidence package.
8. Resume interrupted searches without changing their deterministic search sequence.
9. Benchmark algorithms using equal candidate-evaluation budgets and common seeds.
10. Leave an explicit extension boundary for future defender coevolution.

## 3. Non-goals for the first implementation

The first implementation shall not:

- Modify Open-RMF planners or controllers.
- Train a robot or fleet policy.
- Evolve robot count, speed, acceleration, charger count, lane state, doors, or faults.
- Treat ROS, Gazebo, launch, Docker, or cleanup errors as fleet failures.
- Optimize raw robot trajectories directly.
- Introduce a dashboard.
- Run multiple live Office simulations concurrently on the same ROS domain.
- Claim exact Gazebo physics determinism.

## 4. Existing architecture to preserve

The existing candidate lifecycle remains authoritative:

```text
ScenarioGenome
    -> validate
    -> generate deterministic tasks
    -> ExperimentOrchestrator
    -> RmfDemoAdapter
    -> normalized JSONL events
    -> metrics and failure report
    -> score and replay package
```

Search code shall depend on a candidate-evaluation interface and shall not import ROS
message classes. Live execution remains behind `SimulationAdapter` and
`ExperimentOrchestrator`. Metrics, descriptors, novelty, selection, archives, and
benchmark statistics shall operate on ordinary Python models and persisted artifacts.

## 5. Terminology

| Term | Definition |
| --- | --- |
| Genotype | Evolvable representation used by a search algorithm. |
| Phenotype | Fully decoded, validated scenario submitted to the orchestrator. |
| Realization seed | Seed used to deterministically realize stochastic workload choices. |
| Search seed | Seed controlling initialization, selection, mutation, and crossover. |
| Simulator seed | Gazebo physics seed; not exposed by the current Office launch. |
| Behavior descriptor | Normalized summary of observed mission/failure behavior. |
| Severity | Degree of fleet degradation or failure. Higher is worse. |
| Novelty | Distance from previously observed behaviors. Higher is less familiar. |
| Reproducibility | Frequency and consistency of an outcome across confirmation runs. |
| Complexity | Size of the adversarial scenario. Lower is more explanatory. |
| Elite | Best retained candidate in a behavioral niche. |
| Defender | Versioned fleet policy, controller configuration, or swarm checkpoint. |

## 6. Capability model

### 6.1 Capability correctness

Every evolvable gene shall have a capability declaration and a live actuator. A gene
shall be enabled only when both exist. Silent no-op genes are forbidden.

The following invariant shall hold:

```text
enabled gene -> decoded phenotype changes -> adapter applies change -> telemetry can verify change
```

If any implication is false, scenario validation shall reject the non-default value.

### 6.2 Immediate schema correction

`FacilityGenome.charger_count` is currently accepted without being applied by the
Office adapter. Before search is enabled, one of the following shall be implemented:

1. Add `supports_charger_count=False` and reject non-default charger counts; or
2. Implement, verify, and expose a charger-count actuator.

The first milestone shall use option 1.

### 6.3 Evolvable variables in milestone 1

Only these workload variables are live-validated:

| Gene | Type | Bound | Semantics |
| --- | --- | --- | --- |
| `task_count` | integer | 1-50 | Number of patrol tasks. |
| `arrival_interval_seconds` | float | 0-30 | Uniform interval between task releases. |
| `priority_skew` | float | 0-1 | Probability of elevated priority under the realization seed. |
| `patrol_routes` | variable list | 1-8 routes | Ordered route pool, used cyclically. |
| Route length | variable list | 2-8 waypoints | Ordered patrol locations in a route. |
| Route waypoint | categorical | capability allowlist | One of the verified Office waypoints. |

The initial Office waypoint alphabet is:

```text
coe
lounge
supplies
pantry
hardware_2
```

Consecutive duplicate waypoints shall be rejected or repaired. At least one route and
at least two waypoints per route are required.

### 6.4 Capability-gated future variables

The schema may represent the following genes, but they shall not be enabled until
their actuators and telemetry checks pass live validation:

- Robot count and initial robot placement
- Per-robot speed and acceleration
- Initial battery state and charger assignment
- Charger availability and charger count
- Lane closure and reopening schedules
- Door delay, stuck-open, and stuck-closed events
- Lift unavailability
- Robot dropout, degradation, and recovery time
- State-update latency, jitter, and loss
- Localization offsets and command delay
- Temporary obstacles and traffic-rule changes
- Pickup/delivery tasks, deadlines, dependencies, and cancellations

## 7. Genome design

### 7.1 Search genotype

Search shall use a model distinct from `ScenarioGenome` so capability gating and
realization seeds are explicit:

```text
AdversarialGenome
└── workload
    ├── task_count
    ├── arrival_interval_seconds
    ├── priority_skew
    └── patrol_routes[]
        └── waypoint[]
```

`AdversarialGenome` shall not contain the search seed. The realization seed shall be
provided to the decoder and written into the resulting `ScenarioGenome`.

### 7.2 Seed separation

The implementation shall distinguish:

- `search_seed`: algorithm randomness only.
- `realization_seed`: task realization and repeat comparison.
- `simulator_seed`: recorded as unavailable until Office exposes it.

The search algorithm shall not mutate `realization_seed` as an ordinary gene.
Algorithms compared in a benchmark shall receive the same ordered realization-seed
set. A candidate ID shall hash the canonical genotype without the realization seed.
A candidate realization ID shall hash the genotype plus realization seed.

### 7.3 Decoding

The decoder shall:

1. Accept an `AdversarialGenome`, capability document, and realization seed.
2. Repair bounded numeric values only for floating-point mutation drift.
3. Reject structural or capability errors rather than silently deleting genes.
4. Produce a strict `ScenarioGenome`.
5. Validate it before any simulator process starts.
6. Persist genotype, phenotype, capability version, and both hashes.

### 7.4 Variation operators

Milestone 1 shall provide deterministic operators driven by a passed `random.Random`
instance; global random state is forbidden.

Numeric operators:

- Bounded polynomial or Gaussian mutation for interval and priority skew.
- Integer step or bounded polynomial mutation for task count.
- Simulated binary crossover or uniform crossover for numeric genes.

Route operators:

- Substitute a waypoint.
- Insert or delete a waypoint within route bounds.
- Reverse a route segment.
- Add or remove a route within route-count bounds.
- Crossover complete routes between parents.
- One-point crossover within compatible routes.

Every operator shall have deterministic unit tests using fixed seeds.

## 8. Candidate evaluation contract

### 8.1 Evaluation states

A candidate realization shall have exactly one terminal evaluation state:

```text
valid_completed
valid_failure
valid_timeout
invalid_genome
infrastructure_failure
cleanup_failure
```

Only the first three states may receive severity or archive eligibility.

### 8.2 Evaluator interface

Search shall call a narrow interface equivalent to:

```python
class CandidateEvaluator(Protocol):
    def evaluate(
        self,
        genome: AdversarialGenome,
        *,
        realization_seed: int,
        candidate_id: str,
    ) -> CandidateEvaluation: ...
```

The live evaluator shall decode the genome and delegate to
`ExperimentOrchestrator`. A deterministic fake evaluator shall support unit tests and
algorithm smoke benchmarks without ROS.

### 8.3 Evaluation cache

The system shall cache terminal evaluations by:

```text
phenotype_hash
realization_seed
environment_image_digest
metric_configuration_hash
failure_detector_configuration_hash
defender_id
```

Cached infrastructure or cleanup failures shall not be reused as valid evidence.

### 8.4 Confirmation policy

Live simulation is expensive, so evaluation shall use two stages:

1. Screening: one realization run for every candidate.
2. Confirmation: additional runs before a candidate becomes a failure elite.

Default confirmation policy:

```text
screening_runs: 1
confirmation_runs: 3 total
confirmation_trigger:
  classified failure, timeout, incomplete task, or provisional archive insertion
```

The confirmation seed set shall be common across algorithms in a benchmark. All run
packages shall be retained or referenced by the aggregate evaluation.

## 9. Severity and failure qualification

### 9.1 Severity

The existing 0-10 metric score shall be renamed conceptually to `severity_score` in
search artifacts while remaining backward-compatible with `fitness.score` in run
packages.

Severity components may include:

- Incomplete-task ratio
- Latency degradation
- Deadlock duration
- Starvation count
- Negotiation failures
- Recovery loops
- Total blocked time
- Fleet fragmentation
- Collision or safety events when available

Weights and normalization shall be loaded from configuration, not duplicated in
algorithm code.

### 9.2 Failure qualification

Archive reports shall distinguish a classified failure from performance degradation.
The initial mechanism labels are:

```text
none
latency_degradation
task_timeout_or_incomplete
task_starvation
deadlock
negotiation_failure
collision
recovery_failure
unknown_fleet_failure
```

`infrastructure_failure` and `cleanup_failure` are evaluation states, not failure
mechanisms.

### 9.3 Robust severity

For confirmed candidates, selection shall use the median severity across valid runs.
Artifacts shall also report minimum, maximum, mean, standard deviation, and the
25th-percentile severity. A benchmark may select the 25th percentile as a conservative
quality objective, but it shall state that choice in its configuration.

## 10. Behavior descriptor and novelty

### 10.1 Principle

Novelty shall be computed from observed mission behavior, not genotype distance.
Genotype diversity may be reported separately but shall not substitute for behavioral
novelty.

### 10.2 Initial descriptor

The initial `BehaviorDescriptor` shall contain values derivable from the normalized
event and metric contracts:

| Field | Type | Normalization |
| --- | --- | --- |
| `failure_mechanism` | categorical | exact category |
| `mission_result` | categorical | completed/failure/timeout |
| `incomplete_task_ratio` | float | already 0-1 |
| `p95_latency_ratio` | float | clamp(p95 / configured latency scale) |
| `failure_onset_ratio` | float | onset / mission timeout; 1 when absent |
| `deadlock_duration_ratio` | float | clamp(duration / configured scale) |
| `starvation_ratio` | float | clamp(count / configured scale) |
| `blocked_time_ratio` | float | clamp(total / configured scale) |
| `affected_robot_fraction` | float | affected / configured robot count |
| `task_active_imbalance` | float | normalized imbalance of active time per robot |
| `recovery_ratio` | float | clamp(recovery events / configured scale) |
| `negotiation_failure_ratio` | float | clamp(count / configured scale) |

Missing telemetry shall be represented by an explicit availability mask. Missing data
shall not be silently interpreted as zero.

### 10.3 Descriptor extensions

After telemetry support is added, the descriptor should include:

- Spatial failure zone or normalized failure centroid
- Door, lane, or lift involvement
- Queue-depth summary
- Negotiation count and negotiation topology
- Robot motion entropy or stopped-time distribution
- Task phase at first failure
- Fault actuator involved
- Recovery sequence signature

### 10.4 Distance

Behavior distance shall combine categorical and continuous components:

```text
distance = categorical_weight * categorical_mismatch
         + continuous_weight * weighted_normalized_L1
         + mask_weight * availability_mismatch
```

All weights shall be configured and persisted. Continuous features shall be bounded
to 0-1 before distance calculation. Distance shall be symmetric, deterministic, and
unit-tested for identity and missing-data behavior.

### 10.5 Novelty score

Novelty shall be the mean distance to the `k` nearest descriptor neighbors from the
current population plus the persistent novelty archive:

```text
novelty(x) = mean(k_nearest_distances(x, population U archive))
```

Default `k` is 10 and shall be configurable. When fewer than `k` neighbors exist, all
available non-self neighbors shall be used.

Novelty shall also be reported within the same broad failure mechanism. This prevents
one categorical mismatch from making every member of a new category appear equally
novel while allowing within-category behavioral exploration.

## 11. Reproducibility

### 11.1 Outcome agreement

`reproducibility_score` shall be the fraction of confirmation runs matching the modal:

- Mission result
- Failure mechanism
- Tasks-completed bucket

Continuous metric agreement shall be reported separately using configured tolerances.

### 11.2 Archive eligibility

A failure candidate shall require, by default:

```text
valid confirmation runs >= 3
modal outcome agreement >= 2/3
no cleanup failures
at least one non-infrastructure failure or degradation criterion
```

Candidates below this threshold may remain in the novelty archive but shall be marked
`unstable` and shall not become benchmark-counted failure elites.

## 12. Scenario complexity

Complexity shall discourage trivial maximum-load scenarios and favor minimal
counterexamples. Initial normalized complexity shall be:

```text
0.50 * task_count / task_count_max
+ 0.25 * total_route_waypoints / maximum_total_route_waypoints
+ 0.25 * route_count / route_count_max
```

Future injected facility and fault events shall add event-count and event-duration
terms. Complexity shall be minimized as a separate objective, not subtracted from
severity with a hidden scalar weight.

An optional post-discovery minimizer shall attempt task and route deletion while
preserving failure qualification. Minimization is a later milestone and shall use the
same replay/confirmation requirements as discovery.

## 13. Search objectives

The canonical multi-objective evaluation is:

```text
maximize robust_severity
maximize behavioral_novelty
maximize reproducibility
minimize scenario_complexity
```

Infrastructure validity is a constraint, not an objective. Algorithm implementations
shall retain the separate objective values even if a specific baseline uses a scalar
combination.

## 14. Algorithms

All algorithms shall implement a shared ask/tell protocol so candidate evaluation,
caching, persistence, and benchmark accounting are identical.

```python
class SearchAlgorithm(Protocol):
    def ask(self, count: int) -> list[AdversarialGenome]: ...
    def tell(self, evaluations: list[CandidateEvaluation]) -> None: ...
    def state_dict(self) -> dict[str, Any]: ...
    def load_state_dict(self, state: dict[str, Any]) -> None: ...
```

### 14.1 Required algorithms

Implementation order:

1. `random_search`: uniform capability-valid sampling.
2. `severity_ga`: single-objective genetic algorithm using robust severity.
3. `nsga2`: severity, novelty, reproducibility, and complexity with crowding.
4. `fitness_sharing_ga`: severity adjusted by behavioral neighborhood density.
5. `map_elites`: explicit behavioral niche archive.

Novelty search with local competition may be added after MAP-Elites or implemented as
an emitter strategy.

### 14.2 Fitness sharing

Fitness sharing shall operate on behavior distance, not genotype distance. Sharing
radius and exponent shall be configured. The implementation shall report raw severity,
niche count, and shared severity for every candidate.

### 14.3 NSGA-II crowding

Crowding shall be calculated across the separate objective vector. Novelty must remain
an explicit objective; crowding alone is not considered behavioral diversity.

### 14.4 MAP-Elites niches

Initial archive dimensions:

```text
failure mechanism
x affected robot count bucket: 0, 1, 2+
x onset bucket: none, early, middle, late
x incomplete-task bucket: 0, low, medium, high
```

Suggested numeric buckets:

```text
early:  onset ratio < 0.33
middle: 0.33 <= onset ratio < 0.66
late:   onset ratio >= 0.66
low loss:    0 < incomplete ratio <= 0.25
medium loss: 0.25 < incomplete ratio <= 0.75
high loss:   incomplete ratio > 0.75
```

Infrastructure failures are excluded. Each cell shall retain the candidate with the
highest robust severity; ties shall prefer reproducibility and then lower complexity.
The archive may later support `k` elites per cell.

## 15. Population and archive safeguards

To prevent collapse onto one mechanism:

1. Selection shall use behavioral novelty or an explicit quality-diversity archive.
2. Archive reports shall include coverage per failure mechanism.
3. A single failure category shall not consume a global unbounded archive.
4. Duplicate phenotype hashes shall not receive additional discovery credit.
5. Near-duplicate behaviors shall compete locally.
6. Unstable failures shall be labeled and separated from confirmed elites.
7. Archive insertion shall trigger confirmation before final elite replacement.

## 16. Search persistence and artifacts

Each search shall write:

```text
results/searches/<search_id>/
├── search_config.yaml
├── environment.json
├── capabilities.json
├── manifest.json
├── candidates.jsonl
├── evaluations.jsonl
├── archive.json
├── novelty_archive.json
├── checkpoints/
├── run_references/
└── summary.json
```

Candidate evaluation records shall include:

- Candidate ID and realization ID
- Parent IDs and variation operator
- Generation or emitter iteration
- Genotype and phenotype hashes
- Search and realization seeds
- Run package paths
- Terminal evaluation state
- Raw and aggregate metrics
- Failure report
- Behavior descriptor and availability mask
- Severity, novelty, reproducibility, and complexity
- Archive niche and insertion decision
- Environment and configuration hashes

Checkpoint writes shall be atomic. Resume shall restore algorithm random state,
population, archives, evaluation counter, pending candidate IDs, and cache index.

## 17. Configuration

Search configuration shall be separate from simulator configuration. Proposed example:

```yaml
search:
  algorithm: nsga2
  search_seed: 7001
  evaluation_budget: 100
  population_size: 20
  offspring_size: 20
  checkpoint_interval: 10
  realization_seeds: [1042, 1043, 1044]

genome:
  task_count: [1, 20]
  arrival_interval_seconds: [0.0, 30.0]
  priority_skew: [0.0, 1.0]
  route_count: [1, 6]
  route_length: [2, 6]

objectives:
  severity_aggregate: median
  novelty_k: 10
  confirmation_runs: 3
  reproducibility_threshold: 0.6666667

execution:
  parallelism: 1
  reuse_cache: true
```

Configured genome bounds may be narrower than schema/capability bounds but shall not
be wider.

## 18. CLI

The CLI shall add:

```text
aft search --search-config <path> --config <sim-config>
aft search --resume <search-directory>
aft inspect-archive --search <search-directory>
aft benchmark --benchmark-config <path> --config <sim-config>
```

`aft search` shall return nonzero for configuration, infrastructure, persistence, or
cleanup failures. A valid search that finds no fleet failure shall still return zero.

`aft inspect-archive` shall be read-only and emit JSON or a Markdown summary without
launching ROS.

## 19. Proposed package structure

```text
src/adversarial_fleet/
├── search/
│   ├── models.py
│   ├── config.py
│   ├── encoding.py
│   ├── variation.py
│   ├── evaluator.py
│   ├── objectives.py
│   ├── descriptors.py
│   ├── novelty.py
│   ├── archives.py
│   ├── persistence.py
│   ├── coordinator.py
│   └── algorithms/
│       ├── base.py
│       ├── random_search.py
│       ├── severity_ga.py
│       ├── fitness_sharing.py
│       ├── nsga2.py
│       └── map_elites.py
└── benchmarks/
    ├── config.py
    ├── runner.py
    └── statistics.py
```

Algorithm modules shall contain no ROS or subprocess operations.

## 20. Benchmark specification

### 20.1 Required comparisons

The first complete benchmark shall include:

- Random search
- Severity-only genetic algorithm
- Fitness-sharing genetic algorithm
- NSGA-II with crowding
- MAP-Elites

Latin hypercube or Sobol sampling should be added as a non-evolutionary space-filling
baseline. TPE/SMAC-style optimization may be added later. CMA-ES is not a primary
baseline because the genome is mixed and variable-length; it may be used on a
continuous-only ablation.

### 20.2 Fairness

Every algorithm in a benchmark shall use:

- The same capability and genome bounds
- The same total live evaluation budget
- The same confirmation policy
- The same ordered realization seeds
- The same simulator/environment image
- The same metric and descriptor configuration
- Independent but recorded search seeds
- The same cache policy

Wall-clock time shall be reported but shall not replace evaluation budget as the
primary comparison basis.

### 20.3 Repetitions

Benchmark repetition count and evaluation budget shall be configurable. Publication
claims shall use multiple independent search seeds. Smoke acceptance may use a small
fake-evaluator budget; it shall not be reported as live algorithm performance.

### 20.4 Reported measures

Per algorithm and budget checkpoint:

- Time/evaluations to first qualified failure
- Best robust severity
- Unique confirmed failure behaviors
- Unique failure mechanisms
- MAP-Elites coverage
- Quality-diversity score: sum of elite quality over occupied cells
- Novelty archive size
- Behavioral entropy or occupancy evenness
- Reproducibility distribution
- Scenario complexity of elites
- Infrastructure and cleanup failure counts
- Total live runs and cache hits
- Wall-clock and simulation time

Across search seeds, report median, interquartile range, confidence intervals, and
paired comparisons where common seeds permit them. Do not claim superiority from a
single search run.

## 21. Competitive coevolution extension

### 21.1 Defender interface

Full coevolution requires a versioned defender artifact:

```python
class Defender(Protocol):
    @property
    def defender_id(self) -> str: ...
    def materialize(self, run_directory: Path) -> DefenderRuntime: ...
```

A defender may be a controller configuration, learned checkpoint, fleet policy, or
container digest. The fixed RMF baseline shall be defender `rmf_office_baseline`.

### 21.2 Cross-play

Scenario quality shall be evaluated against:

- A sample of the current defender population
- A hall of fame of historical defenders
- The fixed RMF baseline

Defender quality shall be evaluated against:

- Current scenario population
- Confirmed severe archive
- Confirmed novel archive
- Standard non-adversarial missions

### 21.3 Payoffs and forgetting protection

The scenario payoff is fleet severity subject to validity and reproducibility. The
defender payoff is successful mission performance plus retention on archived cases.
A hall of fame and fixed baseline are mandatory to reduce cycling and catastrophic
forgetting.

Coevolution artifacts shall persist the complete scenario-defender payoff matrix and
the exact version of every participant.

## 22. Testing requirements

### 22.1 Unit tests

Required unit coverage:

- Genome canonicalization and hashing
- Capability gating, including charger-count rejection
- Decoder and structural validation
- Every mutation and crossover operator
- Determinism under fixed search seed
- Descriptor construction and availability masks
- Distance identity, symmetry, and bounds
- k-nearest novelty calculation
- Reproducibility aggregation
- Complexity calculation
- Non-dominated sorting and crowding
- Fitness sharing
- MAP-Elites niche assignment and replacement
- Cache keys and invalidation
- Atomic checkpoints and deterministic resume

### 22.2 Algorithm property tests

For a deterministic fake evaluator:

- Same configuration and seed shall produce the same candidate sequence and archive.
- Resume at a checkpoint shall match an uninterrupted run.
- Invalid candidates shall never enter a failure archive.
- Duplicate phenotypes shall not consume additional live budget when cache reuse is on.
- All emitted genomes shall decode into capability-valid scenarios.

### 22.3 Live tests

A bounded live smoke test shall demonstrate:

- At least one search command completes without manual intervention.
- Every evaluated candidate has a replay package.
- Rosbag behavior follows the configured retention policy.
- Search shutdown leaves zero ROS/Gazebo/RMF/Python orphans.
- Archive inspection works without ROS.
- One archived candidate can be replay-verified.

The live smoke test proves integration, not algorithm superiority.

## 23. Phased implementation plan

### Phase 0: capability and terminology correctness

- Reject unsupported charger-count changes.
- Add capability serialization and hashing.
- Separate genotype, realization seed, and phenotype concepts.
- Rename search-facing fitness to severity while preserving run compatibility.

Exit criterion: no enabled gene is inert.

### Phase 1: search foundation

- Add typed search configuration and models.
- Implement encoding, decoding, sampling, mutation, and crossover.
- Add evaluator protocol, fake evaluator, caching, and persistence.
- Implement random search.

Exit criterion: deterministic search and resume pass without ROS.

### Phase 2: objectives and baseline GA

- Implement behavior descriptor, novelty, reproducibility, and complexity.
- Implement screening and confirmation aggregation.
- Implement severity-only GA and fitness-sharing GA.

Exit criterion: algorithms preserve distinct behaviors in deterministic fixtures.

### Phase 3: quality-diversity search

- Implement NSGA-II with explicit novelty objective and crowding.
- Implement MAP-Elites and archive reports.
- Add elite replay verification hooks.

Exit criterion: QD archive covers multiple synthetic behavior niches and resumes
deterministically.

### Phase 4: live workload search

- Run bounded Office searches using only workload genes.
- Verify replay packages, confirmation policy, and cleanup.
- Document discovered cases without claiming benchmark superiority.

Exit criterion: at least one full live search completes unattended with zero orphans.

### Phase 5: benchmarking

- Implement benchmark coordinator and reports.
- Run equal-budget algorithm comparisons across multiple search seeds.
- Report uncertainty, archive coverage, and failure reproducibility.

Exit criterion: benchmark report is fully reproducible from persisted configuration.

Implementation status (2026-08-06): the coordinator, fairness manifest, common-budget
checkpoint reporting, seeded bootstrap intervals, paired comparisons, and output-directory
reproduction flow are implemented. A five-algorithm, five-seed deterministic validation completed
25 searches and reproduced its design, fairness, scientific-result, and all candidate-sequence
fingerprints from the persisted configuration. This validates benchmark machinery only; see
`docs/phase5_validation_report.md`. It is not a live Open-RMF performance comparison.

### Phase 6: new actuators and defender coevolution

- Add and live-validate facility/fault genes one actuator at a time.
- Add versioned defender interface and cross-play.
- Add hall-of-fame evaluation and standard-mission retention tests.

Exit criterion: both populations adapt and all payoffs remain replayable.

Implementation status (2026-08-06): one facility mutation, directed lane closure, is capability
gated and live-validated against the pinned Kilted Office environment. The implementation includes
versioned defender artifacts, two adapting populations, complete current/archive/standard versus
current/HOF/baseline cross-play, exact participant persistence, and independent recomputation of all
924 deterministic validation payoffs. The live lane scenario and its fresh replay completed with
verified close/reopen events, non-empty command/state MCAP topics, and zero orphans. See
`docs/phase6_validation_report.md`.

This satisfies the exit criterion for the deterministic coevolution machinery, not for live
controller learning. Evolved defender genes are currently synthetic and the fixed RMF baseline is
not executed for each matrix cell. A live defender materializer and bounded live cross-play study
remain required before claiming competitive adaptation in Open-RMF.

## 24. Milestone acceptance criteria

The evolutionary-search milestone is complete when:

1. Unsupported/no-op genes are rejected.
2. Random search, severity GA, fitness sharing, NSGA-II, and MAP-Elites share one
   evaluator and accounting path.
3. Search is deterministic under fixed configuration, search seed, and fake evaluator.
4. Interrupted search resumes to the same result as uninterrupted search.
5. Novelty uses behavior descriptors rather than genome distance.
6. MAP-Elites retains distinct behavioral niches and excludes infrastructure failures.
7. Failure elites meet the configured reproducibility threshold.
8. Every live elite references complete scenario, seed, task, metrics, log, rosbag,
   and replay artifacts.
9. Benchmark comparisons use equal budgets and common realization seeds.
10. A bounded live Office search and an elite replay both finish with zero orphan
    processes.

## 25. Design decisions requiring future review

The following values are initial defaults, not scientific conclusions:

- Behavior feature weights
- Novelty `k=10`
- Confirmation count of three
- Reproducibility threshold of two-thirds
- MAP-Elites bucket boundaries
- Complexity coefficients
- Failure/degradation qualification thresholds

They shall be configuration values and shall be included in every search and benchmark
artifact. Changes to them invalidate direct comparisons unless the benchmark is rerun.

### 25.1 Deferred failure-diversity review after Phase 6

The Phase 3 deterministic evaluator and workload-only genome do not constitute
evidence that Open-RMF exposes only the failure mechanisms found in synthetic
validation. The present synthetic evaluator can emit only deadlock, task starvation,
task timeout/incompletion, and latency degradation. It assigns exactly one primary
mechanism through an ordered classifier, so co-occurring symptoms are compressed.
Negotiation, collision, recovery, communication, energy, facility, and injected robot
fault mechanisms are unreachable until their actuators and telemetry are implemented.

A 10,000-genome uniform diagnostic sweep found that latency degradation and task
timeout/incompletion each occupied less than 3% of the current synthetic search
space. A 48-candidate validation budget therefore commonly misses one of them. Across
ten search seeds, NSGA-II found all four reachable mechanisms once and MAP-Elites
found all four four times. These results indicate a combination of reachability,
class imbalance, small budget, classifier precedence, and possible selection pressure;
they do not establish premature convergence as the primary cause.

After Phase 6, review and, where supported by live evidence, implement:

1. A primary mechanism plus secondary symptom/failure signature instead of one
   exclusive failure label.
2. Capability-validated genes for facility disruptions, robot degradation, state
   latency/loss, battery and charging, localization/command delay, obstacles, and
   richer task semantics.
3. RMF negotiation, schedule-conflict, recovery, battery, and collision-adjacent
   telemetry.
4. Per-generation mechanism coverage, behavioral entropy, genotype diversity,
   genealogy, turnover, and selection-pressure diagnostics.
5. Random reachability sweeps, stratified initialization, and mechanism-conditioned
   emitters before attributing missing categories to an evolutionary algorithm.
6. Larger multi-seed budgets and power/coverage analysis for rare failure regions.

This review is intentionally deferred until Phase 6 so the implemented live,
benchmarking, and coevolution layers can provide evidence unavailable in the current
synthetic workload-only validation.

Phase 6 review outcome (2026-08-06): the new lane-closure gene proved that the capability and
actuation path can be extended without enabling a no-op mutation. Its isolated smoke mission did
not traverse the closed lane and produced no failure, while the coevolution evaluator remains
synthetic. There is therefore insufficient live evidence to add new exclusive failure labels or to
attribute missing categories to premature convergence. The primary-plus-secondary signature and
mechanism diagnostics above remain the next taxonomy work, after live tests place each new actuator
on a mission-relevant path.
