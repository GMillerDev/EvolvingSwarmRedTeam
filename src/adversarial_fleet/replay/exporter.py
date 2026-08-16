from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any

from adversarial_fleet.config import AppConfig
from adversarial_fleet.failures.models import FailureReport
from adversarial_fleet.scenarios.genome import ScenarioGenome, TaskSpec
from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities
from adversarial_fleet.scenarios.task_generator import task_sequence_hash


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class ReplayExporter:
    def export(
        self,
        output_dir: Path,
        *,
        scenario: ScenarioGenome,
        tasks: list[TaskSpec],
        config: AppConfig,
        metrics: dict[str, float],
        fitness: dict[str, Any],
        failure: FailureReport,
        capabilities: ScenarioCapabilities | None = None,
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            import yaml
        except ModuleNotFoundError as exc:  # pragma: no cover - packaging guard
            raise RuntimeError("PyYAML is required to export replay packages") from exc
        (output_dir / "scenario.yaml").write_text(
            yaml.safe_dump(scenario.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
        )
        (output_dir / "run_config.yaml").write_text(
            yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
        )
        _write_json(
            output_dir / "seed.json",
            {
                "seed": scenario.seed,
                "scenario_sha256": scenario.digest(),
                "task_sequence_sha256": task_sequence_hash(tasks),
                "capabilities_sha256": (
                    capabilities.digest() if capabilities is not None else None
                ),
            },
        )
        if capabilities is not None:
            _write_json(output_dir / "capabilities.json", capabilities.normalized())
        _write_json(output_dir / "tasks.json", [task.model_dump(mode="json") for task in tasks])
        _write_json(output_dir / "metrics.json", metrics | {"fitness": fitness})
        _write_json(output_dir / "failure.json", failure.model_dump(mode="json"))
        _write_json(
            output_dir / "environment.json",
            {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "ros_distro": os.environ.get("ROS_DISTRO"),
                "ros_domain_id": config.simulation.ros_domain_id,
                "world": config.simulation.world,
                "rmf_container_image": os.environ.get("AFT_RMF_IMAGE"),
                "upstream_versions_verified": bool(os.environ.get("AFT_RMF_IMAGE")),
            },
        )
        _write_json(output_dir / "optimizer.json", {"strategy": None, "state": None})
        script = """#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v aft >/dev/null || { echo "aft is not installed" >&2; exit 2; }
aft health-check --config "$here/run_config.yaml"
aft replay --package "$here"
"""
        reproduce = output_dir / "reproduce.sh"
        reproduce.write_text(script, encoding="utf-8", newline="\n")
        if os.name != "nt":
            reproduce.chmod(0o755)
        (output_dir / "rosbag").mkdir(exist_ok=True)
        for filename in ("events.jsonl", "stdout.log", "stderr.log"):
            (output_dir / filename).touch(exist_ok=True)
