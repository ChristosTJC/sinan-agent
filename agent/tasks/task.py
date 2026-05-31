"""任务实体定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(Enum):
    """任务类型"""
    TOOL_CALL = "tool_call"
    LLM_INFERENCE = "llm_inference"
    THINKING = "thinking"
    COMPOSITE = "composite"


@dataclass
class TaskResult:
    """任务执行结果"""
    success: bool
    output: Any
    error: Optional[str] = None
    compressed: bool = False


@dataclass
class Task:
    """任务实体"""
    id: str
    name: str
    type: TaskType
    status: TaskStatus

    executor: Optional[Callable]
    args: dict

    dependencies: list[str]
    children: list['Task']

    result: Optional[TaskResult]

    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    progress: float

    checkpoint_data: Optional[dict] = None

    def duration(self) -> float:
        """计算任务执行时长（秒）"""
        if self.started_at is None or self.completed_at is None:
            return 0.0
        return (self.completed_at - self.started_at).total_seconds()

    def compress_result(self, max_chars: int = 400) -> str:
        """压缩结果输出（保留头尾各 max_chars/2 字符）"""
        if self.result is None or self.result.output is None:
            return ""

        output_str = str(self.result.output)
        if len(output_str) <= max_chars:
            return output_str

        half = max_chars // 2
        return f"{output_str[:half]}\n... (已截断 {len(output_str) - max_chars} 字符) ...\n{output_str[-half:]}"
