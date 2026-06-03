"""Tests for REPL tool bridge pure helpers."""

from __future__ import annotations

import json

from agent.llm.client import ToolCall
from agent.repl.tool_bridge import (
    build_tool_call_message,
    build_tool_result_message,
    execute_all_tool_calls,
    format_tool_result,
    tools_to_openai_format,
)


class BridgeRegistry:
    def __init__(self):
        self.calls = []

    def is_dangerous(self, name):
        return name == "danger"

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "danger":
            if not self.confirm_callback(name, "high", arguments):
                return {"success": False, "error": "用户拒绝执行工具 'danger'"}
            return {"success": True, "result": "approved"}
        return {"success": True, "result": name, "arguments": arguments}

    def set_confirm_callback(self, callback):
        self.confirm_callback = callback

    def set_danger_confirm(self, enabled):
        self.danger_confirm = enabled


def test_tools_to_openai_format_preserves_schema():
    tools = [{"name": "scan_serial", "description": "scan", "parameters": {"type": "object", "properties": {}}}]

    converted = tools_to_openai_format(tools)

    assert converted == [{
        "type": "function",
        "function": {"name": "scan_serial", "description": "scan", "parameters": {"type": "object", "properties": {}}},
    }]


def test_format_tool_result_truncates_serial_lines_and_counts_devices():
    serial_result = {"success": True, "lines": [f"line-{i}" for i in range(205)], "data": "\n".join(str(i) for i in range(205))}
    serial_payload = json.loads(format_tool_result(serial_result, "serial_monitor"))

    assert len(serial_payload["lines"]) == 200
    assert "仅显示前 200" in serial_payload["lines_truncated"]
    assert "仅显示前 200" in serial_payload["_truncated"]

    devices_payload = json.loads(format_tool_result({"result": [{"port": "a"}, {"port": "b"}]}, "scan_serial"))
    assert devices_payload["result_count"] == 2


def test_build_tool_messages_use_openai_shape():
    call = ToolCall(id="call-1", name="scan_serial", arguments={"port": "/dev/ttyUSB0"})

    assistant = build_tool_call_message("calling", [call])
    tool = build_tool_result_message("call-1", '{"success": true}')

    assert assistant["tool_calls"][0]["function"]["name"] == "scan_serial"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"port": "/dev/ttyUSB0"}
    assert tool == {"role": "tool", "tool_call_id": "call-1", "content": '{"success": true}'}


def test_execute_all_tool_calls_preserves_order_for_parallel_safe_calls():
    registry = BridgeRegistry()
    calls = [
        ToolCall(id="1", name="first", arguments={"x": 1}),
        ToolCall(id="2", name="second", arguments={"x": 2}),
    ]
    statuses = []

    messages = execute_all_tool_calls(calls, registry, status_callback=lambda name, status: statuses.append((name, status)))

    assert [message["tool_call_id"] for message in messages] == ["1", "2"]
    assert json.loads(messages[0]["content"])["result"] == "first"
    assert ("first", "calling") in statuses
    assert ("second", "done") in statuses


def test_execute_all_tool_calls_routes_dangerous_call_through_approval():
    registry = BridgeRegistry()
    calls = [ToolCall(id="danger-1", name="danger", arguments={"write": True})]
    approvals = []

    messages = execute_all_tool_calls(
        calls,
        registry,
        approval_callback=lambda name, args: approvals.append((name, args)) or True,
    )

    assert approvals == [("danger", {"write": True})]
    assert json.loads(messages[0]["content"])["result"] == "approved"
