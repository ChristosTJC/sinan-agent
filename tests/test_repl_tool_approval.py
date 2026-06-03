"""REPL tool approval regression tests."""

from __future__ import annotations

import json

from agent.llm.client import ToolCall
from agent.repl.repl import SinanREPL
from agent.tools import DangerLevel, ToolRegistry


class PlainCompactor:
    def compress_tool_result(self, _name: str, content: str, max_chars: int = 400) -> str:
        return content[:max_chars]


def test_repl_approval_satisfies_registry_danger_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    registry = ToolRegistry()
    registry.register(
        "danger_tool",
        lambda _args: {"success": True, "value": "ran"},
        danger_level=DangerLevel.HIGH,
    )

    repl = object.__new__(SinanREPL)
    repl.tool_registry = registry
    repl.message_compactor = PlainCompactor()

    statuses: list[tuple[str, str]] = []
    message = repl._execute_single_tool(
        ToolCall(id="tc-1", name="danger_tool", arguments={"pin": "PA5", "TOKEN": "tok-secret"}),
        lambda name, status: statuses.append((name, status)),
        lambda _name, _args: True,
    )

    assert message["role"] == "tool"
    assert message["tool_call_id"] == "tc-1"
    assert "'success': True" in message["content"]
    assert "需要确认" not in message["content"]
    assert statuses == [("danger_tool", "running"), ("danger_tool", "done")]

    event_path = tmp_path / ".sinan" / "repl_events" / "event.jsonl"
    event_text = event_path.read_text(encoding="utf-8")
    events = [json.loads(line) for line in event_text.splitlines()]
    assert [event["type"] for event in events] == ["tool_start", "approval_required", "tool_done"]
    assert events[0]["danger_level"] == "high"
    assert "tok-secret" not in event_text
    assert events[0]["arguments"]["TOKEN"] == "[REDACTED]"
