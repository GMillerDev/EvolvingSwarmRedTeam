from __future__ import annotations

import os
import re
import signal
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from adversarial_fleet.config import AppConfig
from adversarial_fleet.failures import FailureDetector
from adversarial_fleet.metrics import calculate_metrics
from adversarial_fleet.telemetry import EventWriter, read_events
from adversarial_fleet.telemetry.ros_topics import REQUIRED_TOPICS, ROSBAG_TOPICS

from .process_manager import ProcessManager


class RmfDemoAdapter:
    def __init__(self, config: AppConfig, run_dir: Path) -> None:
        self.config = config
        self.run_dir = run_dir
        self.events_path = run_dir / "events.jsonl"
        self.processes = ProcessManager()
        self._submitted_count = 0
        self._simulation_runtime = 0.0
        self._wall_started: float | None = None
        self._last_orphans: list[dict[str, Any]] = []

    def _environment(self) -> dict[str, str]:
        return os.environ | {
            "ROS_DOMAIN_ID": str(self.config.simulation.ros_domain_id),
            "ROS2CLI_DISABLE_DAEMON": "1",
            "PYTHONUNBUFFERED": "1",
        }

    def _shell_command(self, tokens: list[str]) -> list[str]:
        setup = [self.config.simulation.ros_setup_script]
        if self.config.simulation.workspace_setup_script:
            setup.append(self.config.simulation.workspace_setup_script)
        sources = " && ".join(f"source {shlex.quote(str(path))}" for path in setup)
        command = " ".join(shlex.quote(token) for token in tokens)
        return ["bash", "-lc", f"{sources} && {command}"]

    def initialize(self, attempt: int = 1) -> None:
        self._wall_started = time.monotonic()
        command = self._shell_command(
            [
                "ros2", "launch", "rmf_demos_gz", f"{self.config.simulation.world}.launch.xml",
                "headless:=1", "use_sim_time:=true", "sim_update_rate:=100",
            ]
        )
        process_name = "simulation" if attempt == 1 else f"simulation_retry_{attempt}"
        self.processes.start(
            process_name, command, output_dir=self.run_dir, env=self._environment()
        )

    def health_check(self) -> dict[str, Any]:
        checks: dict[str, Any] = {
            "platform": sys.platform,
            "bash": shutil.which("bash") is not None,
            "ros_setup_script": self.config.simulation.ros_setup_script.exists(),
            "workspace_setup_script": (
                self.config.simulation.workspace_setup_script is None
                or self.config.simulation.workspace_setup_script.exists()
            ),
            "output_writable": os.access(self.run_dir, os.W_OK),
        }
        if all(
            checks[name]
            for name in ("bash", "ros_setup_script", "workspace_setup_script", "output_writable")
        ):
            package_check = subprocess.run(
                self._shell_command(["ros2", "pkg", "prefix", "rmf_demos_gz"]),
                env=self._environment(), capture_output=True, text=True, timeout=15, check=False,
            )
            checks["rmf_demos_gz"] = package_check.returncode == 0
            topic_check = subprocess.run(
                self._shell_command(["ros2", "topic", "list"]),
                env=self._environment(), capture_output=True, text=True, timeout=15, check=False,
            )
            topics = {line.strip() for line in topic_check.stdout.splitlines() if line.strip()}
            checks["required_topics"] = sorted(REQUIRED_TOPICS & topics)
            clock_check = subprocess.run(
                self._shell_command(["timeout", "5", "ros2", "topic", "echo", "/clock", "--once"]),
                env=self._environment(), capture_output=True, text=True, timeout=10, check=False,
            )
            fleet_check = subprocess.run(
                self._shell_command(
                    ["timeout", "5", "ros2", "topic", "echo", "/fleet_states", "--once"]
                ),
                env=self._environment(), capture_output=True, text=True, timeout=10, check=False,
            )
            checks["clock_publishing"] = clock_check.returncode == 0 and "clock:" in clock_check.stdout
            checks["robots_ready"] = fleet_check.returncode == 0 and "- name:" in fleet_check.stdout
            checks["ready"] = (
                topic_check.returncode == 0
                and REQUIRED_TOPICS <= topics
                and checks["clock_publishing"]
                and checks["robots_ready"]
            )
        else:
            checks.update(
                {
                    "rmf_demos_gz": False,
                    "required_topics": [],
                    "clock_publishing": False,
                    "robots_ready": False,
                    "ready": False,
                }
            )
        checks["healthy"] = all(
            [
                checks["bash"], checks["ros_setup_script"], checks["workspace_setup_script"],
                checks["output_writable"], checks["rmf_demos_gz"],
            ]
        )
        return checks

    def reset(self, seed: int, scenario: dict[str, Any]) -> None:
        # A fresh process group is the reset boundary. Seed support is not yet exposed by Office.
        if seed < 0 or not scenario:
            raise ValueError("reset requires a valid seed and scenario")

    def start(self) -> None:
        collector = self._shell_command(
            ["python3", "-m", "adversarial_fleet.telemetry.ros_collector", "--output", str(self.events_path)]
        )
        self.processes.start(
            "collector", collector, output_dir=self.run_dir, env=self._environment()
        )
        if self.config.recording.enable_rosbag:
            bag_command = self._shell_command(
                [
                    "ros2", "bag", "record", "--storage", "mcap",
                    "--output", str(self.run_dir / "rosbag"), *ROSBAG_TOPICS,
                ]
            )
            managed = self.processes.start(
                "rosbag", bag_command, output_dir=self.run_dir, env=self._environment()
            )
            time.sleep(1.0)
            if managed.process.poll() is not None:
                error = managed.stderr_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(f"rosbag recorder exited during startup: {error[-1000:]}")

    def submit_tasks(self, tasks: list[dict[str, Any]]) -> None:
        self._submitted_count = len(tasks)
        for task in tasks:
            command = self._shell_command(
                [
                    "ros2", "run", "rmf_demos_tasks", "dispatch_patrol",
                    "-p", *[str(place) for place in task["places"]],
                    "-n", str(task.get("rounds", 1)),
                    "-st", str(round(float(task["start_offset_seconds"]))),
                    "-pt", str(task.get("priority", 0)), "--use_sim_time",
                ]
            )
            managed = self.processes.start(
                f"submit_{task['task_id']}", command, output_dir=self.run_dir,
                env=self._environment(),
            )
            try:
                return_code = managed.process.wait(timeout=15)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(f"task submission timed out: {task['task_id']}") from exc
            output = managed.stdout_path.read_text(encoding="utf-8", errors="replace")
            task_id_match = re.search(r"['\"]id['\"]\s*:\s*['\"]([^'\"]+)", output)
            if return_code != 0 or not task_id_match:
                error = managed.stderr_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(
                    f"task submission failed or returned no RMF task id for {task['task_id']}: "
                    f"exit={return_code}; stderr={error[-500:]}"
                )
            rmf_task_id = task_id_match.group(1)
            simulation_time = self.observe()["simulation_time"]
            with EventWriter(self.events_path) as writer:
                writer.write(
                    {
                        "timestamp": float(simulation_time),
                        "event": "task_submitted",
                        "task_id": rmf_task_id,
                        "candidate_task_id": task["task_id"],
                        "places": task["places"],
                        "scheduled_start_offset": float(task["start_offset_seconds"]),
                    }
                )

    def observe(self) -> dict[str, Any]:
        events = self.observe_events()
        if events:
            self._simulation_runtime = max(float(event.get("timestamp", 0)) for event in events)
        return {"event_count": len(events), "simulation_time": self._simulation_runtime}

    def observe_events(self) -> list[dict[str, Any]]:
        return read_events(self.events_path)

    def is_complete(self) -> bool:
        terminal = {
            str(event["task_id"]) for event in self.observe_events()
            if event.get("event") in {"task_completed", "task_failed", "task_canceled"}
            and event.get("task_id")
        }
        return self._submitted_count > 0 and len(terminal) >= self._submitted_count

    def has_failed(self) -> bool:
        detector = FailureDetector(self.config.failure_detection)
        return detector.detect(self.observe_events()).is_failure

    def calculate_metrics(self) -> dict[str, float]:
        wall_clock_runtime = (
            time.monotonic() - self._wall_started if self._wall_started is not None else 0.0
        )
        return calculate_metrics(
            self.observe_events(),
            simulation_runtime=self._simulation_runtime,
            wall_clock_runtime=wall_clock_runtime,
        )

    def export_replay(self, output_dir: str) -> None:
        if Path(output_dir).resolve() != self.run_dir.resolve():
            raise ValueError("the initial adapter exports directly into its allocated run directory")

    def shutdown(self) -> None:
        self.processes.stop_all(graceful_timeout=20.0, kill_timeout=5.0)
        orphans = self.processes.orphan_pids()
        if orphans:
            raise RuntimeError(f"orphan processes remain: {orphans}")
        found = self._find_unmanaged_processes()
        for sig, timeout_seconds in (
            (signal.SIGINT, 5.0),
            (signal.SIGTERM, 5.0),
            (signal.SIGKILL, 2.0),
        ):
            if not found:
                break
            for process in found:
                try:
                    os.kill(int(process["pid"]), sig)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                time.sleep(0.2)
                found = self._find_unmanaged_processes()
                if not found:
                    break
        self._last_orphans = found
        if found:
            raise RuntimeError(f"unmanaged ROS/Gazebo processes remain: {found}")

    def _find_unmanaged_processes(self) -> list[dict[str, Any]]:
        process_list = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,stat=,args="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        patterns = (
            "ros2 launch",
            "ros2 bag",
            "gz sim",
            "/rmf_",
            "fleet_adapter",
            "fleet_manager",
            "ros_collector",
            "ros_gz_bridge",
            "building_map_server",
        )
        found: list[dict[str, Any]] = []
        for line in process_list.stdout.splitlines():
            fields = line.strip().split(maxsplit=3)
            if len(fields) != 4:
                continue
            pid, parent_pid, state, command = fields
            if int(pid) == os.getpid():
                continue
            if any(pattern in command for pattern in patterns):
                found.append(
                    {
                        "pid": int(pid),
                        "ppid": int(parent_pid),
                        "state": state,
                        "command": command,
                    }
                )
        return found

    @property
    def orphan_processes(self) -> list[dict[str, Any]]:
        return list(self._last_orphans)
