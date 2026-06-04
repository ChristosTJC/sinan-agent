from __future__ import annotations

import json
from pathlib import Path

from agent.core.renderer import NullRenderer, TraceRenderer
from agent.orchestration.events import ToolDoneEvent


def test_null_renderer_swallows_everything():
    r = NullRenderer()
    r.on_text_delta("hi")
    r.on_tool_status("scan_usb", "calling")
    r.on_event(ToolDoneEvent(tool_name="scan_usb", danger_level="safe", success=True,
                             duration_ms=1.0, result_summary="ok"))  # 不抛异常即可


def test_trace_renderer_writes_event_jsonl(tmp_path: Path):
    event_path = tmp_path / "event.jsonl"
    r = TraceRenderer(event_path=event_path)
    r.on_event(ToolDoneEvent(tool_name="flash_firmware", danger_level="high",
                             success=True, duration_ms=12.0, result_summary="done"))

    lines = event_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["tool_name"] == "flash_firmware"
    assert payload["type"] == "tool_done"


def test_trace_renderer_text_delta_accumulates(tmp_path: Path):
    r = TraceRenderer(event_path=tmp_path / "event.jsonl")
    r.on_text_delta("Hello ")
    r.on_text_delta("world")
    assert r.text == "Hello world"
