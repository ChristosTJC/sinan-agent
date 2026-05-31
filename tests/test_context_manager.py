import pytest
from agent.context.manager import ContextManager


def test_context_manager_no_compression():
    """测试无需压缩的情况"""
    ctx = ContextManager(max_turns=10, max_tokens=10000)

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
    ctx = ContextManager(max_turns=3, max_tokens=10000)

    # 添加系统消息
    ctx.add_message("system", "你是助手")

    # 添加 5 轮对话（超过 max_turns=3）
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
    ctx = ContextManager(max_turns=2, max_tokens=10000)

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
    ctx = ContextManager(max_turns=10, max_tokens=100)

    # 添加长消息
    long_text = "A" * 200  # 约 200 tokens
    ctx.add_message("user", long_text)

    # 估算 token 数
    estimated = ctx.estimate_tokens()

    # 应该接近 200
    assert 150 < estimated < 250


def test_context_manager_clear():
    """测试清空上下文"""
    ctx = ContextManager(max_turns=10, max_tokens=10000)

    ctx.add_message("system", "系统提示")
    ctx.add_message("user", "问题")
    ctx.add_message("assistant", "回答")

    assert len(ctx.get_messages()) == 3

    ctx.clear()

    assert len(ctx.get_messages()) == 0
