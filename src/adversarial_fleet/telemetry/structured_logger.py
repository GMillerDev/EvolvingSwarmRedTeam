from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class StructuredLogger:
    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        candidate_id: str,
        generation: int | None,
        search_method: str,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("a", encoding="utf-8", newline="\n")
        self._started = time.monotonic()
        self._context = {
            "run_id": run_id,
            "candidate_id": candidate_id,
            "generation": generation,
            "search_method": search_method,
        }

    def log(self, event_type: str, *, simulation_time: float = 0.0, **fields: Any) -> None:
        entry = self._context | {
            "simulation_time": simulation_time,
            "wall_clock_time": time.monotonic() - self._started,
            "event_type": event_type,
        } | fields
        self._stream.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()

