"""Hook 协议与 Hook 链 — 在工具调用前后插入可组合的拦截逻辑."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolUseContext:
    """工具调用上下文 — Hook 在 pre/post/error 点消费的数据对象。

    Hook 可以修改此对象来影响工具执行：
    - approved=False 阻止执行
    - error 设置错误消息
    - arguments 修改参数（pre 阶段）
    - result 在 post 阶段可被观察
    """

    tool_name: str
    danger_level: str
    arguments: dict[str, Any]
    approved: bool = True
    error: str = ""
    result: Optional[dict[str, Any]] = None
    duration_ms: float = 0.0


class Hook(ABC):
    """Hook 基类 — 子类覆盖需要的方法即可。

    三个拦截点：
    - on_pre_tool_use: 工具执行前，返回修改后的 ToolUseContext。
      设置 ctx.approved=False 可阻止执行。
    - on_post_tool_use: 工具执行后（无论成功或失败），用于审计/记录。
    - on_tool_error: 仅工具抛异常时调用。
    """

    def on_pre_tool_use(self, ctx: ToolUseContext) -> ToolUseContext:
        return ctx

    def on_post_tool_use(self, ctx: ToolUseContext) -> None:
        pass

    def on_tool_error(self, ctx: ToolUseContext) -> None:
        pass


class HookChain:
    """有序 Hook 链 — 按注册顺序执行所有 Hook。

    用法::

        chain = HookChain([DangerGateHook(), AuditHook()])
        ctx = ToolUseContext("read_file", "safe", {})
        ctx = chain.run_pre_tool_use(ctx)
        if ctx.approved:
            result = execute_tool(ctx)
        chain.run_post_tool_use(ctx)
    """

    def __init__(self, hooks: Optional[list[Hook]] = None):
        self._hooks: list[Hook] = hooks or []

    def add(self, hook: Hook) -> None:
        self._hooks.append(hook)

    def remove(self, hook_class: type) -> None:
        self._hooks = [h for h in self._hooks if not isinstance(h, hook_class)]

    def run_pre_tool_use(self, ctx: ToolUseContext) -> ToolUseContext:
        for hook in self._hooks:
            ctx = hook.on_pre_tool_use(ctx)
            if not ctx.approved:
                break
        return ctx

    def run_post_tool_use(self, ctx: ToolUseContext) -> None:
        for hook in self._hooks:
            hook.on_post_tool_use(ctx)

    def run_tool_error(self, ctx: ToolUseContext) -> None:
        for hook in self._hooks:
            hook.on_tool_error(ctx)

    def __len__(self) -> int:
        return len(self._hooks)

    def has_danger_gate(self) -> bool:
        """HookChain 是否包含 DangerGateHook。"""
        from agent.orchestration.hooks.danger_gate import DangerGateHook
        return any(isinstance(h, DangerGateHook) for h in self._hooks)
