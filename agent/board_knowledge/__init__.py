"""司南嵌入式智能体 — 板级知识库模块

提供板卡配置文件的加载、校验、管理与上下文构建功能。

对外接口:
    BoardKnowledgeBase — 板卡知识库管理类（加载/保存/查询/上下文构建）
    BoardValidator      — 板卡配置文件 JSON Schema 校验器
"""

from .manager import BoardKnowledgeBase
from .validator import BoardValidator

__all__ = [
    "BoardKnowledgeBase",
    "BoardValidator",
]
