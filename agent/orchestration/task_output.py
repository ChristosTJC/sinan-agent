"""有界输出缓冲 — 8MB 内存 + 磁盘溢出。"""
from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Optional


class TaskOutput:
    DEFAULT_MAX_MEMORY = 8 * 1024 * 1024  # 8MB

    def __init__(
        self,
        task_id: str,
        output_dir: Optional[Path] = None,
        max_memory: int = DEFAULT_MAX_MEMORY,
    ):
        self.task_id = task_id
        self._output_dir = output_dir or (Path.home() / ".sinan" / "task_output")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._output_file = self._output_dir / f"{task_id}.out"
        self._max_memory = max_memory
        self._buffer = ""
        self._total_bytes = 0
        self._overflowed = False

    def write(self, data: str) -> None:
        self._total_bytes += len(data)
        if self._overflowed:
            self._append_to_file(data)
            return
        if len(self._buffer) + len(data) > self._max_memory:
            self._spill_to_disk(data)
            return
        self._buffer += data

    def get_output(self, max_bytes: int = 500_000) -> str:
        if self._overflowed:
            try:
                content = self._output_file.read_text()
                if len(content) > max_bytes:
                    return content[:max_bytes] + f"\n... ({len(content)} bytes total)"
                return content
            except FileNotFoundError:
                return self._buffer or ""
        if len(self._buffer) > max_bytes:
            return self._buffer[:max_bytes] + f"\n... ({len(self._buffer)} bytes total)"
        return self._buffer

    def clear(self) -> None:
        self._buffer = ""
        self._total_bytes = 0
        self._overflowed = False
        with suppress(OSError):
            self._output_file.unlink(missing_ok=True)

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def is_overflowed(self) -> bool:
        return self._overflowed

    def _spill_to_disk(self, current_data: str) -> None:
        self._overflowed = True
        self._append_to_file(self._buffer + current_data)
        self._buffer = ""

    def _append_to_file(self, data: str) -> None:
        with open(self._output_file, "a") as f:
            f.write(data)
