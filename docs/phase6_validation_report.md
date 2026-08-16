# Phase 6 implementation and validation report

Date: 2026-08-06

## Outcome

Phase 6 now has a capability-gated facility genome, one live-validated Open-RMF actuator,
a versioned defender contract, deterministic two-population cross-play, severe and novel scenario
archives, a defender hall of fame, a fixed baseline participant, standard-mission retention tests,
complete payoff persistence, and payoff replay verification.

The bounded live result is successful: lane 20 was closed and reopened through Open-RMF, the patrol
completed, the command and state appeared in MCAP, a replay package was exported, a fresh replay
passed all comparisons, and both runs reported zero orphan processes.

The coevolution result is deliberately narrower. Both populations adapted and all 924 payoff cells
recomputed exactly, but the evolved defenders and their payoffs use the deterministic cross-play
evaluator. The fixed RMF baseline is represented and versioned in the matrix; it is not executed as
a live RMF controller in this coevolution validation. Phase 6 therefore proves the coevolution
machinery and one live scenario actuator, not live controller learning or algorithm superiority.

## Implemented architecture

```text
AdversarialGenome                           DefenderArtifact
  workload genes                             fixed RMF baseline
  optional blocked_lane_id                   or 4-gene synthetic policy
          |                                           |
          +------ capability validation --------------+
                              |
                  generation cross-play panel
             current + severe + novel + standards
                    x current + HOF + baseline
                              |
               median severity over common seeds
                scenario payoff / defender payoff
                              |
          full payoff matrix + exact participant versions
                              |
                independent payoff recomputation
```

### Capability-gated facility gene

`FacilitySearchGenome.blocked_lane_id` is optional. Sampling, mutation, crossover, decoding, and
scenario validation may use it only when the selected `ScenarioCapabilities` document declares
`supports_lane_closure: true` and allowlists the lane. Workload-only genomes continue to omit the
facility object from their canonical form, preserving their Phase 0-5 identities.

The live-validated document is
`configs/capabilities/office_kilted_lane_closure.yaml`. It binds the mutation to Office fleet
`tinyRobot`, lane `20`, capability version `office-kilted-v2-lane-closure-20`, and capability hash
`cd9110465765e1ce909b41ef187a55b47f4fcd56c647fbebf4d36f8de739fc2f`.

The installed Office graph contains 29 vertices and 60 directed lanes. Lane 20 is the directed edge
from `presupplies` to `supplies`. The smoke mission itself uses `coe -> lounge`; this isolates
actuator correctness from route-blocking severity and does not claim that this lane creates a
failure.

### Live actuator contract

The adapter publishes `rmf_fleet_msgs/msg/LaneRequest` on `/lane_closure_requests`:

```text
string fleet_name
uint64[] open_lanes
uint64[] close_lanes
```

It then reads `rmf_fleet_msgs/msg/ClosedLanes` from `/closed_lanes` and requires the exact fleet and
lane state. The state subscription uses reliable, transient-local QoS. Publication waits for both
the fleet-adapter and rosbag subscriptions when recording is enabled. A bounded three-attempt
publish/observe loop handles DDS discovery timing; exhausting it remains an infrastructure failure.
Shutdown reopens the lane before terminating RMF and records a verified `lane_reopened` event.

The replay package now includes the exact capability document and its SHA-256 digest. Replay also
compares the timestamp-independent actuator sequence `(event, fleet, lane, verified)`.

### Defender and cross-play contract

The defender boundary is:

```python
class Defender(Protocol):
    @property
    def defender_id(self) -> str: ...
    def materialize(self, run_directory: Path) -> DefenderRuntime: ...
```

Every defender has an immutable artifact version. The fixed participant is
`rmf_office_baseline` / `fixed-rmf-office-baseline-v1`. Synthetic defenders evolve four bounded
genes: congestion resilience, priority fairness, coordination horizon, and recovery aggressiveness.
Their artifact version is the SHA-256 digest of the normalized genome.

