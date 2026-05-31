"""思维链单元测试"""

from agent.context.thinking_chain import ThinkingStep, ThinkingType


def test_thinking_step_creation():
    """测试 ThinkingStep 创建"""
    step = ThinkingStep(
        type=ThinkingType.REASONING,
        content="分析用户需求",
        metadata={"confidence": 0.9}
    )
    assert step.type == ThinkingType.REASONING
    assert step.content == "分析用户需求"
    assert step.metadata["confidence"] == 0.9
    assert step.timestamp is not None
