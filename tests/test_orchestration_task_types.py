"""编排层类型 + 输出缓冲测试."""
import tempfile
from pathlib import Path


class TestOrchestrationTaskTypes:
    def test_task_type_values(self):
        from agent.orchestration.task_types import OrchestrationTaskType
        assert OrchestrationTaskType.LOCAL_AGENT.value == "local_agent"
        assert OrchestrationTaskType.HARDWARE_OP.value == "hardware_op"

    def test_task_status_values(self):
        from agent.orchestration.task_types import OrchestrationTaskStatus
        assert OrchestrationTaskStatus.PENDING.value == "pending"
        assert OrchestrationTaskStatus.IN_PROGRESS.value == "in_progress"
        assert OrchestrationTaskStatus.COMPLETED.value == "completed"
        assert OrchestrationTaskStatus.FAILED.value == "failed"
        assert OrchestrationTaskStatus.KILLED.value == "killed"

    def test_is_terminal_status(self):
        from agent.orchestration.task_types import (
            OrchestrationTaskStatus, is_terminal_status
        )
        assert is_terminal_status(OrchestrationTaskStatus.COMPLETED) is True
        assert is_terminal_status(OrchestrationTaskStatus.FAILED) is True
        assert is_terminal_status(OrchestrationTaskStatus.KILLED) is True
        assert is_terminal_status(OrchestrationTaskStatus.PENDING) is False
        assert is_terminal_status(OrchestrationTaskStatus.IN_PROGRESS) is False

    def test_generate_task_id_agent(self):
        from agent.orchestration.task_types import (
            OrchestrationTaskType, generate_task_id
        )
        tid = generate_task_id(OrchestrationTaskType.LOCAL_AGENT)
        assert tid.startswith("a"), tid
        assert len(tid) == 9

    def test_generate_task_id_hardware(self):
        from agent.orchestration.task_types import (
            OrchestrationTaskType, generate_task_id
        )
        tid = generate_task_id(OrchestrationTaskType.HARDWARE_OP)
        assert tid.startswith("h"), tid

    def test_task_state_base_construction(self):
        from agent.orchestration.task_types import (
            TaskStateBase, OrchestrationTaskType, OrchestrationTaskStatus
        )
        ts = TaskStateBase(
            id="a12345678",
            type=OrchestrationTaskType.LOCAL_AGENT,
            status=OrchestrationTaskStatus.PENDING,
            description="测试 worker",
            owner="driver",
            allowed_tools=["read_file", "grep"],
            metadata={"priority": "high"},
        )
        assert ts.id == "a12345678"
        assert ts.owner == "driver"
        assert ts.allowed_tools == ["read_file", "grep"]
        assert ts.metadata["priority"] == "high"
        assert ts.start_time > 0
        assert ts.end_time is None
        assert ts.output_file == ""


class TestTaskOutput:
    def test_write_and_read_small(self):
        from agent.orchestration.task_output import TaskOutput
        out = TaskOutput("test1")
        out.write("hello world\n")
        assert "hello world" in out.get_output()
        assert out.total_bytes > 0
        assert not out.is_overflowed

    def test_clear_resets(self):
        from agent.orchestration.task_output import TaskOutput
        out = TaskOutput("test2")
        out.write("data")
        out.clear()
        assert out.get_output() == ""
        assert out.total_bytes == 0

    def test_overflow_to_disk(self):
        from agent.orchestration.task_output import TaskOutput
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = TaskOutput("test3", output_dir=Path(tmp), max_memory=10)
            out.write("a" * 20)
            assert out.is_overflowed
            content = out.get_output()
            assert len(content) > 0

    def test_truncation(self):
        from agent.orchestration.task_output import TaskOutput
        out = TaskOutput("test4")
        out.write("x" * 10000)
        content = out.get_output(max_bytes=100)
        assert len(content) <= 150, f"got {len(content)}"
        # Content should be truncated (not full 10000 chars)
        assert len(content) < 10000
