"""统一事件类型测试."""

import json
import time
from dataclasses import asdict


class TestEventType:
    """EventType 枚举测试."""

    def test_has_text_delta(self):
        from agent.orchestration.events import EventType

        assert EventType.TEXT_DELTA.value == "text_delta"

    def test_has_tool_start(self):
        from agent.orchestration.events import EventType

        assert EventType.TOOL_START.value == "tool_start"

    def test_has_tool_done(self):
        from agent.orchestration.events import EventType

        assert EventType.TOOL_DONE.value == "tool_done"

    def test_has_tool_error(self):
        from agent.orchestration.events import EventType

        assert EventType.TOOL_ERROR.value == "tool_error"

    def test_has_approval_required(self):
        from agent.orchestration.events import EventType

        assert EventType.APPROVAL_REQUIRED.value == "approval_required"

    def test_has_run_start(self):
        from agent.orchestration.events import EventType

        assert EventType.RUN_START.value == "run_start"

    def test_has_phase_start(self):
        from agent.orchestration.events import EventType

        assert EventType.PHASE_START.value == "phase_start"

    def test_has_step_start(self):
        from agent.orchestration.events import EventType

        assert EventType.STEP_START.value == "step_start"


class TestToolStartEvent:
    """工具开始事件."""

    def test_tool_start_event_construction(self):
        from agent.orchestration.events import ToolStartEvent

        event = ToolStartEvent(
            tool_name="read_file",
            danger_level="safe",
            arguments={"file_path": "/tmp/test.txt"},
        )
        assert event.type == "tool_start"
        assert event.tool_name == "read_file"
        assert event.danger_level == "safe"
        assert event.arguments == {"file_path": "/tmp/test.txt"}
        assert event.timestamp > 0

    def test_tool_start_event_serializable(self):
        from agent.orchestration.events import ToolStartEvent

        event = ToolStartEvent(
            tool_name="read_file",
            danger_level="safe",
            arguments={"file_path": "/tmp/test.txt"},
        )
        d = asdict(event)
        assert d["type"] == "tool_start"
        assert d["tool_name"] == "read_file"
        assert isinstance(json.dumps(d), str)


class TestToolDoneEvent:
    """工具完成事件."""

    def test_tool_done_event_construction(self):
        from agent.orchestration.events import ToolDoneEvent

        event = ToolDoneEvent(
            tool_name="read_file",
            danger_level="safe",
            success=True,
            duration_ms=12.5,
            result_summary="ok",
        )
        assert event.type == "tool_done"
        assert event.success is True
        assert event.duration_ms == 12.5

    def test_tool_done_event_failure(self):
        from agent.orchestration.events import ToolDoneEvent

        event = ToolDoneEvent(
            tool_name="flash_firmware",
            danger_level="high",
            success=False,
            duration_ms=1500.0,
            result_summary="烧录超时",
        )
        assert event.success is False
        assert event.result_summary == "烧录超时"


class TestToolErrorEvent:
    """工具异常事件."""

    def test_tool_error_event(self):
        from agent.orchestration.events import ToolErrorEvent

        event = ToolErrorEvent(
            tool_name="build_firmware",
            error="cmake: command not found",
        )
        assert event.type == "tool_error"
        assert "cmake" in event.error


class TestApprovalRequiredEvent:
    """审批请求事件."""

    def test_approval_required_event(self):
        from agent.orchestration.events import ApprovalRequiredEvent

        event = ApprovalRequiredEvent(
            tool_name="flash_firmware",
            danger_level="high",
            arguments={"chip": "nRF52840"},
        )
        assert event.type == "approval_required"
        assert event.tool_name == "flash_firmware"


class TestRunPhaseEvents:
    """运行/阶段事件."""

    def test_run_start_event(self):
        from agent.orchestration.events import RunStartEvent

        event = RunStartEvent(goal="扫描串口", run_id="abc123")
        assert event.type == "run_start"
        assert event.goal == "扫描串口"

    def test_phase_start_event(self):
        from agent.orchestration.events import PhaseStartEvent

        event = PhaseStartEvent(phase="plan", label="生成计划")
        assert event.type == "phase_start"
        assert event.phase == "plan"


class TestSinanEventBase:
    """事件基类."""

    def test_all_events_have_type_and_timestamp(self):
        from agent.orchestration.events import (
            ToolStartEvent, ToolDoneEvent, ToolErrorEvent,
            ApprovalRequiredEvent, RunStartEvent, PhaseStartEvent,
        )

        events = [
            ToolStartEvent("grep", "safe", {}),
            ToolDoneEvent("grep", "safe", True, 1.0, "ok"),
            ToolErrorEvent("grep", "failed"),
            ApprovalRequiredEvent("flash", "high", {}),
            RunStartEvent("test", "id"),
            PhaseStartEvent("plan", "计划"),
        ]
        for e in events:
            assert e.type, f"missing type: {e}"
            assert e.timestamp > 0, f"missing timestamp: {e}"


