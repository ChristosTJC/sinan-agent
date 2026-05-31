import pytest
from datetime import datetime
from agent.tasks.task import Task, TaskStatus, TaskType, TaskResult


def test_task_creation():
    """测试任务创建"""
    task = Task(
        id="task-001",
        name="test_task",
        type=TaskType.TOOL_CALL,
        status=TaskStatus.PENDING,
        executor=lambda: "result",
        args={"arg1": "value1"},
        dependencies=[],
        children=[],
        result=None,
        created_at=datetime.now(),
        started_at=None,
        completed_at=None,
        progress=0.0,
        checkpoint_data=None,
    )

    assert task.id == "task-001"
    assert task.status == TaskStatus.PENDING
    assert task.progress == 0.0


def test_task_duration():
    """测试任务时长计算"""
    task = Task(
        id="task-002",
        name="test_task",
        type=TaskType.TOOL_CALL,
        status=TaskStatus.COMPLETED,
        executor=lambda: "result",
        args={},
        dependencies=[],
        children=[],
        result=None,
        created_at=datetime(2026, 5, 31, 10, 0, 0),
        started_at=datetime(2026, 5, 31, 10, 0, 5),
        completed_at=datetime(2026, 5, 31, 10, 0, 15),
        progress=1.0,
        checkpoint_data=None,
    )

    assert task.duration() == 10.0