Each generation evaluates:

- current scenarios, severe archive, novel archive, and three fixed standard missions;
- current defenders, defender hall of fame, and the fixed baseline;
- three ordered common realization seeds: 1042, 1043, and 1044.

Scenario payoff is median severity divided by ten. Scenario selection adds `0.15` times novelty in
the vector of outcomes against defenders. Defender payoff is one minus scenario payoff. Defender
selection weights adversarial performance at `0.65` and standard-mission retention at `0.35`.
Elitism, crossover, mutation, bounded severe/novel archives, and a bounded defender hall of fame
operate deterministically under the coevolution seed.

`participants.json` stores every exact scenario and defender artifact.
`payoff_matrix.jsonl` stores evaluator version, generation, roles, participant IDs and versions,
ordered seeds, individual severities, robust severity, both payoffs, and a replay digest for every
cell. `CrossplayVerifier` reloads only persisted configuration and participants and recomputes every
cell.

## Commands used

```powershell
.\.venv\Scripts\python.exe -m pytest -q --cov=adversarial_fleet --cov-report=term-missing

.\.venv\Scripts\aft.exe coevolve `
  --coevolution-config configs/coevolution/phase6_fake_validation.yaml `
  --config configs/default.yaml `
  --output results/coevolution/phase6_fake_validation_primary

.\.venv\Scripts\aft.exe verify-crossplay `
  --package results/coevolution/phase6_fake_validation_primary

docker compose -f docker/docker-compose.yml build aft

docker compose -f docker/docker-compose.yml run --rm aft run-scenario `
  --scenario configs/phase6_lane_closure_smoke.yaml `
  --capabilities configs/capabilities/office_kilted_lane_closure.yaml `
  --config configs/default.yaml

docker compose -f docker/docker-compose.yml run --rm aft replay `
  --package /opt/adversarial-fleet-testing/results/runs/run_2026-08-06T23-26-07-561569Z_seed_1060_candidate_0000

docker compose -f docker/docker-compose.yml run --rm --entrypoint bash aft -lc `
  'source /opt/ros/kilted/setup.bash && ros2 bag info /opt/adversarial-fleet-testing/results/runs/run_2026-08-06T23-26-07-561569Z_seed_1060_candidate_0000/rosbag'
