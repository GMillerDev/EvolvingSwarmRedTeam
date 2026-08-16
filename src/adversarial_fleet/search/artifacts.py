from __future__ import annotations

import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Any

import yaml

from adversarial_fleet.config import AppConfig
from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities

from .config import SearchFileConfig
from .evaluation import AggregateEvaluation


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f"{path.name}-",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


class SearchArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.checkpoints = self.root / "checkpoints"
        self.run_references = self.root / "run_references"
        self.candidates_path = self.root / "candidates.jsonl"
        self.evaluations_path = self.root / "evaluations.jsonl"
        self.accounting_path = self.root / "evaluation_accounting.jsonl"
        self.checkpoint_path = self.checkpoints / "latest.json"

    def initialize(
        self,
        *,
        search_id: str,
        search_config: SearchFileConfig,
        app_config: AppConfig,
        capabilities: ScenarioCapabilities,
        environment: dict[str, Any],
    ) -> None:
        if self.root.exists() and any(self.root.iterdir()):
            raise FileExistsError(f"search directory already exists and is not empty: {self.root}")
        self.checkpoints.mkdir(parents=True, exist_ok=True)
        self.run_references.mkdir(parents=True, exist_ok=True)
        (self.root / "search_config.yaml").write_text(
            yaml.safe_dump(
                search_config.model_dump(mode="json"),
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (self.root / "simulator_config.yaml").write_text(
            yaml.safe_dump(
                app_config.model_dump(mode="json"),
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        _atomic_json(self.root / "capabilities.json", capabilities.normalized())
        _atomic_json(self.root / "environment.json", environment)
        _atomic_json(
            self.root / "manifest.json",
            {
                "schema_version": 1,
                "search_id": search_id,
                "algorithm": search_config.search.algorithm,
                "evaluator": search_config.execution.evaluator,
                "evaluation_budget": search_config.search.evaluation_budget,
                "search_seed": search_config.search.search_seed,
                "realization_seeds": list(search_config.search.realization_seeds),
                "capabilities_version": capabilities.version,
                "capabilities_hash": capabilities.digest(),
                "platform": platform.platform(),
                "status": "running",
            },
        )
        self.candidates_path.touch()
        self.evaluations_path.touch()
        self.accounting_path.touch()

    @staticmethod
    def _append_jsonl(path: Path, value: Any) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())

    def append_candidate(
        self,
        *,
        evaluation_index: int,
        generation: int,
        genome: Any,
    ) -> None:
        self._append_jsonl(
            self.candidates_path,
            {
                "evaluation_index": evaluation_index,
                "generation": generation,
                "candidate_id": genome.digest(),
                "genome": genome.model_dump(mode="json"),
            },
        )

    def append_evaluation(
        self,
        evaluation: AggregateEvaluation,
        *,
        evaluation_index: int,
        generation: int,
        cumulative_cache_hit_count: int | None = None,
        wall_clock_elapsed_seconds: float | None = None,
    ) -> None:
        self._append_jsonl(
            self.evaluations_path,
            {
                "evaluation_index": evaluation_index,
                "generation": generation,
                "evaluation": evaluation.model_dump(mode="json"),
            },
        )
        self._append_jsonl(
            self.accounting_path,
            {
                "evaluation_index": evaluation_index,
                "cumulative_cache_hit_count": cumulative_cache_hit_count,
                "wall_clock_elapsed_seconds": wall_clock_elapsed_seconds,
            },
        )
        references = [
            {
                "realization_id": run.realization_id,
                "realization_seed": run.realization_seed,
                "phenotype_hash": run.phenotype_hash,
                "state": run.state.value,
                "run_path": run.run_path,
                "orphan_process_count": run.orphan_process_count,
            }
            for run in evaluation.runs
        ]
        _atomic_json(
            self.run_references / f"{evaluation.candidate_id}.json",
            {
                "candidate_id": evaluation.candidate_id,
                "references": references,
            },
        )

    def load_evaluations(self) -> list[AggregateEvaluation]:
        return [
            AggregateEvaluation.model_validate(record["evaluation"])
            for record in self.load_evaluation_records()
        ]

    def load_evaluation_records(self) -> list[dict[str, Any]]:
        if not self.evaluations_path.is_file():
            return []
        output: list[dict[str, Any]] = []
        for line in self.evaluations_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                output.append(json.loads(line))
        accounting: dict[int, dict[str, Any]] = {}
        if self.accounting_path.is_file():
            for line in self.accounting_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    accounting[int(record["evaluation_index"])] = record
        for record in output:
            metadata = accounting.get(int(record["evaluation_index"]), {})
            for key in ("cumulative_cache_hit_count", "wall_clock_elapsed_seconds"):
                if metadata.get(key) is not None:
                    record[key] = metadata[key]
        return output

    def save_checkpoint(self, value: dict[str, Any]) -> None:
        _atomic_json(self.checkpoint_path, value)

    def load_checkpoint(self) -> dict[str, Any]:
        if not self.checkpoint_path.is_file():
            raise FileNotFoundError(self.checkpoint_path)
        value = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("checkpoint root must be a JSON object")
        return value

    def finalize(
        self,
        *,
        summary: dict[str, Any],
        archive: dict[str, Any],
        novelty_archive: list[dict[str, Any]],
        status: str,
    ) -> None:
        _atomic_json(self.root / "summary.json", summary)
        _atomic_json(self.root / "archive.json", archive)
        _atomic_json(self.root / "novelty_archive.json", novelty_archive)
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        manifest["status"] = status
        manifest["completed_candidate_count"] = summary["measures"]["candidate_count"]
        _atomic_json(self.root / "manifest.json", manifest)
