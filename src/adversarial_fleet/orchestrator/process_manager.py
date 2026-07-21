from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Mapping, Sequence


@dataclass
class ManagedProcess:
    name: str
    command: tuple[str, ...]
    process: subprocess.Popen[str]
    stdout_path: Path
    stderr_path: Path
    stdout_stream: IO[str]
    stderr_stream: IO[str]


class ProcessManager:
    def __init__(self) -> None:
        self._processes: list[ManagedProcess] = []

    @property
    def processes(self) -> tuple[ManagedProcess, ...]:
        return tuple(self._processes)

    def start(
        self,
        name: str,
        command: Sequence[str],
        *,
        output_dir: Path,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> ManagedProcess:
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = output_dir / ("stdout.log" if name == "simulation" else f"{name}.stdout.log")
        stderr_path = output_dir / ("stderr.log" if name == "simulation" else f"{name}.stderr.log")
        stdout_stream = stdout_path.open("w", encoding="utf-8")
        stderr_stream = stderr_path.open("w", encoding="utf-8")
        kwargs: dict[str, object] = {"start_new_session": os.name != "nt"}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=dict(env) if env else None,
                stdout=stdout_stream,
                stderr=stderr_stream,
                text=True,
                **kwargs,
            )
        except Exception:
            stdout_stream.close()
            stderr_stream.close()
            raise
        managed = ManagedProcess(
            name=name,
            command=tuple(command),
            process=process,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_stream=stdout_stream,
            stderr_stream=stderr_stream,
        )
        self._processes.append(managed)
        return managed

    def stop_all(self, graceful_timeout: float = 10.0, kill_timeout: float = 5.0) -> None:
        alive = [item for item in reversed(self._processes) if item.process.poll() is None]
        for item in alive:
            self._signal_group(item, signal.SIGINT)
        self._wait(alive, graceful_timeout)
        alive = [item for item in alive if item.process.poll() is None]
        for item in alive:
            self._signal_group(item, signal.SIGTERM)
        self._wait(alive, kill_timeout)
        for item in alive:
            if item.process.poll() is None:
                self._signal_group(item, signal.SIGKILL)
        self._wait(alive, kill_timeout)
        for item in self._processes:
            item.stdout_stream.close()
            item.stderr_stream.close()

    @staticmethod
    def _wait(items: list[ManagedProcess], timeout: float) -> None:
        deadline = time.monotonic() + timeout
        for item in items:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                item.process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass

    @staticmethod
    def _signal_group(item: ManagedProcess, sig: signal.Signals) -> None:
        if item.process.poll() is not None:
            return
        try:
            if os.name == "nt":
                if sig == signal.SIGINT:
                    item.process.send_signal(signal.CTRL_BREAK_EVENT)
                elif sig == signal.SIGTERM:
                    item.process.terminate()
                else:
                    item.process.kill()
            else:
                os.killpg(os.getpgid(item.process.pid), sig)
        except ProcessLookupError:
            pass

    def orphan_pids(self) -> list[int]:
        return [item.process.pid for item in self._processes if item.process.poll() is None]
