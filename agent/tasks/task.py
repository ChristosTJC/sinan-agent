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
    args: dict = field(default_factory=dict)

    dependencies: list[str] = field(default_factory=list)
    children: list['Task'] = field(default_factory=list)

    result: Optional[TaskResult] = None

    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0

    checkpoint_data: Optional[dict] = None

    def duration(self) -> float:
        """计算任务执行时长（秒）"""
        if self.started_at is None or self.completed_at is None:
            return 0.0
        delta = (self.completed_at - self.started_at).total_seconds()
        return max(0.0, delta)  # 保证非负

    def compress_result(self, max_chars: int = 400) -> str:
        """压缩结果输出（保留头尾各 max_chars/2 字符）"""
        if self.result is None or self.result.output is None:
            return ""

        output_str = str(self.result.output)
        if len(output_str) <= max_chars:
            return output_str

        half = max_chars // 2
        kept_chars = half * 2
        truncated_chars = len(output_str) - kept_chars
        compressed = f"{output_str[:half]}\n... (已截断 {truncated_chars} 字符) ...\n{output_str[-half:]}"
        self.result.compressed = True  # 标记压缩状态
        return compressed
