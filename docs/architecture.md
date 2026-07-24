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
remains the next integration boundary.

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
