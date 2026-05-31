"""UI 组件（任务卡片、进度条等）"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


STATUS_ICONS = {
    TaskStatus.PENDING: "⏳",
    TaskStatus.RUNNING: "⚙️",
    TaskStatus.COMPLETED: "✓",
    TaskStatus.FAILED: "✗",
}


@dataclass
class TaskCard:
    """任务卡片"""
    name: str
    status: TaskStatus
    description: str
    progress: Optional[float] = None
    details: Optional[str] = None

    def render(self, width: int = 50) -> str:
        """渲染任务卡片

        Args:
            width: 卡片宽度

        Returns:
            渲染后的字符串
        """
        icon = STATUS_ICONS[self.status]
        header = f"{icon} {self.name}"

        lines = [
            "┌─ " + header + " " + "─" * (width - len(header) - 4) + "┐",
            f"│ {self.description}" + " " * (width - len(self.description) - 3) + "│",
        ]

        if self.progress is not None and self.status == TaskStatus.RUNNING:
            bar_width = width - 6
            filled = int(bar_width * self.progress)
            bar = "█" * filled + "░" * (bar_width - filled)
            pct = f"{int(self.progress * 100)}%"
            lines.append(f"│ {bar} {pct}" + " " * (width - len(bar) - len(pct) - 4) + "│")

        lines.append("└" + "─" * (width - 2) + "┘")
        return "\n".join(lines)
