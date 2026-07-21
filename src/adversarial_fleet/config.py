from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectConfig(StrictModel):
    name: str = "adversarial-fleet-testing"
    output_dir: Path = Path("./results")


class SimulationConfig(StrictModel):
    adapter: Literal["rmf_demo"] = "rmf_demo"
    world: Literal["office"] = "office"
    mission_timeout_seconds: float = Field(default=300, gt=0)
    startup_timeout_seconds: float = Field(default=300, gt=0)
    startup_attempt_timeout_seconds: float = Field(default=90, gt=0)
    startup_max_attempts: int = Field(default=3, ge=1)
    poll_interval_seconds: float = Field(default=1.0, gt=0)
    deterministic: bool = True
    ros_domain_id: int = Field(default=0, ge=0, le=232)
    ros_setup_script: Path = Path("/opt/ros/kilted/setup.bash")
    workspace_setup_script: Path | None = Path("/rmf_demos_ws/install/setup.bash")


class RecordingConfig(StrictModel):
    enable_rosbag: bool = True
    enable_video: bool = False
    record_stdout: bool = True
    record_stderr: bool = True


class FailureDetectionConfig(StrictModel):
    deadlock: bool = True
    starvation: bool = True
    recovery_loop: bool = False
    deadlock_minimum_robots: int = Field(default=2, ge=2)
    deadlock_movement_threshold_meters: float = Field(default=0.10, gt=0)
    deadlock_observation_window_seconds: float = Field(default=15, gt=0)
    deadlock_timeout_seconds: float = Field(default=30, gt=0)
    starvation_threshold_seconds: float = Field(default=120, gt=0)
    starvation_minimum_newer_tasks_completed: int = Field(default=2, ge=1)


class AppConfig(StrictModel):
    project: ProjectConfig = ProjectConfig()
    simulation: SimulationConfig = SimulationConfig()
    recording: RecordingConfig = RecordingConfig()
    failure_detection: FailureDetectionConfig = FailureDetectionConfig()


def load_document(path: Path) -> dict[str, Any]:
    """Load JSON or YAML, with JSON remaining usable in dependency-minimal environments."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(raw)
    else:
        try:
            import yaml
        except ModuleNotFoundError as exc:  # pragma: no cover - packaging guard
            raise RuntimeError("PyYAML is required to read YAML files; install the project") from exc
        value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a mapping at the root of {path}")
    return value


def load_config(path: Path) -> AppConfig:
    return AppConfig.model_validate(load_document(path))
