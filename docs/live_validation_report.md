# Live Open-RMF vertical-slice validation report

Validation date: 2026-07-20/21. Result: **PASS**, with the headless-display caveat
described under remaining limitations.

The evidence below comes from the real pinned Open-RMF Office/Gazebo environment,
not unit tests or mocked ROS interfaces.

## Commands executed

Health check:

```powershell
docker compose -f docker/docker-compose.yml run --rm aft health-check --config configs/default.yaml
```

Each of the three primary runs used the identical command:

```powershell
docker compose -f docker/docker-compose.yml run --rm aft run-scenario --scenario configs/example_scenario.yaml --config configs/default.yaml
```

Replay verification used:

```powershell
docker compose -f docker/docker-compose.yml run --rm aft replay --package /opt/adversarial-fleet-testing/results/runs/run_2026-07-20T23-48-12-296237Z_seed_1042_candidate_0000
```

Rosbags were checked with:

```bash
source /opt/ros/kilted/setup.bash
ros2 bag info /opt/adversarial-fleet-testing/results/runs/<run_id>/rosbag
```

The exact environment, source commands, and manual launch command are in
[live_environment_setup.md](live_environment_setup.md). Exact live interfaces are
in [rmf_interface_inspection.md](rmf_interface_inspection.md).

## Health check

The final pre-launch health check exited 0:

```json
{
  "platform": "linux",
  "bash": true,
  "ros_setup_script": true,
  "workspace_setup_script": true,
  "output_writable": true,
  "rmf_demos_gz": true,
  "required_topics": [],
  "clock_publishing": false,
  "robots_ready": false,
  "ready": false,
  "healthy": true
}
```

`healthy: true` is the correct result when the image is installed but Office has
not yet been launched. `ready` becomes true during a run only after the required
topics, a clock sample, and non-empty fleet state have all been observed.

## End-to-end result

```text
Run 1: completed successfully
Run 2: completed successfully
Run 3: completed successfully
```

All three commands exited 0 without manual intervention. In each run, four patrol
requests were accepted, awarded, executed, and reached `completed`. The event log
contains task submission, queued/active/completed transitions and robot states;
metrics and a final fitness score were written; the run directory is the exported
replay package; and an MCAP rosbag was finalized.

Run 1 contained 4,642 typed robot-state samples. Both robots ranged from roughly
`x=5.359` to `x=20.629` and `y=-6.997` to `y=-2.115`, with thousands of samples
marked task-active. This provides direct motion evidence for the patrol execution
in the headless simulator.

## Determinism comparison

`failure_score` below is the stored final fitness score in the current artifact
schema. `failure_type=none` means no fleet failure was classified.

| run_id | seed | task_sequence_hash | scenario_hash | mission_result | failure_type | failure_score | tasks_completed | tasks_incomplete | mean_task_latency | deadlock_duration | rosbag_path | replay_path | orphan_process_count |
| --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `run_2026-07-20T23-48-12-296237Z_seed_1042_candidate_0000` | 1042 | `356f8dfd7b2aa8235e7d02272834c8a4c332daaf097be30766af7e7256bddde5` | `5dbba2fef36fb0d02bdba2281ea0e72dcdb5ec8ca241523bd7a34202fa7fd206` | completed | none | 1.469343 | 4 | 0 | 156.625 s | 0 s | `results/runs/run_2026-07-20T23-48-12-296237Z_seed_1042_candidate_0000/rosbag` | `results/runs/run_2026-07-20T23-48-12-296237Z_seed_1042_candidate_0000` | 0 |
| `run_2026-07-20T23-52-46-897764Z_seed_1042_candidate_0000` | 1042 | `356f8dfd7b2aa8235e7d02272834c8a4c332daaf097be30766af7e7256bddde5` | `5dbba2fef36fb0d02bdba2281ea0e72dcdb5ec8ca241523bd7a34202fa7fd206` | completed | none | 1.485643 | 4 | 0 | 159.380 s | 0 s | `results/runs/run_2026-07-20T23-52-46-897764Z_seed_1042_candidate_0000/rosbag` | `results/runs/run_2026-07-20T23-52-46-897764Z_seed_1042_candidate_0000` | 0 |
| `run_2026-07-20T23-57-40-536762Z_seed_1042_candidate_0000` | 1042 | `356f8dfd7b2aa8235e7d02272834c8a4c332daaf097be30766af7e7256bddde5` | `5dbba2fef36fb0d02bdba2281ea0e72dcdb5ec8ca241523bd7a34202fa7fd206` | completed | none | 1.458777 | 4 | 0 | 155.895 s | 0 s | `results/runs/run_2026-07-20T23-57-40-536762Z_seed_1042_candidate_0000/rosbag` | `results/runs/run_2026-07-20T23-57-40-536762Z_seed_1042_candidate_0000` | 0 |

The generated sequence was identical in all runs:

```text
task_0000  t=0   patrol coe -> lounge
task_0001  t=8   patrol supplies -> pantry
task_0002  t=16  patrol coe -> lounge
task_0003  t=24  patrol supplies -> pantry
```

### Equivalence tolerances

