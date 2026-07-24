from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .evaluation import AggregateEvaluation


class SearchStore:
    """Minimal JSONL evaluation log and atomic algorithm checkpoint store."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.evaluations_path = self.root / "evaluations.jsonl"
        self.checkpoint_path = self.root / "checkpoint.json"

    def append_evaluation(self, evaluation: AggregateEvaluation) -> None:
        with self.evaluations_path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    evaluation.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )

    def load_evaluations(self) -> list[AggregateEvaluation]:
        if not self.evaluations_path.is_file():
            return []
        return [
            AggregateEvaluation.model_validate(json.loads(line))
            for line in self.evaluations_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def save_checkpoint(self, state: dict[str, Any]) -> None:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix="checkpoint-",
            suffix=".tmp",
            dir=self.root,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.checkpoint_path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def load_checkpoint(self) -> dict[str, Any]:
        if not self.checkpoint_path.is_file():
            raise FileNotFoundError(self.checkpoint_path)
        value = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("checkpoint root must be a JSON object")
        return value
