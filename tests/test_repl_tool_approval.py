"""REPL tool approval regression tests."""

from __future__ import annotations

from agent.llm.client import ToolCall
from agent.repl.repl import SinanREPL
from agent.tools import DangerLevel, ToolRegistry


class PlainCompactor:
    def compress_tool_result(self, _name: str, content: str, max_chars: int = 400) -> str:
        return content[:max_chars]


def test_repl_approval_satisfies_registry_danger_gate():
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
        ToolCall(id="tc-1", name="danger_tool", arguments={"pin": "PA5"}),
        lambda name, status: statuses.append((name, status)),
        lambda _name, _args: True,
    )

    assert message["role"] == "tool"
    assert message["tool_call_id"] == "tc-1"
    assert "'success': True" in message["content"]
    assert "需要确认" not in message["content"]
    assert statuses == [("danger_tool", "running"), ("danger_tool", "done")]
