"""思维链可视化渲染器"""

from __future__ import annotations
from typing import List

from agent.context.thinking_chain import ThinkingChain, ThinkingNode, ThinkingType


THINKING_ICONS = {
    ThinkingType.REASONING: "🧠",
    ThinkingType.PLANNING: "📋",
    ThinkingType.REFLECTION: "🤔",
    ThinkingType.ANALYSIS: "🔍",
    ThinkingType.DECISION: "✅",
}


class ThinkingRenderer:
    """思维链渲染器"""

    def render(self, chain: ThinkingChain, use_rich: bool = True) -> str:
        """渲染思维链为树状结构

        Args:
            chain: 思维链对象
            use_rich: 是否使用 rich 格式（暂未实现）

        Returns:
            渲染后的字符串
        """
        tree = chain.get_tree()
        if not tree:
            return ""

        lines = ["思维链："]
        for i, node in enumerate(tree):
            is_last = (i == len(tree) - 1)
            self._render_node(node, lines, prefix="", is_last=is_last)

        return "\n".join(lines)

    def _render_node(
        self,
        node: ThinkingNode,
        lines: List[str],
        prefix: str,
        is_last: bool
    ) -> None:
        """递归渲染节点

        Args:
            node: 当前节点
            lines: 输出行列表
            prefix: 前缀字符串
            is_last: 是否为最后一个子节点
        """
        icon = THINKING_ICONS.get(node.step.type, "•")
        connector = "└─" if is_last else "├─"

        lines.append(f"{prefix}{connector} {icon} {node.step.type.value}: {node.step.content}")

        child_prefix = prefix + ("   " if is_last else "│  ")
        for i, child in enumerate(node.children):
            child_is_last = (i == len(node.children) - 1)
            self._render_node(child, lines, child_prefix, child_is_last)
