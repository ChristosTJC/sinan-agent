"""DangerGateHook — 将现有 confirm_callback 迁移为 Hook 实现."""

from typing import Callable, Optional

from agent.orchestration.hooks import Hook, ToolUseContext


class DangerGateHook(Hook):
    """危险工具门控 Hook。

    取代 ToolRegistry 中硬编码的 confirm_callback 逻辑。
    SAFE/LOW 工具直接通过；MEDIUM/HIGH 工具根据 confirm_enabled 和
    confirm_callback 决定是否放行。

    向后兼容：仍支持与旧 confirm_callback 相同的签名
        (tool_name: str, danger_level: str, arguments: dict) -> bool
    """

    def __init__(
        self,
        *,
        confirm_enabled: bool = True,
        confirm_callback: Optional[Callable[[str, str, dict], bool]] = None,
    ):
        self.confirm_enabled = confirm_enabled
        self.confirm_callback = confirm_callback

    def on_pre_tool_use(self, ctx: ToolUseContext) -> ToolUseContext:
        if ctx.danger_level in ("safe", "low"):
            return ctx

        if not self.confirm_enabled:
            return ctx

        if self.confirm_callback is None:
            ctx.approved = False
            ctx.error = (
                f"危险工具 '{ctx.tool_name}' (等级: {ctx.danger_level}) "
                "需要确认，但未设置确认回调"
            )
            return ctx

        ok = self.confirm_callback(ctx.tool_name, ctx.danger_level, ctx.arguments)
        if not ok:
            ctx.approved = False
            ctx.error = (
                f"用户拒绝执行危险工具 '{ctx.tool_name}' "
                f"(等级: {ctx.danger_level})"
            )
        return ctx
