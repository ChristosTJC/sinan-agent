"""思维链追踪和管理"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


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
