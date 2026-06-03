"""Hook 链测试."""

from dataclasses import asdict


class TestToolUseContext:
    """ToolUseContext 数据类测试."""

    def test_construction(self):
        from agent.orchestration.hooks import ToolUseContext

        ctx = ToolUseContext(
            tool_name="read_file",
            danger_level="safe",
            arguments={"file_path": "/tmp/test.txt"},
        )
        assert ctx.tool_name == "read_file"
        assert ctx.danger_level == "safe"
        assert ctx.arguments == {"file_path": "/tmp/test.txt"}
        assert ctx.result is None
        assert ctx.error == ""
        assert ctx.approved is True  # 默认放行

    def test_serializable(self):
        import json
        from agent.orchestration.hooks import ToolUseContext

        ctx = ToolUseContext(
            tool_name="write_file",
            danger_level="medium",
            arguments={"file_path": "/tmp/out.txt", "content": "hello"},
        )
        d = asdict(ctx)
        assert isinstance(json.dumps(d), str)


class TestHookChainOrdering:
    """Hook 链顺序执行测试."""

    def test_hooks_execute_in_order(self):
        from agent.orchestration.hooks import Hook, HookChain, ToolUseContext

        order: list[str] = []

        class HookA(Hook):
            def on_pre_tool_use(self, ctx: ToolUseContext) -> ToolUseContext:
                order.append("A")
                return ctx

        class HookB(Hook):
            def on_pre_tool_use(self, ctx: ToolUseContext) -> ToolUseContext:
                order.append("B")
                return ctx

        chain = HookChain([HookA(), HookB()])
        ctx = ToolUseContext("test", "safe", {})
        chain.run_pre_tool_use(ctx)
        assert order == ["A", "B"]

    def test_empty_hook_chain_passes_through(self):
        from agent.orchestration.hooks import HookChain, ToolUseContext

        chain = HookChain([])
        ctx = ToolUseContext("test", "safe", {})
        result = chain.run_pre_tool_use(ctx)
        assert result is ctx  # 无修改返回

    def test_post_hooks_execute_in_order(self):
        from agent.orchestration.hooks import Hook, HookChain, ToolUseContext

        order: list[str] = []

        class HookX(Hook):
            def on_post_tool_use(self, ctx: ToolUseContext) -> None:
                order.append("X")

        class HookY(Hook):
            def on_post_tool_use(self, ctx: ToolUseContext) -> None:
                order.append("Y")

        chain = HookChain([HookX(), HookY()])
        ctx = ToolUseContext("test", "safe", {})
        chain.run_post_tool_use(ctx)
        assert order == ["X", "Y"]


class TestHookRejection:
    """Hook 拒绝执行测试."""

    def test_pre_hook_can_approve(self):
        from agent.orchestration.hooks import HookChain, ToolUseContext

        chain = HookChain([])
        ctx = ToolUseContext("test", "safe", {})
        ctx.approved = True
        result = chain.run_pre_tool_use(ctx)
        assert result.approved is True

    def test_pre_hook_can_reject(self):
        from agent.orchestration.hooks import Hook, HookChain, ToolUseContext

        class RejectHook(Hook):
            def on_pre_tool_use(self, ctx: ToolUseContext) -> ToolUseContext:
                ctx.approved = False
                ctx.error = "拒绝执行: 测试原因"
                return ctx

        chain = HookChain([RejectHook()])
        ctx = ToolUseContext("flash_firmware", "high", {})
        result = chain.run_pre_tool_use(ctx)
        assert result.approved is False
        assert "拒绝" in result.error

    def test_error_hook_called(self):
        from agent.orchestration.hooks import Hook, HookChain, ToolUseContext

        called: list[str] = []

        class ErrorHook(Hook):
            def on_tool_error(self, ctx: ToolUseContext) -> None:
                called.append(ctx.tool_name)

        chain = HookChain([ErrorHook()])
        ctx = ToolUseContext("build_firmware", "medium", {})
        ctx.error = "cmake: not found"
        chain.run_tool_error(ctx)
        assert called == ["build_firmware"]


class TestDangerGateHook:
    """DangerGateHook 测试."""

    def test_safe_tool_passes(self):
        from agent.orchestration.hooks.danger_gate import DangerGateHook
        from agent.orchestration.hooks import ToolUseContext

        hook = DangerGateHook(confirm_enabled=True)
        ctx = ToolUseContext("grep", "safe", {})
        result = hook.on_pre_tool_use(ctx)
        assert result.approved is True

    def test_medium_tool_blocked_no_callback(self):
        from agent.orchestration.hooks.danger_gate import DangerGateHook
        from agent.orchestration.hooks import ToolUseContext

        hook = DangerGateHook(confirm_enabled=True)
        ctx = ToolUseContext("build_firmware", "medium", {})
        result = hook.on_pre_tool_use(ctx)
        assert result.approved is False
        assert "确认" in result.error

    def test_high_tool_blocked_no_callback(self):
        from agent.orchestration.hooks.danger_gate import DangerGateHook
        from agent.orchestration.hooks import ToolUseContext

        hook = DangerGateHook(confirm_enabled=True)
        ctx = ToolUseContext("flash_firmware", "high", {})
        result = hook.on_pre_tool_use(ctx)
        assert result.approved is False

    def test_danger_confirm_disabled_passes_all(self):
        from agent.orchestration.hooks.danger_gate import DangerGateHook
        from agent.orchestration.hooks import ToolUseContext

        hook = DangerGateHook(confirm_enabled=False)
        ctx = ToolUseContext("flash_firmware", "high", {})
        result = hook.on_pre_tool_use(ctx)
        assert result.approved is True

    def test_callback_approves(self):
        from agent.orchestration.hooks.danger_gate import DangerGateHook
        from agent.orchestration.hooks import ToolUseContext

        def approve_callback(name: str, level: str, args: dict) -> bool:
            return True

        hook = DangerGateHook(confirm_enabled=True, confirm_callback=approve_callback)
        ctx = ToolUseContext("flash_firmware", "high", {})
        result = hook.on_pre_tool_use(ctx)
        assert result.approved is True

    def test_callback_rejects(self):
        from agent.orchestration.hooks.danger_gate import DangerGateHook
        from agent.orchestration.hooks import ToolUseContext

        def reject_callback(name: str, level: str, args: dict) -> bool:
            return False

        hook = DangerGateHook(confirm_enabled=True, confirm_callback=reject_callback)
        ctx = ToolUseContext("flash_firmware", "high", {})
        result = hook.on_pre_tool_use(ctx)
        assert result.approved is False
        assert "用户拒绝" in result.error
