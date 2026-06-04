from __future__ import annotations

from agent.core.approval import AutoApprove, DenyDangerous
from agent.core.renderer import NullRenderer
from agent.core.session import AgentSession, TurnResult
from agent.llm.client import LLMResponse, ToolCall
from agent.tools import DangerLevel


class FakeLLM:
    """按预设脚本逐轮返回 LLMResponse。"""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.model = "fake"

    def chat(self, messages, tools=None):
        resp = self._script[self.calls]
        self.calls += 1
        return resp


class FakeRegistry:
    def __init__(self, danger=()):
        self._danger = set(danger)
        self.calls = []

    def list_tools(self):
        return [{"name": "scan_usb", "description": "", "parameters": {"type": "object", "properties": {}}},
                {"name": "flash_firmware", "description": "", "parameters": {"type": "object", "properties": {}}}]

    def is_dangerous(self, name):
        return name in self._danger

    def get_danger_level(self, name):
        return DangerLevel.HIGH if name in self._danger else DangerLevel.SAFE

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name in self._danger and getattr(self, "_confirm_callback", None):
            if not self._confirm_callback(name, "high", arguments):
                return {"success": False, "error": "用户拒绝执行"}
        return {"success": True, "result": f"{name}-ok"}

    def set_confirm_callback(self, cb):
        self._confirm_callback = cb

    def set_danger_confirm(self, enabled):
        self._danger_confirm = enabled


def _session(llm, registry, **kw):
    return AgentSession(
        llm, registry,
        system_prompt="sys",
        approval=kw.pop("approval", AutoApprove()),
        renderer=kw.pop("renderer", NullRenderer()),
        stream=False,
        **kw,
    )


def test_single_turn_no_tools():
    llm = FakeLLM([LLMResponse(content="你好", tool_calls=[])])
    s = _session(llm, FakeRegistry())
    result = s.send("hi")
    assert isinstance(result, TurnResult)
    assert result.final_text == "你好"
    assert result.tool_calls_made == 0
    assert result.hit_depth_limit is False


def test_multi_turn_tool_chain():
    llm = FakeLLM([
        LLMResponse(content="", tool_calls=[ToolCall(id="a", name="scan_usb", arguments={})]),
        LLMResponse(content="扫描完成", tool_calls=[]),
    ])
    reg = FakeRegistry()
    s = _session(llm, reg)
    result = s.send("扫描 usb")
    assert result.final_text == "扫描完成"
    assert result.tool_calls_made == 1
    assert reg.calls == [("scan_usb", {})]


def test_dangerous_tool_rejected_records():
    llm = FakeLLM([
        LLMResponse(content="", tool_calls=[ToolCall(id="f", name="flash_firmware", arguments={})]),
        LLMResponse(content="已停止", tool_calls=[]),
    ])
    reg = FakeRegistry(danger={"flash_firmware"})
    s = _session(llm, reg, approval=DenyDangerous())
    result = s.send("烧录")
    assert "flash_firmware" in result.rejected_tools


def test_depth_limit_terminates():
    # LLM 永远要求工具 → 必须被 max_tool_depth 截断
    script = [LLMResponse(content="", tool_calls=[ToolCall(id=str(i), name="scan_usb", arguments={})])
              for i in range(10)]
    llm = FakeLLM(script)
    s = _session(llm, FakeRegistry(), max_tool_depth=3)
    result = s.send("loop")
    assert result.hit_depth_limit is True
    assert result.depth_reached == 3


def test_tool_failure_feeds_back():
    class FailRegistry(FakeRegistry):
        def call_tool(self, name, arguments):
            return {"success": False, "error": "boom"}

    llm = FakeLLM([
        LLMResponse(content="", tool_calls=[ToolCall(id="a", name="scan_usb", arguments={})]),
        LLMResponse(content="已知悉错误", tool_calls=[]),
    ])
    s = _session(llm, FailRegistry())
    result = s.send("x")
    assert result.final_text == "已知悉错误"
    # 失败结果作为 tool 消息回灌
    assert any(m.get("role") == "tool" for m in s.messages)


class RecordingRenderer:
    def __init__(self):
        self.events = []

    def on_text_delta(self, text):
        pass

    def on_tool_status(self, name, status):
        pass

    def on_event(self, event):
        self.events.append(event.type)


def test_dangerous_tool_emits_approval_required_sequence():
    llm = FakeLLM([
        LLMResponse(content="", tool_calls=[ToolCall(id="f", name="flash_firmware", arguments={})]),
        LLMResponse(content="完成", tool_calls=[]),
    ])
    reg = FakeRegistry(danger={"flash_firmware"})
    rec = RecordingRenderer()
    s = AgentSession(llm, reg, system_prompt="sys", approval=AutoApprove(),
                     renderer=rec, stream=False)
    s.send("烧录")
    assert rec.events == ["tool_start", "approval_required", "tool_done"]
