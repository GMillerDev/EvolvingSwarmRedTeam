from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def _task_event(payload: dict[str, Any], timestamp: float) -> dict[str, Any] | None:
    data = payload.get("data", payload)
    booking = data.get("booking", {}) if isinstance(data, dict) else {}
    task_id = booking.get("id") or data.get("task_id") or data.get("id")
    status = str(data.get("status", "")).lower()
    assigned = data.get("assigned_to", {}) if isinstance(data, dict) else {}
    if not task_id:
        return None
    if status in {"completed", "success", "succeeded"}:
        kind = "task_completed"
    elif status in {"failed", "error", "killed"}:
        kind = "task_failed"
    elif status in {"canceled", "cancelled"}:
        kind = "task_canceled"
    elif status in {"active", "underway", "executing"}:
        kind = "task_active"
    elif status in {"queued", "pending"}:
        kind = "task_queued"
    else:
        kind = "task_state"
    event = {"timestamp": timestamp, "event": kind, "task_id": str(task_id), "status": status}
    if isinstance(assigned, dict) and assigned.get("name"):
        event["robot_id"] = str(assigned["name"])
        event["fleet"] = str(assigned.get("group", ""))
    return event


def main() -> None:  # pragma: no cover - requires ROS Kilted
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.parameter import Parameter
        from rmf_fleet_msgs.msg import FleetState
        from std_msgs.msg import String
    except ImportError as exc:
        raise SystemExit(f"ROS Python dependencies unavailable: {exc}") from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    stream = args.output.open("a", encoding="utf-8", newline="\n")

    def emit(event: dict[str, Any]) -> None:
        stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()

    class Collector(Node):
        def __init__(self) -> None:
            super().__init__(
                "aft_telemetry_collector",
                parameter_overrides=[Parameter("use_sim_time", value=True)],
            )
            self.active_tasks_by_robot: dict[str, str] = {}
            self.create_subscription(FleetState, "/fleet_states", self.fleet_state, 100)
            self.create_subscription(String, "/task_state_update", self.task_state, 100)

        def now_seconds(self) -> float:
            stamp = self.get_clock().now().nanoseconds
            return stamp / 1_000_000_000

        def fleet_state(self, message: Any) -> None:
            timestamp = self.now_seconds()
            for robot in message.robots:
                location = robot.location
                task_id = self.active_tasks_by_robot.get(robot.name) or robot.task_id or None
                emit(
                    {
                        "timestamp": timestamp,
                        "event": "robot_state",
                        "fleet": message.name,
                        "robot_id": robot.name,
                        "x": float(location.x),
                        "y": float(location.y),
                        "yaw": float(location.yaw),
                        "task_active": task_id is not None,
                        "task_id": task_id,
                        "battery_percent": float(robot.battery_percent),
                    }
                )

        def task_state(self, message: Any) -> None:
            timestamp = self.now_seconds()
            try:
                payload = json.loads(message.data)
            except json.JSONDecodeError:
                emit({"timestamp": timestamp, "event": "malformed_task_state"})
                return
            event = _task_event(payload, timestamp)
            if event:
                robot_id = event.get("robot_id")
                if robot_id and event["event"] == "task_active":
                    self.active_tasks_by_robot[str(robot_id)] = str(event["task_id"])
                elif robot_id and event["event"] in {
                    "task_completed", "task_failed", "task_canceled"
                }:
                    self.active_tasks_by_robot.pop(str(robot_id), None)
                emit(event)

    rclpy.init()
    node = Collector()
    emit({"timestamp": 0.0, "event": "collector_started", "wall_time": time.time()})
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
        stream.close()


if __name__ == "__main__":
    main()
