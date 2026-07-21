from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from adversarial_fleet.config import AppConfig, load_config, load_document
from adversarial_fleet.orchestrator.runner import ExperimentOrchestrator
from adversarial_fleet.scenarios.genome import ScenarioGenome, TaskSpec
from adversarial_fleet.scenarios.task_generator import generate_tasks, task_sequence_hash


METRIC_TOLERANCES = {
    "failure_score": {"absolute": 0.5},
    "mean_task_latency": {"absolute": 10.0, "relative": 0.20},
    "deadlock_duration": {"absolute": 2.0},
    "tasks_completed": {"absolute": 0.0},
    "tasks_incomplete": {"absolute": 0.0},
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _within_tolerance(original: float, replay: float, tolerance: dict[str, float]) -> bool:
    difference = abs(original - replay)
    absolute = tolerance.get("absolute", 0.0)
    relative = tolerance.get("relative", 0.0) * max(abs(original), 1e-9)
    return difference <= max(absolute, relative)


def verify_rosbag(package_dir: Path) -> dict[str, Any]:
    bag_dir = package_dir / "rosbag"
    metadata = bag_dir / "metadata.yaml"
    data_files = sorted(path for path in bag_dir.glob("*.mcap") if path.stat().st_size > 0)
    metadata_hash = (
        hashlib.sha256(metadata.read_bytes()).hexdigest() if metadata.is_file() else None
    )
    return {
        "valid": metadata.is_file() and bool(data_files),
        "path": str(bag_dir.resolve()),
        "metadata_path": str(metadata.resolve()),
        "metadata_sha256": metadata_hash,
        "data_files": [str(path.resolve()) for path in data_files],
        "data_bytes": sum(path.stat().st_size for path in data_files),
    }


class ReplayVerifier:
    def verify(self, package_dir: Path) -> dict[str, Any]:
        package_dir = package_dir.resolve()
        scenario = ScenarioGenome.model_validate(load_document(package_dir / "scenario.yaml"))
        config: AppConfig = load_config(package_dir / "run_config.yaml")
        saved_tasks = [TaskSpec.model_validate(item) for item in _load_json(package_dir / "tasks.json")]
        generated_tasks = generate_tasks(scenario)
        original_seed = _load_json(package_dir / "seed.json")
        original_metrics_doc = _load_json(package_dir / "metrics.json")
        original_failure = _load_json(package_dir / "failure.json")
        original_task_hash = task_sequence_hash(saved_tasks)
        generated_task_hash = task_sequence_hash(generated_tasks)
        bag = verify_rosbag(package_dir)
        prerequisites = {
            "seed_matches": original_seed["seed"] == scenario.seed,
            "scenario_hash_matches": original_seed["scenario_sha256"] == scenario.digest(),
            "saved_tasks_match_generated": original_task_hash == generated_task_hash,
            "saved_task_hash_matches": (
                original_seed.get("task_sequence_sha256") == original_task_hash
            ),
            "rosbag_valid": bag["valid"],
        }
        if not all(prerequisites.values()):
            report = {"verified": False, "prerequisites": prerequisites, "rosbag": bag}
            self._write(package_dir, report)
            return report

        replay_result = ExperimentOrchestrator(config).run(scenario, candidate_id="replay")
        replay_tasks = [
            TaskSpec.model_validate(item)
            for item in _load_json(replay_result.run_dir / "tasks.json")
        ]
        replay_metrics_doc = _load_json(replay_result.run_dir / "metrics.json")
        replay_failure = _load_json(replay_result.run_dir / "failure.json")
        original_score = float(original_metrics_doc["fitness"]["score"])
        replay_score = float(replay_metrics_doc["fitness"]["score"])
        comparisons = {
            "task_sequence_hash": task_sequence_hash(replay_tasks) == original_task_hash,
            "scenario_hash": scenario.digest() == _load_json(
                replay_result.run_dir / "seed.json"
            )["scenario_sha256"],
            "mission_result": replay_result.status
            == _load_json(package_dir / "run_result.json")["status"],
            "failure_type": replay_failure.get("failure_type")
            == original_failure.get("failure_type"),
            "failure_score": _within_tolerance(
                original_score, replay_score, METRIC_TOLERANCES["failure_score"]
            ),
        }
        for metric in ("mean_task_latency", "deadlock_duration", "tasks_completed", "tasks_incomplete"):
            comparisons[metric] = _within_tolerance(
                float(original_metrics_doc.get(metric, 0.0)),
                float(replay_metrics_doc.get(metric, 0.0)),
                METRIC_TOLERANCES[metric],
            )
        report = {
            "verified": all(comparisons.values()),
            "prerequisites": prerequisites,
            "comparisons": comparisons,
            "tolerances": METRIC_TOLERANCES,
            "rosbag": bag,
            "original_package": str(package_dir),
            "replay_package": str(replay_result.run_dir.resolve()),
            "replay_status": replay_result.status,
        }
        self._write(package_dir, report)
        return report

    @staticmethod
    def _write(package_dir: Path, report: dict[str, Any]) -> None:
        (package_dir / "replay_verification.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
