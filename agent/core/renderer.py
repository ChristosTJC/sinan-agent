"""输出适配器：把 AgentSession 的文本/状态/事件渲染到不同前端。"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Optional, Protocol

from agent.orchestration.events import sanitize_event_payload


class Renderer(Protocol):
    """渲染器协议：会话内核通过它把输出推给具体前端，与 UI 解耦。"""

    def on_text_delta(self, text: str) -> None: ...
    def on_tool_status(self, name: str, status: str) -> None: ...
    def on_event(self, event: object) -> None: ...


class NullRenderer:
    """静默渲染器（sub-agent 用）。"""

    def on_text_delta(self, text: str) -> None:
        pass

    def on_tool_status(self, name: str, status: str) -> None:
        pass

    def on_event(self, event: object) -> None:
        pass


def _event_to_dict(event: object) -> dict:
    """把事件统一转成脱敏后的字典，供 JSONL 落盘。"""
    if is_dataclass(event):
        return sanitize_event_payload(asdict(event))
    if isinstance(event, dict):
        return sanitize_event_payload(event)
    return {"event": str(event)}


class TraceRenderer:
    """headless `sinan run` 用：事件落 JSONL，文本累积供报告。"""

    def __init__(self, event_path: Path) -> None:
        self.event_path = Path(event_path)
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        self.text = ""

    def on_text_delta(self, text: str) -> None:
        self.text += text

    def on_tool_status(self, name: str, status: str) -> None:
        pass

    def on_event(self, event: object) -> None:
        with self.event_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_event_to_dict(event), ensure_ascii=False, default=str) + "\n")


class TerminalRenderer:
    """REPL 用：文本增量打印 + 状态行 + 事件落盘。"""

    def __init__(self, write=None, status=None, event_path: Optional[Path] = None) -> None:
        self._write = write or (lambda s: print(s, end="", flush=True))
        self._status = status
        self.event_path = Path(event_path) if event_path else None
        if self.event_path:
            self.event_path.parent.mkdir(parents=True, exist_ok=True)

    def on_text_delta(self, text: str) -> None:
        self._write(text)

    def on_tool_status(self, name: str, status: str) -> None:
        if self._status:
            self._status(name, status)

    def on_event(self, event: object) -> None:
        if not self.event_path:
            return
        with self.event_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_event_to_dict(event), ensure_ascii=False, default=str) + "\n")
