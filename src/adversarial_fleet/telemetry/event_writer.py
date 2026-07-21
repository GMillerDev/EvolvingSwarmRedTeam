from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterable


class EventWriter:
    """Thread-safe append-only JSONL writer with per-event durability."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("a", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()

    def write(self, event: dict[str, Any]) -> None:
        if "timestamp" not in event or "event" not in event:
            raise ValueError("events require timestamp and event fields")
        line = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()

    def close(self) -> None:
        with self._lock:
            if not self._stream.closed:
                self._stream.close()

    def __enter__(self) -> "EventWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            events.append(value)
    return events


def write_events(path: Path, events: Iterable[dict[str, Any]]) -> None:
    with EventWriter(path) as writer:
        for event in events:
            writer.write(event)