```

## Environment and exact versions

| Component | Validated value |
| --- | --- |
| Ubuntu | 24.04.4 LTS |
| ROS | Kilted |
| Gazebo Sim | Ionic 9.5.0 |
| `rmf_demos_gz` | 2.9.0 |
| `rmf_fleet_msgs` | 4.0.0 |
| `rmf_task_msgs` | 4.0.0 |
| `rmf_traffic_ros2` | 2.13.0 |
| Python | 3.12.3 in container; 3.12.13 in test venv |
| `adversarial-fleet-testing` | 0.1.0 |
| Pydantic | 2.13.4 in validation image |
| PyYAML | 6.0.1 in validation image |
| Upstream RMF image | `ghcr.io/open-rmf/rmf/rmf_demos@sha256:a6ed4f30b6f86833b54037aa5ce3535a078ea304de776b0d6b5ddb01b1e94478` |
| Final derived image | `adversarial-fleet-testing@sha256:aebc2800e8b6f48405ceb05bbf2f9e37e3edea49cfa357dd4b240b472979a42f` |

The image build still prints the upstream environment's FastAPI 0.101.0 / Starlette 0.31.1
dependency warning. Neither package is imported by `aft`; the warning did not affect the ROS
validation, but the base-image Python environment should eventually be isolated further.

## Automated tests

Final full-suite result:

```text
55 passed
repository-wide statement coverage: 84%
```

The Phase 6 tests cover capability rejection, stable workload-only identity, lane sampling,
mutation and crossover, state parsing, command/state rosbag inclusion, actuator publication,
transient discovery retry, defender version materialization, invalid coevolution configuration,
hall-of-fame/standard-mission cross-play, exact replay, deterministic reproduction, and payoff
tamper detection.

## Coevolution validation

Configuration: five generations, eight scenarios, eight defenders, three common realization seeds,
archives and hall of fame capped at eight.

| generation | matrix cells | best scenario | mean scenario | best defender | mean defender | best standard retention | severe / novel / HOF |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 99 | 0.143480 | 0.094862 | 0.944644 | 0.934347 | 0.974324 | 2 / 2 / 1 |
| 1 | 150 | 0.133838 | 0.114486 | 0.934644 | 0.926816 | 0.974324 | 3 / 4 / 1 |
| 2 | 180 | 0.121948 | 0.102436 | 0.941979 | 0.933833 | 0.975093 | 4 / 6 / 2 |
| 3 | 231 | 0.117860 | 0.107806 | 0.940090 | 0.934227 | 0.975827 | 5 / 8 / 2 |
| 4 | 264 | 0.115573 | 0.108390 | 0.938410 | 0.934260 | 0.976483 | 6 / 8 / 2 |

| Measure | Result |
| --- | ---: |
| Payoff cells | 924 |
| Unique scenarios | 35 |
| Unique defenders | 33 |
| Scenario population changed | yes |
| Defender population changed | yes |
| Retention threshold | 0.80 |
| Final best retention | 0.976483 |
| Recomputed payoff cells | 924 / 924 |
| Scientific fingerprint | `ce4ada206ca129ecb98add18245d31718f88ad1636960f07f81a3cedada35264` |

An independent reproduction produced the same scientific fingerprint. The primary and reproduction
`payoff_matrix.jsonl` files both hash to
`8c5a529d0806a88d006083c972efe1036066d5e698e846c2e6dcc6c58e372c29`; both participant registries
hash to `9de7000a4d8449e74aa1c6c6fc57539411fe56a3ca79fba6e8fccdf30ea67d51`.

The falling best-scenario value is not interpreted as search regression. Its opponent panel changes
as defenders and the hall of fame change, so cross-generation scalar values are not directly
stationary. A future benchmark should include a frozen external evaluation panel.

## Final live validation and replay

| Field | Original | Replay |
| --- | --- | --- |
| Run ID | `run_2026-08-06T23-26-07-561569Z_seed_1060_candidate_0000` | `run_2026-08-06T23-28-34-818521Z_seed_1060_replay` |
| Seed | 1060 | 1060 |
| Scenario SHA-256 | `97dd87af18e1620a2f5646f7429ff692cb61ac428e1eb52b6e1554319360e7ac` | identical |
| Task-sequence SHA-256 | `79105974fece4093b643590f6f2167df64e51e66dfebb435e9b619147f50af4f` | identical |
| Mission | completed, 1/1 tasks | completed, 1/1 tasks |
| Failure | none | none |
| Failure score | 0.589067 | 0.582667 |
| Mean task latency | 88.36 s | 87.40 s |
| Deadlock duration | 0 s | 0 s |
| Lane closed event | lane 20 at 12.34 s, verified | lane 20 at 13.92 s, verified |
| Lane reopened event | lane 20 at 108.53 s, verified | lane 20 at 109.33 s, verified |
| MCAP size | 1,373,262 bytes | 1,371,386 bytes |
| Cleanup error | null | null |
| Orphan process count | 0 | 0 |

The original MCAP contains 11,738 messages over 101.70 seconds. Relevant non-zero counts include:

| Topic | Type | Count |
| --- | --- | ---: |
| `/lane_closure_requests` | `rmf_fleet_msgs/msg/LaneRequest` | 2 |
| `/closed_lanes` | `rmf_fleet_msgs/msg/ClosedLanes` | 2 |
| `/task_api_requests` | `rmf_task_msgs/msg/ApiRequest` | 1 |
| `/task_api_responses` | `rmf_task_msgs/msg/ApiResponse` | 1 |
| `/task_state_update` | `std_msgs/msg/String` | 94 |
| `/dispatch_states` | `rmf_task_msgs/msg/DispatchStates` | 51 |
| `/fleet_states` | `rmf_fleet_msgs/msg/FleetState` | 1,108 |
| `/clock` | `rosgraph_msgs/msg/Clock` | 10,057 |

`replay_verification.json` reports every prerequisite and comparison true, including capability
hash, generated tasks, task hash, rosbag validity, original cleanup, scenario hash, mission result,
failure type, score tolerance, actuator sequence, task counts, latency, deadlock duration, and replay
cleanup.

Observed numerical differences are within the predeclared tolerances: failure score absolute
difference 0.0064 (limit 0.5) and task latency absolute difference 0.96 seconds (limit is the larger
of 10 seconds or 20%). The source is classified as ROS timing/controller scheduling; task generation,
scenario parameters, mission outcome, failure classification, and process lifecycle were identical.

Final `docker compose ps -a` and the image-filtered `docker ps` returned no containers. Both run
packages independently report zero ROS, Gazebo, RMF, recorder, collector, or Python orphans.

## Integration defects found and fixed

1. Replay initially omitted the capability document. The exporter now writes `capabilities.json`
   and its hash; replay loads and validates it before starting RMF.
2. Replay compared mission metrics but not facility actions. It now compares the verified close/open
   event sequence independent of nondeterministic timestamps.
3. A live run intermittently timed out reading `/closed_lanes`. Explicit transient-local QoS plus
   bounded republish/observe attempts now tolerate DDS discovery delay without inferring success.
4. MCAP initially omitted `/lane_closure_requests`, and adding the name alone yielded zero messages
   because the publisher was ephemeral. It now waits for the fleet and recorder subscribers. The
   final bag contains both close and reopen commands.
5. One separate run failed Office readiness because `/fleet_states` existed but contained no ready
   robots after all three launch attempts. It was correctly classified as `startup_failure`, cleaned
   up with zero orphans, and was not scored as an adversarial failure.

## Failure-diversity review

The Phase 6 evidence does not support expanding the failure taxonomy yet. The new lane gene is real,
but the controlled smoke route did not traverse lane 20 and produced no failure. The deterministic
cross-play evaluator still maps facility pressure into its pre-existing synthetic behavior and
failure space. Consequently, Phase 6 does not show that the earlier observed mechanisms are
exhaustive, nor does it distinguish genome reachability from selection convergence.

The deferred review in the specification remains actionable: add one live actuator at a time,
exercise it on routes where it can affect missions, capture negotiation/recovery/facility symptoms,
then introduce primary-plus-secondary failure signatures and mechanism-conditioned coverage
diagnostics. Doing the taxonomy change before those live labels exist would create categories that
the current telemetry cannot validate.

## Remaining blockers and weaknesses

- Evolved defender genomes are synthetic and cannot yet materialize into a live Open-RMF controller
  configuration. A concrete controller/checkpoint adapter is the smallest next step for live
  competitive coevolution.
- The fixed RMF baseline participates in deterministic payoff calculations but is not run live for
  each matrix cell. Full live cross-play needs a sequential budget, caching, and likely a frozen
  evaluation panel because 924 Office runs would be expensive.
- Only directed lane closure has been live-validated. Door delay, robot failure, state latency,
  battery/charging, obstacles, and speed/acceleration remain disabled by capabilities.
- Scenario novelty is opponent-response novelty, not a multi-symptom failure signature. It protects
  some strategic diversity but does not ensure mechanism coverage.
- The current coevolution checkpoint is a terminal audit artifact, not interrupted-run resume.
- The one live lane smoke test proves actuation and replay, not that the gene finds a severe or novel
  failure.

These limits are explicit so the next review can distinguish implemented infrastructure from live
scientific evidence.
