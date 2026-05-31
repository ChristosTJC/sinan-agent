"""UI 组件单元测试"""

from agent.repl.widgets import TaskCard, TaskStatus
from agent.repl.syntax_highlighter import SyntaxHighlighter


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


def test_syntax_highlighter_c():
    """测试 C 语言代码高亮"""
    code = '''void setup() {
    Serial.begin(115200);
}'''
    highlighter = SyntaxHighlighter()
    output = highlighter.highlight(code, language="c")
    assert "void" in output
    assert "setup" in output


def test_syntax_highlighter_auto_detect():
    """测试自动语言检测"""
    code = "def hello():\n    print('world')"
    highlighter = SyntaxHighlighter()
    output = highlighter.highlight(code)
    assert "def" in output
