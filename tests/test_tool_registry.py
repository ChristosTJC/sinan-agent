"""
测试增强工具注册表。
"""

import pytest

from agent.tools.enhanced_registry import (
    DangerLevel,
    EnhancedToolRegistry,
    ToolCategory,
    ToolMetadata,
)


# ---------------------------------------------------------------------------
# 测试工具函数
# ---------------------------------------------------------------------------


def safe_tool(text: str) -> str:
    """安全工具：只读操作。"""
    return f"Read: {text}"


def dangerous_tool(path: str) -> str:
    """危险工具：删除操作。"""
    return f"Deleted: {path}"


# ---------------------------------------------------------------------------
# ToolMetadata
# ---------------------------------------------------------------------------


class TestToolMetadata:
    """测试工具元数据。"""

    def test_metadata_creation(self):
        metadata = ToolMetadata(
            name="test_tool",
            description="测试工具",
            category=ToolCategory.FILE,
            danger_level=DangerLevel.LOW,
        )
        assert metadata.name == "test_tool"
        assert metadata.category == ToolCategory.FILE
        assert metadata.danger_level == DangerLevel.LOW


# ---------------------------------------------------------------------------
# EnhancedToolRegistry
# ---------------------------------------------------------------------------


class TestEnhancedToolRegistry:
    """测试增强工具注册表。"""

    def test_tool_registry_register(self):
        registry = EnhancedToolRegistry()
        registry.register(
            func=safe_tool,
            name="safe_tool",
            description="安全工具",
            category=ToolCategory.FILE,
            danger_level=DangerLevel.SAFE,
        )

        assert "safe_tool" in registry.list_all()
        tool = registry.get("safe_tool")
        assert tool is not None
        assert tool.metadata.name == "safe_tool"

    def test_tool_registry_get_by_category(self):
        registry = EnhancedToolRegistry()
        registry.register(
            func=safe_tool,
            name="file_tool",
            description="文件工具",
            category=ToolCategory.FILE,
        )
        registry.register(
            func=safe_tool,
            name="hardware_tool",
            description="硬件工具",
            category=ToolCategory.HARDWARE,
        )

        file_tools = registry.get_by_category(ToolCategory.FILE)
        assert len(file_tools) == 1
        assert file_tools[0].metadata.name == "file_tool"

        hardware_tools = registry.get_by_category(ToolCategory.HARDWARE)
        assert len(hardware_tools) == 1
        assert hardware_tools[0].metadata.name == "hardware_tool"

    def test_tool_registry_execute_safe(self):
        registry = EnhancedToolRegistry()
        registry.register(
            func=safe_tool,
            name="safe_tool",
            description="安全工具",
            danger_level=DangerLevel.SAFE,
        )

        result = registry.execute("safe_tool", text="test")
        assert result == "Read: test"

    def test_tool_registry_execute_dangerous_with_confirm(self):
        registry = EnhancedToolRegistry(danger_confirm=True)
        registry.register(
            func=dangerous_tool,
            name="dangerous_tool",
            description="危险工具",
            danger_level=DangerLevel.HIGH,
        )

        # 用户确认
        def confirm_yes(name: str, level: DangerLevel) -> bool:
            return True

        result = registry.execute("dangerous_tool", confirm_yes, path="/tmp/test")
        assert result == "Deleted: /tmp/test"

    def test_tool_registry_execute_dangerous_reject(self):
        registry = EnhancedToolRegistry(danger_confirm=True)
        registry.register(
            func=dangerous_tool,
            name="dangerous_tool",
            description="危险工具",
            danger_level=DangerLevel.HIGH,
        )

        # 用户拒绝
        def confirm_no(name: str, level: DangerLevel) -> bool:
            return False

        with pytest.raises(PermissionError, match="用户拒绝执行"):
            registry.execute("dangerous_tool", confirm_no, path="/tmp/test")

    def test_tool_registry_execute_dangerous_no_callback(self):
        registry = EnhancedToolRegistry(danger_confirm=True)
        registry.register(
            func=dangerous_tool,
            name="dangerous_tool",
            description="危险工具",
            danger_level=DangerLevel.MEDIUM,
        )

        with pytest.raises(PermissionError, match="需要确认但未提供确认回调"):
            registry.execute("dangerous_tool", path="/tmp/test")

    def test_tool_registry_execute_nonexistent(self):
        registry = EnhancedToolRegistry()
        with pytest.raises(ValueError, match="不存在"):
            registry.execute("nonexistent_tool")

    def test_tool_registry_to_openai_tools(self):
        registry = EnhancedToolRegistry()
        registry.register(
            func=safe_tool,
            name="test_tool",
            description="测试工具",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "输入文本"}
                },
                "required": ["text"],
            },
        )

        tools = registry.to_openai_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "test_tool"
        assert tools[0]["function"]["description"] == "测试工具"
        assert "parameters" in tools[0]["function"]

    def test_tool_registry_danger_confirm_disabled(self):
        registry = EnhancedToolRegistry(danger_confirm=False)
        registry.register(
            func=dangerous_tool,
            name="dangerous_tool",
            description="危险工具",
            danger_level=DangerLevel.HIGH,
        )

        # 不需要确认，直接执行
        result = registry.execute("dangerous_tool", path="/tmp/test")
        assert result == "Deleted: /tmp/test"
