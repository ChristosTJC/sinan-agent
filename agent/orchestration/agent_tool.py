"""Worker 生命周期管理器。

受控 worker：创建任务 → 过滤工具 → 执行 tool_call 序列 → 收集输出 → 事件通知。
Worker 通过 ToolRegistry.call_tool() 执行，自动继承 P0（路径保护）和 P1（Hook 链）。
"""
from __future__ import annotations

import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from agent.orchestration.task_types import (
    TaskStateBase,
    OrchestrationTaskType,
    OrchestrationTaskStatus,
    generate_task_id,
    is_terminal_status,
)
from agent.orchestration.task_output import TaskOutput
from agent.orchestration.events import (
    ToolStartEvent,
    ToolDoneEvent,
    ToolErrorEvent,
    ApprovalRequiredEvent,
)


@dataclass
class AgentRunConfig:
    agent_type: str = "local_agent"
    description: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    owner: str = "worker"
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentRunResult:
    task_id: str
    success: bool
    results: list[dict[str, Any]]
    duration_ms: float
    error: str = ""


class AgentTool:
    def __init__(self, registry: Any):
        self._registry = registry
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._running: dict[str, Any] = {}

    def run_worker(
        self,
        config: AgentRunConfig,
        tool_calls: list[dict[str, Any]],
        *,
        event_callback: Optional[Callable[[Any], None]] = None,
    ) -> AgentRunResult:
        """同步执行一个 worker 任务。

        Args:
            config: 运行配置（agent_type, allowed_tools, owner）。
            tool_calls: 预定义的 tool_call 序列 [{name, arguments}, ...]。
            event_callback: 可选的事件回调。

        Returns:
            AgentRunResult 包含任务 ID、成功状态、结果列表。
        """
        task_id = generate_task_id(OrchestrationTaskType.LOCAL_AGENT)
        allowed = set(config.allowed_tools)
        results: list[dict[str, Any]] = []
        start = time.time()

        self._running[task_id] = {"status": OrchestrationTaskStatus.IN_PROGRESS, "config": config}

        for tc in tool_calls:
            if task_id not in self._running:
                results.append({"success": False, "error": "任务已被停止", "tool": tc.get("name", "?")})
                break

            name = tc.get("name", "")
            args = tc.get("arguments", {})

            if allowed and name not in allowed:
                results.append({"success": False, "error": f"工具 '{name}' 不在 allowed_tools 中"})
                continue

            danger_level = self._get_danger_level(name)

            if event_callback:
                event_callback(ToolStartEvent(name, danger_level, args))
                if danger_level in ("medium", "high"):
                    event_callback(ApprovalRequiredEvent(name, danger_level, args))

            try:
                result = self._registry.call_tool(name, args)
                results.append(result)
                if event_callback:
                    success = result.get("success", False)
                    duration = (time.time() - start) * 1000
                    event_callback(ToolDoneEvent(
                        name, danger_level, success, duration,
                        "ok" if success else result.get("error", "failed"),
                    ))
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                results.append({"success": False, "error": error, "tool": name})
                if event_callback:
                    event_callback(ToolErrorEvent(name, error))

        duration = (time.time() - start) * 1000
        all_ok = all(r.get("success", False) for r in results)
        self._running.pop(task_id, None)

        return AgentRunResult(
            task_id=task_id,
            success=all_ok,
            results=results,
            duration_ms=duration,
            error="" if all_ok else "部分工具执行失败",
        )

    def stop_worker(self, task_id: str) -> bool:
        if task_id in self._running:
            del self._running[task_id]
            return True
        return False

    def _get_danger_level(self, tool_name: str) -> str:
        if hasattr(self._registry, "get_danger_level"):
            level = self._registry.get_danger_level(tool_name)
            return level.value if hasattr(level, "value") else str(level)
        return "safe"

    def shutdown(self):
        self._running.clear()
        self._executor.shutdown(wait=False)