| Field | Required tolerance | Observed three-run spread | Result |
| --- | --- | --- | --- |
| Seed, task hash, scenario hash | exact | exact | pass |
| Mission result and failure type | exact | all `completed`, all `none` | pass |
| Tasks completed/incomplete | exact | 4/0 in every run | pass |
| Deadlock duration | absolute 2 s | 0 s | pass |
| Mean task latency | absolute 10 s or relative 20%, whichever is larger | 3.485 s (155.895-159.380) | pass |
| Failure/fitness score | absolute 0.5 | 0.026867 | pass |
| Orphan process count | exact zero | zero in every run | pass |

The p95 latency, an additional diagnostic, ranged from 218.8165 to 222.8465
seconds (4.03 seconds). Simulation runtime ranged from 233.97 to 251.27 seconds.

Task generation was exactly deterministic. The numerical variation is classified
primarily as **ROS timing** and **controller behavior**, with **Gazebo physics** as
a contributing source. Rosbag message counts also vary slightly because recorder
and publisher startup are asynchronous; that variation is classified as
**telemetry collection**. There was no outcome, failure-classification, or process-
lifecycle divergence in the three accepted runs.

## Rosbag verification

All bags used MCAP storage and reported ROS distribution Kilted:

| Run | Size | Duration | Messages | `/clock` | `/fleet_states` | `/task_state_update` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.5 MiB | 231.718 s | 26,960 | 23,061 | 2,363 | 459 |
| 2 | 3.6 MiB | 235.407 s | 27,393 | 23,431 | 2,396 | 465 |
| 3 | 3.6 MiB | 232.044 s | 27,072 | 23,104 | 2,420 | 462 |

Every bag also contains dispatch states, door and lane states, fleet JSON updates,
four bid responses, four dispatch commands, four dispatch acknowledgements, and
traffic negotiation messages. The exact topic set is documented in the interface
report. Zero-message `/closed_lanes` entries are expected because this scenario
does not close a lane.

## Replay verification

Run 1's replay verifier checked all of the following before launching a fresh live
Office run:

```text
seed_matches: true
scenario_hash_matches: true
saved_tasks_match_generated: true
saved_task_hash_matches: true
rosbag_valid: true
```

The successful replay package is:

```text
results/runs/run_2026-07-21T00-10-37-825665Z_seed_1042_replay
```

It completed 4/4 tasks with score 1.485510, mean latency 159.18 seconds, zero
deadlock duration, no failure classification, and zero orphan processes. The
verifier reported every comparison true and wrote
`replay_verification.json` into Run 1's package.

## Process cleanup verification

Each accepted run's `run_result.json` records:

```text
cleanup_error: null
orphan_process_count: 0
orphan_processes: []
```

The successful replay records the same values. After the final manual inspection,
both `docker ps` and a filtered `docker ps -a` showed no running or retained AFT
container. The runner disables the ROS CLI daemon, terminates managed process
groups, scans for escaped ROS/Gazebo/RMF processes, and treats any survivor as a
cleanup failure.

## Integration failures found and fixed

### ROS domain and escaped Gazebo process

The first preliminary command used the same scenario command but config domain 42.
It failed after 300 seconds with:

```text
TimeoutError: RMF did not become ready: ... 'clock_publishing': True,
'robots_ready': False, 'ready': False, 'healthy': True
```

The relevant Gazebo output was:

```text
[slotcar_tinyRobot1]: Unable to determine the current level_name for robot
[tinyRobot1]... The RobotState message for this robot will not be published.
[slotcar_tinyRobot2]: Unable to determine the current level_name for robot
[tinyRobot2]... The RobotState message for this robot will not be published.
```

The old cleanup logic then reported one escaped `gz sim` process. The failed
artifact is
`results/runs/run_2026-07-20T23-41-02-435969Z_seed_1042_candidate_0000`.
The smallest corrective actions were applied: use domain 0 for this image, require
real robot data during readiness, add descendant scanning and staged termination,
and enable a container init process.

### Transient fleet-discovery stall during first replay attempt

The first replay command validated its package and rosbag but its fresh simulation
never added robots to the fleet. It ended with the same readiness predicate and
zero cleanup orphans. That failed attempt is
`results/runs/run_2026-07-21T00-02-37-247399Z_seed_1042_replay`.

The runner was hardened to allow up to three 90-second startup attempts inside the
same command, performing full cleanup between attempts and preserving a 300-second
overall startup bound. Tests and lint passed, the image was rebuilt, and the exact
same replay command then verified successfully.

Other live fixes included the Kilted task payload path, actual task-state JSON and
fleet message conversion, simulation-clock timestamps, launch timing, terminal
task detection, rosbag finalization before export, timeout classification, and
replay hash/metric checks.

## Remaining limitations

There is no blocker for this requested patrol vertical slice. Two limitations
remain explicit:

1. The Office launch does not expose a Gazebo random-seed argument, so identical
   numerical physics timing is not guaranteed. Equivalence is assessed with the
   tolerances above.
2. The benchmark ran headless because Qt/RViz display initialization failed in
   Docker Desktop. Robot execution was verified from changing live poses, task
   states, logs, and MCAP data; a graphical screenshot was not captured.
