import pytest
from agent.context.manager import ContextManager


def test_context_manager_no_compression():
    """测试无需压缩的情况"""
    ctx = ContextManager(window_size=10, max_tokens=10000)

    # 添加系统消息
    ctx.add_message("system", "你是一个 RoboMaster 视觉系统助手")

    # 添加用户消息
    ctx.add_message("user", "帮我分析装甲板检测代码")
    ctx.add_message("assistant", "好的，我来分析")

    messages = ctx.get_messages()

    assert len(messages) == 3
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"


def test_context_manager_sliding_window():
    """测试滑动窗口压缩"""
    ctx = ContextManager(window_size=3, max_tokens=10000)

    # 添加系统消息
    ctx.add_message("system", "你是助手")

    # 添加 5 轮对话（超过 window_size=3）
    for i in range(5):
        ctx.add_message("user", f"问题 {i}")
        ctx.add_message("assistant", f"回答 {i}")

    messages = ctx.get_messages()

    # 系统消息 + 最近 3 轮对话 = 1 + 3*2 = 7 条消息
    assert len(messages) == 7
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "你是助手"

    # 验证保留的是最近 3 轮
    assert "问题 2" in messages[1]["content"]
    assert "问题 3" in messages[3]["content"]
    assert "问题 4" in messages[5]["content"]


def test_context_manager_system_message_preserved():
    """测试系统消息始终保留"""
    ctx = ContextManager(window_size=2, max_tokens=10000)

    ctx.add_message("system", "系统提示")

    # 添加 10 轮对话
    for i in range(10):
        ctx.add_message("user", f"问题 {i}")
        ctx.add_message("assistant", f"回答 {i}")

    messages = ctx.get_messages()

    # 系统消息始终在第一条
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "系统提示"

    # 只保留最近 2 轮对话
    assert len(messages) == 5  # 1 系统 + 2*2 对话


def test_context_manager_token_estimation():
    """测试 Token 估算"""
    ctx = ContextManager(window_size=10, max_tokens=100)

    # 添加长消息
    long_text = "A" * 200  # 约 200 tokens
    ctx.add_message("user", long_text)

    # 估算 token 数
    estimated = ctx.estimate_tokens()

    # 应该接近 200
    assert 150 < estimated < 250


def test_context_manager_clear():
    """测试清空上下文"""
    ctx = ContextManager(window_size=10, max_tokens=10000)

    ctx.add_message("system", "系统提示")
    ctx.add_message("user", "问题")
    ctx.add_message("assistant", "回答")

    assert len(ctx.get_messages()) == 3

    ctx.clear()

    assert len(ctx.get_messages()) == 0


# ============================================================
# MessageCompactor 测试
# ============================================================

from agent.context.compactor import MessageCompactor


def test_message_compactor_generic():
    """测试通用压缩策略（头尾保留）"""
    compactor = MessageCompactor()

    long_text = "\n".join([f"行 {i}" for i in range(100)])
    compressed = compactor.compress_generic(long_text, max_lines=20)

    lines = compressed.split("\n")

    # 保留前 10 行 + 分隔符 + 后 10 行
    assert len(lines) <= 22  # 10 + 1 (分隔符) + 10 + 1 (截断信息)
    assert "行 0" in compressed
    assert "行 99" in compressed
    assert "已截断" in compressed


def test_message_compactor_sensor_data():
    """测试传感器数据压缩"""
    compactor = MessageCompactor()

    sensor_log = """
[INFO] 传感器初始化完成
[DATA] 温度: 25.3°C
[DATA] 湿度: 60%
[DATA] 温度: 25.4°C
[DATA] 湿度: 61%
[DATA] 温度: 25.5°C
[ERROR] 传感器异常
[DATA] 温度: 25.6°C
"""

    compressed = compactor.compress_sensor_data(sensor_log, max_lines=10)

    # 应该保留 ERROR 和部分 DATA
    assert "[ERROR]" in compressed
    assert "[INFO]" in compressed
    assert "已截断" in compressed or len(compressed.split("\n")) <= 12


def test_message_compactor_build_log():
    """测试编译日志压缩（保留错误和警告）"""
    compactor = MessageCompactor()

    build_log = """
[ 10%] Building CXX object CMakeFiles/armor_detector.dir/src/detector.cpp.o
[ 20%] Building CXX object CMakeFiles/armor_detector.dir/src/tracker.cpp.o
/home/user/src/tracker.cpp:42:10: warning: unused variable 'temp' [-Wunused-variable]
[ 30%] Building CXX object CMakeFiles/armor_detector.dir/src/solver.cpp.o
/home/user/src/solver.cpp:100:5: error: 'Eigen::Matrix3d' has no member named 'inversee'
[ 40%] Building CXX object CMakeFiles/armor_detector.dir/src/main.cpp.o
[ 50%] Linking CXX executable armor_detector
"""

    compressed = compactor.compress_build_log(build_log, max_lines=10)

    # 必须保留 error 和 warning
    assert "error:" in compressed
    assert "warning:" in compressed
    assert "已截断" in compressed or "Building" in compressed


def test_message_compactor_file_content():
    """测试文件内容压缩"""
    compactor = MessageCompactor()

    file_content = "\n".join([f"// 第 {i} 行代码" for i in range(200)])
    compressed = compactor.compress_file_content(file_content, max_lines=50)

    lines = compressed.split("\n")

    # 保留前 25 行 + 分隔符 + 后 25 行
    assert len(lines) <= 52
    assert "第 0 行" in compressed
    assert "第 199 行" in compressed
    assert "已截断" in compressed
