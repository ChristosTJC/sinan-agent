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


def test_task_duration_inverted():
    """测试时间倒置时返回 0"""
    task = Task(
        id="task-002b",
        name="test_task",
        type=TaskType.TOOL_CALL,
        status=TaskStatus.COMPLETED,
        executor=lambda: "result",
        created_at=datetime(2026, 5, 31, 10, 0, 0),
        started_at=datetime(2026, 5, 31, 10, 0, 15),
        completed_at=datetime(2026, 5, 31, 10, 0, 5),
        progress=1.0,
    )

    assert task.duration() == 0.0


def test_compress_result_short():
    """测试短结果不压缩"""
    task = Task(
        id="task-003",
        name="test",
        type=TaskType.TOOL_CALL,
        status=TaskStatus.COMPLETED,
        executor=None,
        result=TaskResult(success=True, output="短文本"),
        created_at=datetime.now(),
    )
    assert task.compress_result(max_chars=400) == "短文本"
    assert task.result.compressed is False


def test_compress_result_long():
    """测试长结果压缩"""
    task = Task(
        id="task-004",
        name="test",
        type=TaskType.TOOL_CALL,
        status=TaskStatus.COMPLETED,
        executor=None,
        result=TaskResult(success=True, output="A" * 1000),
        created_at=datetime.now(),
    )
    compressed = task.compress_result(max_chars=400)
    assert "已截断" in compressed
    assert len(compressed) < 1000
    assert task.result.compressed is True


def test_compress_result_none():
    """测试空结果"""
    task = Task(
        id="task-005",
        name="test",
        type=TaskType.TOOL_CALL,
        status=TaskStatus.PENDING,
        executor=None,
        result=None,
        created_at=datetime.now(),
    )
    assert task.compress_result() == ""


def test_compress_result_truncation_accuracy():
    """测试截断字符数计算准确性"""
    task = Task(
        id="task-006",
        name="test",
        type=TaskType.TOOL_CALL,
        status=TaskStatus.COMPLETED,
        executor=None,
        result=TaskResult(success=True, output="B" * 1000),
        created_at=datetime.now(),
    )
    compressed = task.compress_result(max_chars=400)
    # 保留 200 + 200 = 400 字符，截断 600 字符
    assert "已截断 600 字符" in compressed


# ============================================================
# TaskManager 测试
# ============================================================

from agent.tasks.manager import TaskManager


def test_task_manager_create_task():
    """测试任务创建"""
    manager = TaskManager()

    task = manager.create_task(
        name="test_tool",
        type=TaskType.TOOL_CALL,
        executor=lambda: "result",
        args={"port": "/dev/ttyUSB0"},
        dependencies=[],
    )

    assert task.id in manager.tasks
    assert task.status == TaskStatus.PENDING
    assert len(manager.tasks) == 1


def test_task_manager_dependencies():
    """测试任务依赖管理"""
    manager = TaskManager()

    task_a = manager.create_task("task_a", TaskType.TOOL_CALL, lambda: "A", {}, [])
    task_b = manager.create_task("task_b", TaskType.TOOL_CALL, lambda: "B", {}, [task_a.id])

    ready_tasks = manager.get_ready_tasks()
    assert task_a.id in [t.id for t in ready_tasks]
    assert task_b.id not in [t.id for t in ready_tasks]

    # 标记 task_a 完成
    manager.update_status(task_a.id, TaskStatus.COMPLETED)

    ready_tasks = manager.get_ready_tasks()
    assert task_b.id in [t.id for t in ready_tasks]


def test_task_manager_circular_dependency():
    """测试循环依赖检测"""
    manager = TaskManager()

    task_a = manager.create_task("task_a", TaskType.TOOL_CALL, lambda: "A", {}, [])
    task_b = manager.create_task("task_b", TaskType.TOOL_CALL, lambda: "B", {}, [task_a.id])

    # 尝试创建循环依赖
    with pytest.raises(ValueError, match="循环依赖"):
        manager.update_dependencies(task_a.id, [task_b.id])
