"""危险工具审批策略：把是否放行某次工具调用抽象为可注入对象。"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from agent.tools import DangerLevel


@runtime_checkable
class ApprovalPolicy(Protocol):
    """审批策略协议。approve 返回 True 放行、False 拒绝。"""

    def approve(self, tool: str, args: dict, level: DangerLevel) -> bool: ...


class AutoApprove:
    """无条件放行（headless --yes）。"""

    def approve(self, tool: str, args: dict, level: DangerLevel) -> bool:
        return True


class DenyDangerous:
    """放行 SAFE/LOW，拒绝 MEDIUM/HIGH（headless 默认安全策略）。"""

    def approve(self, tool: str, args: dict, level: DangerLevel) -> bool:
        return level not in (DangerLevel.MEDIUM, DangerLevel.HIGH)


class InteractiveApproval:
    """终端交互审批：打印工具与参数，读取 y/N。"""

    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        out: Callable[[str], None] = print,
    ) -> None:
        self._input = input_fn
        self._out = out

    def approve(self, tool: str, args: dict, level: DangerLevel) -> bool:
        self._out(f"工具 {tool} (danger={level.value}) 请求执行，参数: {args}")
        answer = self._input("确认执行? [y/N] ").strip().lower()
        return answer in ("y", "yes")
