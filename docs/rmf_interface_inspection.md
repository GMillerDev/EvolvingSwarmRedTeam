# Live RMF Office interface inspection

This interface inventory was captured from the pinned Kilted Office demo described
in [live_environment_setup.md](live_environment_setup.md). It records the graph
actually present after launch; it is not inferred from mocks or older RMF APIs.

## Inspection commands

After launching the Office demo, the following commands were run in the live
container:

```bash
source /opt/ros/kilted/setup.bash
source /rmf_demos_ws/install/setup.bash
ros2 topic list -t
ros2 service list -t
ros2 action list -t
gz service -l
gz service -i -s /world/sim_world/control
gz service -i -s /server_control
```

`ros2 action list -t` returned no actions.

## Task submission and monitoring

The supported generic task API in this image is topic-based:

| Direction | Name | Type |
| --- | --- | --- |
| Request | `/task_api_requests` | `rmf_task_msgs/msg/ApiRequest` |
| Response | `/task_api_responses` | `rmf_task_msgs/msg/ApiResponse` |
| Dispatch lifecycle | `/dispatch_states` | `rmf_task_msgs/msg/DispatchStates` |
| JSON task lifecycle | `/task_state_update` | `std_msgs/msg/String` |
| Bid request | `/rmf_task/bid_notice` | `rmf_task_msgs/msg/BidNotice` |
| Bid response | `/rmf_task/bid_response` | `rmf_task_msgs/msg/BidResponse` |
| Dispatch command | `/rmf_task/dispatch_request` | `rmf_task_msgs/msg/DispatchCommand` |
| Dispatch acknowledgement | `/rmf_task/dispatch_ack` | `rmf_task_msgs/msg/DispatchAck` |

