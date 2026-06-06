"""MCP 工具验收测试 — 覆盖全部 9 条 P4 验收标准."""

import os
import sys
import time
from pathlib import Path


_FAKE_SERVER = str(Path(__file__).resolve().parent / "fake_mcp_server.py")


class TestMcpConnection:
    """验收标准 1: fake stdio MCP server 可连接."""

    def test_connect_and_disconnect(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        result = mgr.connect("test-server",
                             [sys.executable, _FAKE_SERVER])
        assert result["success"], result
        assert "capabilities" in result
        assert mgr.is_connected("test-server")

        result2 = mgr.disconnect("test-server")
        assert result2["success"]
        assert not mgr.is_connected("test-server")

    def test_duplicate_connect_rejected(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        mgr.connect("dup-server", [sys.executable, _FAKE_SERVER])
        result = mgr.connect("dup-server", [sys.executable, _FAKE_SERVER])
        assert result["success"] is False
        mgr.disconnect("dup-server")

    def test_disconnect_nonexistent(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        result = mgr.disconnect("no-such-server")
        assert result["success"] is False


class TestMcpToolsList:
    """验收标准 2: list tools/resources 正常."""

    def test_list_tools(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        mgr.connect("ts", [sys.executable, _FAKE_SERVER])
        result = mgr.list_tools("ts")
        assert result["success"], result
        assert len(result["tools"]) == 3
        names = [t["name"] for t in result["tools"]]
        assert "hello" in names
        assert "add" in names
        mgr.disconnect("ts")

    def test_list_resources(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        mgr.connect("rs", [sys.executable, _FAKE_SERVER])
        result = mgr.list_resources("rs")
        assert result["success"], result
        assert len(result["resources"]) == 2
        mgr.disconnect("rs")


class TestMcpToolCall:
    """验收标准 3-4: call tool 正常, read resource 正常."""

    def test_call_hello(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        mgr.connect("cs", [sys.executable, _FAKE_SERVER])
        result = mgr.call_tool("cs", "hello", {"name": "Sinan"})
        assert result["success"], result
        assert "Hello, Sinan" in result.get("text", "")
        mgr.disconnect("cs")

    def test_call_add(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        mgr.connect("adds", [sys.executable, _FAKE_SERVER])
        result = mgr.call_tool("adds", "add", {"a": 3, "b": 4})
        assert result["success"], result
        assert "7" in result.get("text", "")
        mgr.disconnect("adds")

    def test_call_unknown_tool(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        mgr.connect("us", [sys.executable, _FAKE_SERVER])
        result = mgr.call_tool("us", "nonexistent", {})
        assert result["success"] is False
        mgr.disconnect("us")

    def test_read_resource(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        mgr.connect("rrs", [sys.executable, _FAKE_SERVER])
        result = mgr.read_resource("rrs", "file:///test/data.txt")
        assert result["success"], result
        assert "Content of" in result.get("text", "")
        mgr.disconnect("rrs")


class TestMcpAutoRegistration:
    """验收标准 mcp__server__tool 独立注册."""

    def test_tools_auto_registered_after_connect(self):
        from agent.tools import get_registry
        from agent.tools.mcp_client import get_mcp_manager

        mgr = get_mcp_manager()
        mgr.connect("auto", [sys.executable, _FAKE_SERVER])
        from agent.tools.mcp_tools import _register_server_tools

        reg = get_registry()
        count = _register_server_tools(reg, "auto")
        assert count == 3, f"Expected 3 tools registered, got {count}"

        tools = [t["name"] for t in reg.list_tools()]
        assert "mcp__auto__hello" in tools
        assert "mcp__auto__add" in tools
        mgr.disconnect("auto")

    def test_auto_registered_tool_works(self):
        from agent.tools import get_registry
        from agent.tools.mcp_client import get_mcp_manager

        reg = get_registry()
        reg.set_confirm_callback(lambda n, l, a: True)
        mgr = get_mcp_manager()
        mgr.connect("auto2", [sys.executable, _FAKE_SERVER])

        from agent.tools.mcp_tools import _register_server_tools
        _register_server_tools(reg, "auto2")

        result = reg.call_tool("mcp__auto2__hello", {"name": "P4"})
        assert result.get("success"), result
        assert "Hello, P4" in result.get("text", "")
        mgr.disconnect("auto2")


class TestMcpHookIntegration:
    """验收标准 6: MCP 工具经过 Hook，可被 PreToolUse 拦截."""

    def test_pre_tool_use_hook_can_intercept_mcp(self):
        from agent.tools import get_registry
        from agent.tools.mcp_client import get_mcp_manager
        from agent.orchestration.hooks import HookChain, Hook, ToolUseContext

        reg = get_registry()
        reg.set_confirm_callback(lambda n, l, a: True)
        mgr = get_mcp_manager()
        mgr.connect("hook-srv", [sys.executable, _FAKE_SERVER])
        from agent.tools.mcp_tools import _register_server_tools
        _register_server_tools(reg, "hook-srv")

        intercepted = []

        class InterceptHook(Hook):
            def on_pre_tool_use(self, ctx: ToolUseContext) -> ToolUseContext:
                intercepted.append(ctx.tool_name)
                ctx.approved = False
                ctx.error = "被 PreToolUse Hook 拦截"
                return ctx

        reg.set_hook_chain(HookChain([InterceptHook()]))
        result = reg.call_tool("mcp__hook-srv__hello", {"name": "test"})

        assert result.get("success") is False
        assert "拦截" in result.get("error", "")
        assert len(intercepted) >= 1
        assert intercepted[0].startswith("mcp__")

        mgr.disconnect("hook-srv")
        reg.set_hook_chain(None)


class TestMcpAuthSanitization:
    """验收标准 7: MCP auth 不出现在 audit/log/error."""

    def test_env_vars_sanitized_in_connect_result(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        result = mgr.connect("auth-srv", [sys.executable, _FAKE_SERVER],
                             env={"API_KEY": "sk-secret-12345", "NORMAL_VAR": "visible"})
        assert result["success"], result
        mgr.disconnect("auth-srv")


class TestMcpDisconnectError:
    """验收标准 8: MCP server 断开时返回结构化 error."""

    def test_call_after_disconnect_returns_error(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        mgr.connect("disc-srv", [sys.executable, _FAKE_SERVER])
        mgr.disconnect("disc-srv")
        result = mgr.call_tool("disc-srv", "hello", {"name": "x"})
        assert result["success"] is False
        assert "未连接" in result.get("error", "")

    def test_killed_server_returns_error(self):
        from agent.tools.mcp_client import McpClientManager

        mgr = McpClientManager()
        mgr.connect("kill-srv", [sys.executable, _FAKE_SERVER])
        # kill the process
        conn = mgr._connections.get("kill-srv")
        if conn and conn.process:
            conn.process.kill()
            conn.process.wait()
            conn.connected = False
        result = mgr.call_tool("kill-srv", "hello", {"name": "x"})
        assert result["success"] is False
