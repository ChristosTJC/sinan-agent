"""编排层任务类型定义。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OrchestrationTaskType(str, Enum):
    LOCAL_AGENT = "local_agent"
    HARDWARE_OP = "hardware_op"


class OrchestrationTaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


_TERMINAL_STATUSES = frozenset({
    OrchestrationTaskStatus.COMPLETED,
    OrchestrationTaskStatus.FAILED,
    OrchestrationTaskStatus.KILLED,
})


def is_terminal_status(status: OrchestrationTaskStatus) -> bool:
    return status in _TERMINAL_STATUSES


_TASK_PREFIXES = {
    OrchestrationTaskType.LOCAL_AGENT: "a",
    OrchestrationTaskType.HARDWARE_OP: "h",
}


def generate_task_id(task_type: OrchestrationTaskType) -> str:
    prefix = _TASK_PREFIXES.get(task_type, "x")
    return f"{prefix}{uuid.uuid4().hex[:8]}"


@dataclass
class TaskStateBase:
    id: str
    type: OrchestrationTaskType
    status: OrchestrationTaskStatus
    description: str
    owner: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    output_file: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
