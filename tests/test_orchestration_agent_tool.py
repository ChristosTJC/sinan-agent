"""AgentTool Worker 验收测试 — 覆盖全部 6 条 P2 验收标准."""

import tempfile
from pathlib import Path


class TestAgentBasic:
    def test_run_worker_with_allowed_tools(self):
        from agent.tools import get_registry
        from agent.orchestration.agent_tool import AgentTool, AgentRunConfig

        r = get_registry()
        at = AgentTool(r)

        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "hello.txt"
            fpath.write_text("test content")

            config = AgentRunConfig(
                allowed_tools=["read_file", "glob"],
                description="测试 worker",
            )
            tool_calls = [
                {"name": "read_file", "arguments": {"file_path": str(fpath)}},
                {"name": "glob", "arguments": {"pattern": "*.txt", "path": tmp}},
            ]
            result = at.run_worker(config, tool_calls)
            assert result.success, f"Worker failed: {result.results}"
            assert len(result.results) == 2

    def test_empty_tool_calls(self):
        from agent.tools import get_registry
        from agent.orchestration.agent_tool import AgentTool, AgentRunConfig

        r = get_registry()
        at = AgentTool(r)
        result = at.run_worker(AgentRunConfig(), [])
        assert result.success
        assert result.results == []


class TestAgentAllowedTools:
    """验收标准 1: 子 Agent 只能使用 allowed_tools."""

    def test_rejects_tool_not_in_allowed_list(self):
        from agent.tools import get_registry
        from agent.orchestration.agent_tool import AgentTool, AgentRunConfig

        r = get_registry()
        at = AgentTool(r)

        config = AgentRunConfig(
            allowed_tools=["glob"],  # read_file 不在白名单
        )
        tool_calls = [
            {"name": "read_file", "arguments": {"file_path": "/tmp/nonexistent.txt"}},
        ]
        result = at.run_worker(config, tool_calls)
        assert result.success is False
        assert "不在 allowed_tools" in result.results[0].get("error", "")

    def test_allowed_tools_empty_means_no_restriction(self):
        from agent.tools import get_registry
        from agent.orchestration.agent_tool import AgentTool, AgentRunConfig
        import tempfile
        from pathlib import Path

        r = get_registry()
        at = AgentTool(r)

        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "x.txt"
            fpath.write_text("ok")
            result = at.run_worker(AgentRunConfig(allowed_tools=[]), [
                {"name": "read_file", "arguments": {"file_path": str(fpath)}},
            ])
            assert result.success


class TestAgentSecurity:
    """验收标准 2: 子 Agent 尝试读 /etc/passwd 仍被拒绝."""

    def test_rejects_etc_passwd(self):
        from agent.tools import get_registry
        from agent.orchestration.agent_tool import AgentTool, AgentRunConfig

        r = get_registry()
        at = AgentTool(r)

        result = at.run_worker(
            AgentRunConfig(allowed_tools=["read_file"]),
            [{"name": "read_file", "arguments": {"file_path": "/etc/passwd"}}],
        )
        assert result.success is False
        assert result.results[0].get("success") is False

    def test_rejects_write_to_ssh(self):
        from agent.tools import get_registry
        from agent.orchestration.agent_tool import AgentTool, AgentRunConfig

        r = get_registry()
        at = AgentTool(r)

        result = at.run_worker(
            AgentRunConfig(allowed_tools=["write_file"]),
            [{"name": "write_file", "arguments": {"file_path": "/root/.ssh/authorized_keys", "content": "evil"}}],
        )
        assert result.success is False


class TestAgentDangerEvents:
    """验收标准 3: 请求危险工具触发 approval_required 事件."""

    def test_danger_tool_triggers_approval_event(self):
        from agent.tools import get_registry
        from agent.orchestration.agent_tool import AgentTool, AgentRunConfig

        r = get_registry()
        at = AgentTool(r)

        events: list = []

        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "test.txt"
            fpath.write_text("ok")

            result = at.run_worker(
                AgentRunConfig(allowed_tools=["write_file", "read_file"]),
                [
                    {"name": "read_file", "arguments": {"file_path": str(fpath)}},
                    {"name": "write_file", "arguments": {"file_path": str(Path(tmp) / "out.txt"), "content": "x"}},
                ],
                event_callback=lambda e: events.append(e),
            )

            approval_events = [e for e in events if e.type == "approval_required"]
            assert len(approval_events) >= 1, f"Expected approval_required event for write_file, got: {[e.type for e in events]}"
            assert approval_events[0].tool_name == "write_file"


class TestAgentStop:
    """验收标准 4: task_stop 普通停止 / flash graceful only."""

    def test_stop_normal_worker(self):
        from agent.tools import get_registry
        from agent.orchestration.agent_tool import AgentTool

        r = get_registry()
        at = AgentTool(r)

        at._running["test-task"] = {"status": "in_progress", "config": {}}
        assert at.stop_worker("test-task") is True
        assert "test-task" not in at._running

    def test_stop_nonexistent_worker(self):
        from agent.tools import get_registry
        from agent.orchestration.agent_tool import AgentTool

        r = get_registry()
        at = AgentTool(r)
        assert at.stop_worker("nonexistent") is False


class TestAgentOutput:
    def test_worker_result_structure(self):
        from agent.tools import get_registry
        from agent.orchestration.agent_tool import AgentTool, AgentRunConfig
        import tempfile
        from pathlib import Path

        r = get_registry()
        at = AgentTool(r)

        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "out.txt"
            fpath.write_text("data")

            result = at.run_worker(
                AgentRunConfig(allowed_tools=["read_file", "glob"], owner="test-agent",
                               metadata={"env": "test"}),
                [{"name": "read_file", "arguments": {"file_path": str(fpath)}}],
            )
            assert result.task_id.startswith("a"), result.task_id
            assert result.duration_ms > 0
            assert len(result.results) == 1
