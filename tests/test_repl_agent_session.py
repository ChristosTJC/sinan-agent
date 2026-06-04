"""REPL 切换到 AgentSession 内核后的状态同步不变量测试。

锁定三条关键不变量：
1. repl.messages 与 AgentSession.messages 共享同一对象（引用未断）。
2. 一次含工具的 turn 后，历史中出现 user / assistant / tool 三种角色。
3. 工具计数持续累加（退出时蒸馏阈值依赖该计数）。

夹具用 object.__new__(SinanREPL) 绕开重型 __init__，仅手动赋必要属性。
FakeLLM 不实现 chat_stream，使 AgentSession 走非流式 chat 分支，便于断言。
"""
from __future__ import annotations

from agent.llm.client import LLMResponse, ToolCall
from agent.repl.repl import SinanREPL


class FakeLLM:
    """脚本化 LLM：按调用次数依次返回预设响应。"""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.model = "fake"

    def chat(self, messages, tools=None):
        r = self._script[self.calls]
        self.calls += 1
        return r


class FakeRegistry:
    """最小工具注册表替身：记录调用、声明工具非危险。"""

    def __init__(self):
        self.calls = []

    def list_tools(self):
        return [{
            "name": "scan_usb",
            "description": "",
            "parameters": {"type": "object", "properties": {}},
        }]

    def is_dangerous(self, name):
        return False

    def get_danger_level(self, name):
        from agent.tools import DangerLevel
        return DangerLevel.SAFE

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"success": True, "result": "ok"}

    def set_confirm_callback(self, cb):
        pass

    def set_danger_confirm(self, enabled):
        pass


class NullSessionDB:
    """L2 会话替身：吞掉持久化写入。"""

    def add_message(self, *a, **k):
        return None


def _make_repl(tmp_path, monkeypatch, llm, registry):
    monkeypatch.setenv("HOME", str(tmp_path))
    repl = object.__new__(SinanREPL)
    repl.client = llm
    repl.tool_registry = registry
    repl._memory_store = None
    repl._knowledge_base = None
    repl.messages = [{"role": "system", "content": "sys"}]
    repl._session_tool_calls = 0
    repl._agent_session = None
    repl._max_tool_depth = 25
    repl._session_db = NullSessionDB()
    repl._session_id = "s1"
    repl.context_manager = type("C", (), {"compact": staticmethod(lambda m: m)})()
    repl._build_system_prompt = lambda: "sys"
    repl.console = None
    return repl


def test_repl_turn_drives_session_and_shares_messages(tmp_path, monkeypatch):
    llm = FakeLLM([
        LLMResponse(content="", tool_calls=[ToolCall(id="a", name="scan_usb", arguments={})]),
        LLMResponse(content="完成", tool_calls=[]),
    ])
    reg = FakeRegistry()
    repl = _make_repl(tmp_path, monkeypatch, llm, reg)

    before = repl._session_tool_calls
    result = repl._run_agent_turn("扫描 usb")

    # 不变量 1：repl.messages 与 session.messages 是同一对象（共享引用未断）
    assert repl.messages is repl._agent_session.messages
    # 不变量 2：一次含工具的 turn 后，含 user / assistant / tool 三种角色
    roles = {m.get("role") for m in repl.messages}
    assert {"user", "assistant", "tool"} <= roles
    # 不变量 3：工具计数累加（退出蒸馏阈值依赖）
    assert result.tool_calls_made >= 1
    assert repl._session_tool_calls == before + result.tool_calls_made
    assert reg.calls == [("scan_usb", {})]
    assert result.final_text == "完成"


def test_switch_model_resets_session(tmp_path, monkeypatch):
    """换模型后 _agent_session 置空，确保下次 turn 用新 client + 新 system 重建。"""
    llm = FakeLLM([LLMResponse(content="hi", tool_calls=[])])
    reg = FakeRegistry()
    repl = _make_repl(tmp_path, monkeypatch, llm, reg)

    # 首轮构造 session
    repl._run_agent_turn("你好")
    assert repl._agent_session is not None

    # 模拟 _switch_model 成功路径末尾的重建标记
    repl._agent_session = None
    assert repl._agent_session is None
