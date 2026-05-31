"""思维链单元测试"""

from agent.context.thinking_chain import ThinkingStep, ThinkingType, ThinkingChain
from agent.repl.thinking_renderer import ThinkingRenderer


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


def test_thinking_chain_add_step():
    """测试 ThinkingChain 添加步骤"""
    chain = ThinkingChain(session_id="test-session")
    step_id = chain.add_step(
        type=ThinkingType.REASONING,
        content="分析问题"
    )
    assert len(chain.steps) == 1
    assert chain.steps[0].step_id == step_id


def test_thinking_chain_get_tree():
    """测试 ThinkingChain 树状结构"""
    chain = ThinkingChain(session_id="test-session")
    root_id = chain.add_step(ThinkingType.REASONING, "根节点")
    child_id = chain.add_step(ThinkingType.PLANNING, "子节点", parent_id=root_id)

    tree = chain.get_tree()
    assert len(tree) == 1
    assert tree[0].step.step_id == root_id
    assert len(tree[0].children) == 1
    assert tree[0].children[0].step.step_id == child_id


def test_thinking_renderer_basic():
    """测试 ThinkingRenderer 基本渲染"""
    chain = ThinkingChain(session_id="test")
    chain.add_step(ThinkingType.REASONING, "分析需求")
    chain.add_step(ThinkingType.DECISION, "决定方案")

    renderer = ThinkingRenderer()
    output = renderer.render(chain)

    assert "🧠 reasoning" in output
    assert "✅ decision" in output
    assert "分析需求" in output
