from __future__ import annotations

from pathlib import Path

from agent.llm.client import LLMResponse, ToolCall
from agent.run_loop import SinanRunController


class FakeLLM:
    def __init__(self, script):
        self._script = list(script); self.calls = 0; self.model = "fake"

    def chat(self, messages, tools=None):
        r = self._script[self.calls]; self.calls += 1; return r


class FakeRegistry:
    def list_tools(self):
        return [{"name": "scan_usb", "description": "", "parameters": {"type": "object", "properties": {}}}]

    def is_dangerous(self, name): return False
    def get_danger_level(self, name):
        from agent.tools import DangerLevel; return DangerLevel.SAFE
    def call_tool(self, name, arguments): return {"success": True, "result": "ok"}
    def set_confirm_callback(self, cb): pass
    def set_danger_confirm(self, e): pass


def test_run_with_llm_uses_agent_session(tmp_path: Path):
    llm = FakeLLM([
        LLMResponse(content="", tool_calls=[ToolCall(id="a", name="scan_usb", arguments={})]),
        LLMResponse(content="完成", tool_calls=[]),
    ])
    ctrl = SinanRunController(
        sinan_home=tmp_path / "home",
        project_path=tmp_path,
        registry=FakeRegistry(),
        memory_store=None, session_db=None, knowledge_base=None,
        llm_client=llm,
        confirm_dangerous=False,
        output_dir=tmp_path / "run",
    )
    result = ctrl.run("扫描 usb 设备")
    assert result["success"] is True
    assert "完成" in result["result"]
    assert (tmp_path / "run" / "event.jsonl").exists()
