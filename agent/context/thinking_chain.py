"""思维链追踪和管理"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class ThinkingType(Enum):
    """思维类型"""
    REASONING = "reasoning"
    PLANNING = "planning"
    REFLECTION = "reflection"
    ANALYSIS = "analysis"
    DECISION = "decision"


@dataclass
class ThinkingStep:
    """思维步骤"""
    type: ThinkingType
    content: str
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    parent_id: Optional[str] = None
    step_id: str = field(default_factory=lambda: f"step-{datetime.now().timestamp()}")


@dataclass
class ThinkingNode:
    """思维节点（树状结构）"""
    step: ThinkingStep
    children: List[ThinkingNode] = field(default_factory=list)


class ThinkingChain:
    """思维链管理器"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.steps: List[ThinkingStep] = []
        self.started_at = datetime.now()

    def add_step(
        self,
        type: ThinkingType,
        content: str,
        metadata: Optional[dict] = None,
        parent_id: Optional[str] = None
    ) -> str:
        """添加思维步骤

        Args:
            type: 思维类型
            content: 思维内容
            metadata: 元数据
            parent_id: 父节点 ID

        Returns:
            新步骤的 ID
        """
        step = ThinkingStep(
            type=type,
            content=content,
            metadata=metadata or {},
            parent_id=parent_id
        )
        self.steps.append(step)
        return step.step_id

    def get_tree(self) -> List[ThinkingNode]:
        """构建树状结构

        Returns:
            根节点列表
        """
        nodes = {step.step_id: ThinkingNode(step=step) for step in self.steps}
        roots = []
        for step in self.steps:
            if step.parent_id is None:
                roots.append(nodes[step.step_id])
            else:
                if step.parent_id in nodes:
                    nodes[step.parent_id].children.append(nodes[step.step_id])
        return roots

    def clear(self) -> None:
        """清空思维链"""
        self.steps.clear()