No `/submit_task`, `/cancel_task`, or other task-specific ROS service was present,
and there was no task action. `aft` invokes the image's supported requester:

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -p coe lounge -n 1 -st 0 -pt 0 --use_sim_time
```

That requester publishes an `ApiRequest` with `type=dispatch_task_request`. Its
JSON request contains the requester, `category: patrol`, `description.places`,
`description.rounds`, request time, and earliest start time. A successful response
contains `success: true` and `state.booking.id`, which is the canonical RMF task ID.

`/task_state_update` carries JSON in `std_msgs/msg/String`. Observed states included
`queued`, `underway`, and `completed`. The useful fields are
`data.booking.id`, `data.status`, `data.category`, `data.detail`, and, after award,
`data.assigned_to.group` and `data.assigned_to.name`.

## Robot state and simulation time

| Name | Type | Use |
| --- | --- | --- |
| `/fleet_states` | `rmf_fleet_msgs/msg/FleetState` | Primary typed fleet/robot telemetry |
| `/fleet_state_update` | `std_msgs/msg/String` | JSON fleet update emitted by the fleet manager |
| `/robot_state` | `rmf_fleet_msgs/msg/RobotState` | Per-robot slotcar state |
| `/clock` | `rosgraph_msgs/msg/Clock` | Gazebo simulation clock |
| `/robot_collisions` | `rmf_fleet_msgs/msg/RobotCollision` | Collision notifications |
| `/robot_path_requests` | `rmf_fleet_msgs/msg/PathRequest` | Slotcar path commands |
| `/robot_mode_requests` | `rmf_fleet_msgs/msg/ModeRequest` | Robot mode changes |
| `/robot_pause_requests` | `rmf_fleet_msgs/msg/PauseRequest` | Pause requests |

Readiness requires the task and fleet topics, at least one `/clock` sample, and a
non-empty `/fleet_states` sample. Merely seeing topic names is insufficient because
the graph can exist while robot discovery has failed.

The collector timestamps events with `/clock`, converts robot pose and battery
fields from `FleetState`, and correlates `assigned_to.name` from task JSON with the
robot's active RMF task.

## Traffic and schedule monitoring

The live schedule services were:

| Service | Type |
| --- | --- |
| `/rmf_traffic/register_participant` | `rmf_traffic_msgs/srv/RegisterParticipant` |
| `/rmf_traffic/unregister_participant` | `rmf_traffic_msgs/srv/UnregisterParticipant` |
| `/rmf_traffic/register_query` | `rmf_traffic_msgs/srv/RegisterQuery` |
| `/rmf_traffic/request_changes` | `rmf_traffic_msgs/srv/RequestChanges` |

The relevant observed schedule topics were:

```text
/rmf_traffic/heartbeat                         rmf_traffic_msgs/msg/Heartbeat
/rmf_traffic/participants                      rmf_traffic_msgs/msg/Participants
/rmf_traffic/registered_queries                rmf_traffic_msgs/msg/ScheduleQueries
/rmf_traffic/query_update_1                    rmf_traffic_msgs/msg/MirrorUpdate
/rmf_traffic/schedule_startup                  rmf_traffic_msgs/msg/ScheduleIdentity
/rmf_traffic/schedule_inconsistency            rmf_traffic_msgs/msg/ScheduleInconsistency
/rmf_traffic/itinerary_set                     rmf_traffic_msgs/msg/ItinerarySet
/rmf_traffic/itinerary_extend                  rmf_traffic_msgs/msg/ItineraryExtend
/rmf_traffic/itinerary_delay                   rmf_traffic_msgs/msg/ItineraryDelay
/rmf_traffic/itinerary_reached                 rmf_traffic_msgs/msg/ItineraryReached
/rmf_traffic/itinerary_clear                   rmf_traffic_msgs/msg/ItineraryClear
/rmf_traffic/negotiation_notice                rmf_traffic_msgs/msg/NegotiationNotice
/rmf_traffic/negotiation_proposal              rmf_traffic_msgs/msg/NegotiationProposal
/rmf_traffic/negotiation_conclusion            rmf_traffic_msgs/msg/NegotiationConclusion
/rmf_traffic/negotiation_statuses              rmf_traffic_msgs/msg/NegotiationStatuses
```

The graph also exposed negotiation ack, forfeit, refusal, rejection, repeat, and
state topics, plus blockade request/state topics. The first vertical slice records
the bid/dispatch topics and the four negotiation topics that produced messages in
the Office scenario.

Facility state relevant to the run includes `/door_states`
(`rmf_door_msgs/msg/DoorState`), `/lane_states`
(`rmf_fleet_msgs/msg/LaneStates`), and `/closed_lanes`
(`rmf_fleet_msgs/msg/ClosedLanes`).

## Phase 6 lane closure actuator

The live-validated mutation interface is:

| Direction | Topic | Type | Relevant fields |
| --- | --- | --- | --- |
| command | `/lane_closure_requests` | `rmf_fleet_msgs/msg/LaneRequest` | `fleet_name`, `open_lanes`, `close_lanes` |
| state | `/closed_lanes` | `rmf_fleet_msgs/msg/ClosedLanes` | `fleet_name`, `closed_lanes` |

The `/closed_lanes` publisher offers reliable, transient-local QoS with depth one. The adapter uses
the same QoS for verification. When rosbag is enabled, the one-shot request publisher waits for two
matching subscriptions—the fleet adapter and recorder—before sending. Shutdown sends the inverse
request and requires telemetry to show the lane open before RMF termination.

## Simulator reset and restart

Gazebo advertised:

| Endpoint | Request type | Response type |
| --- | --- | --- |
| `/world/sim_world/control` | `gz.msgs.WorldControl` | `gz.msgs.Boolean` |
| `/server_control` | `gz.msgs.ServerControl` | `gz.msgs.Boolean` |

It also exposed `/world/sim_world/control/state`,
`/world/sim_world/playback/control`, entity create/remove, pose, physics, and world
state services. An in-place Gazebo world reset does not reset RMF dispatcher,
schedule, reservation, or fleet-adapter state. Therefore the validated reset
boundary is a complete Office process-group shutdown followed by the same launch
command. The runner sends SIGINT, then SIGTERM and SIGKILL if needed, scans for
escaped ROS/Gazebo processes, and only then starts a fresh attempt. Docker Compose
also uses `init: true` to reap descendants.

## Rosbag capture set

The MCAP recorder includes:

```text
/clock
/task_api_requests
/task_api_responses
/task_state_update
/dispatch_states
/fleet_states
/fleet_state_update
/door_states
/lane_states
/closed_lanes
/lane_closure_requests
/rmf_task/bid_notice
/rmf_task/bid_response
/rmf_task/dispatch_request
/rmf_task/dispatch_ack
/rmf_traffic/negotiation_notice
/rmf_traffic/negotiation_proposal
/rmf_traffic/negotiation_conclusion
/rmf_traffic/negotiation_statuses
```
