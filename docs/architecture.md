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

## Evolutionary search boundary

The search layer separates a seed-free `AdversarialGenome` from a `ScenarioRealization` and its
validated `ScenarioPhenotype`. A versioned capability document is hashed into the phenotype record,
so evaluations can prove which mutations the adapter claimed to support. Search-facing scoring uses
`severity_score`; existing replay and run artifacts retain their backward-compatible
`fitness.score` representation.

Algorithms use an ask/tell boundary around a narrow candidate evaluator. Phase 2 provides
severity-only and behavior-space fitness-sharing genetic algorithms. Phase 3 adds NSGA-II and
MAP-Elites. NSGA-II retains severity, behavioral novelty, reproducibility, and inverse complexity as
separate objectives, applies feasibility before dominance, and uses objective-space crowding only
after Pareto rank. MAP-Elites indexes confirmed failures by mechanism, affected-robot count, onset,
and incomplete-task buckets; each niche retains the most severe, then most reproducible, then least
complex candidate.

Evaluations retain raw objectives, Pareto annotations, archive decisions, and replay references.
The coordinator screens every candidate once and confirms qualifying ones on a common seed set.
Archives reject infrastructure failures and duplicate phenotypes, persist their complete state, and
produce mechanism coverage and quality-diversity reports. Replay verification is exposed through an
adapter hook so live elite packages can use the existing `ReplayVerifier`. A deterministic evaluator
exercises this path without ROS; the live evaluator that delegates to `ExperimentOrchestrator`
is implemented in Phase 4.

`SearchRunner` owns the live search lifecycle above the ask/tell interface. It enforces an exact
candidate budget, common ordered realization seeds, sequential ROS execution, screening and
confirmation, behavioral novelty assignment, batch-boundary checkpoints, and terminal cleanup
accounting. It writes the specification's search-directory layout and produces per-generation
mechanism, novelty, complexity, entropy, and post-hoc MAP-Elites diagnostics. Every algorithm is
measured through the same post-hoc archive, so later comparisons do not give MAP-Elites exclusive
access to coverage or quality-diversity measures.

`LiveCandidateEvaluator` decodes and validates a phenotype before delegating to
`ExperimentOrchestrator`, then translates the run package back into the search evaluation contract.
Valid terminal evaluations may be reused only when phenotype, realization seed, simulator/source
environment fingerprint, metric configuration, failure-detector configuration, and defender ID
match. Infrastructure and cleanup failures are never cached as successful evidence.

## Benchmark boundary

`BenchmarkRunner` expands a persisted algorithm-by-search-seed design into isolated sequential
`SearchRunner` instances. It overrides only algorithm, search seed, candidate budget, and the
per-run empty cache directory; capability bounds, confirmation seeds, descriptors, MAP bins,
simulator settings, and evaluation policy remain common. A fairness fingerprint covers this common
envelope. Each algorithm is evaluated with the same post-hoc archive metrics at the same candidate
checkpoints.

The statistics layer operates only on ordinary persisted models. It reports median, interquartile
range, a seeded percentile-bootstrap interval for the median, and paired common-seed differences.
Failure-discovery observations retain a censor count. The generated report is descriptive and does
not infer superiority. Wall-clock accounting is written to a sidecar rather than the scientific
evaluation stream, preserving Phase 4's byte-identical interrupted/resumed results. The benchmark
CLI accepts a destination override so persisted configurations can be rerun without mutation.

## Phase 6 actuator and coevolution boundaries

Facility genes are optional search-genome components and remain absent unless a versioned
capability document both enables the actuator and allowlists its target. The first live actuator
publishes a fleet-specific `LaneRequest`, observes the corresponding transient-local
`ClosedLanes` state, records both topics, and reopens the lane during shutdown. Publication waits
for the fleet and recorder subscriptions, and bounded retries handle DDS discovery without accepting
an unverified mutation.

The replay boundary now includes the capability document and digest. It also compares the logical
facility actuator sequence without comparing its nondeterministic timestamps.

`CoevolutionRunner` owns a deterministic scenario-versus-defender matrix. Its scenario panel joins
the current population, severe archive, novel archive, and standard missions. Its defender panel
joins the current population, defender hall of fame, and fixed RMF baseline artifact. Every matrix
cell records exact versions, ordered realization seeds, individual results, aggregate payoffs, and a
replay digest. `CrossplayVerifier` reconstructs all cells from persisted participants.

The current evolved defender implementation is a synthetic four-gene policy used to validate
selection, retention, persistence, and replay. The `Defender` materialization protocol is the seam
for a future live controller configuration or checkpoint. The present baseline artifact does not
turn the deterministic matrix into live RMF cross-play.

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
