"""UI 组件单元测试"""

from agent.repl.widgets import TaskCard, TaskStatus


def test_task_card_pending():
    """测试待处理状态的任务卡片"""
    card = TaskCard(
        name="serial_monitor",
        status=TaskStatus.PENDING,
        description="监听串口"
    )
    output = card.render()
    assert "⏳" in output
    assert "serial_monitor" in output


def test_task_card_with_progress():
    """测试带进度条的任务卡片"""
    card = TaskCard(
        name="build_firmware",
        status=TaskStatus.RUNNING,
        description="编译固件",
        progress=0.6
    )
    output = card.render()
    assert "⚙️" in output
    assert "60%" in output
