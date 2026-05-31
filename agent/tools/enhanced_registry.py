"""
增强工具注册表。

提供工具分类、危险等级管理和执行控制。
"""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ToolCategory(str, Enum):
    """工具分类。"""

    FILE = "file"
    HARDWARE = "hardware"
    NETWORK = "network"
    SYSTEM = "system"
    ANALYSIS = "analysis"
    OTHER = "other"


class DangerLevel(str, Enum):
    """危险等级。"""

    SAFE = "safe"  # 只读操作
    LOW = "low"  # 可逆操作
    MEDIUM = "medium"  # 需确认的写操作
    HIGH = "high"  # 危险操作（删除、格式化等）


class ToolMetadata(BaseModel):
    """工具元数据。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    category: ToolCategory = ToolCategory.OTHER
    danger_level: DangerLevel = DangerLevel.SAFE
    parameters: Dict[str, Any] = Field(default_factory=dict)
    returns: Optional[str] = None


class ToolWrapper:
    """工具包装器。"""

    def __init__(
        self,
        func: Callable,
        metadata: ToolMetadata,
    ):
        self.func = func
        self.metadata = metadata

    def execute(self, **kwargs) -> Any:
        """执行工具。"""
        return self.func(**kwargs)

    def to_openai_schema(self) -> Dict[str, Any]:
        """转换为 OpenAI tool calling 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.metadata.name,
                "description": self.metadata.description,
                "parameters": self.metadata.parameters,
            },
        }


class EnhancedToolRegistry:
    """增强工具注册表。"""

    def __init__(self, danger_confirm: bool = True):
        """
        初始化注册表。

        Args:
            danger_confirm: 危险工具是否需要确认
        """
        self._tools: Dict[str, ToolWrapper] = {}
        self._danger_confirm = danger_confirm

    def register(
        self,
        func: Callable,
        name: str,
        description: str,
        category: ToolCategory = ToolCategory.OTHER,
        danger_level: DangerLevel = DangerLevel.SAFE,
        parameters: Optional[Dict[str, Any]] = None,
        returns: Optional[str] = None,
    ) -> None:
        """
        注册工具。

        Args:
            func: 工具函数
            name: 工具名称
            description: 工具描述
            category: 工具分类
            danger_level: 危险等级
            parameters: 参数 schema（OpenAI 格式）
            returns: 返回值描述
        """
        metadata = ToolMetadata(
            name=name,
            description=description,
            category=category,
            danger_level=danger_level,
            parameters=parameters or {},
            returns=returns,
        )
        self._tools[name] = ToolWrapper(func, metadata)

    def get(self, name: str) -> Optional[ToolWrapper]:
        """获取工具。"""
        return self._tools.get(name)

    def get_by_category(self, category: ToolCategory) -> List[ToolWrapper]:
        """按分类获取工具。"""
        return [
            tool for tool in self._tools.values() if tool.metadata.category == category
        ]

    def list_all(self) -> List[str]:
        """列出所有工具名称。"""
        return list(self._tools.keys())

    def execute(
        self,
        name: str,
        confirm_callback: Optional[Callable[[str, DangerLevel], bool]] = None,
        **kwargs,
    ) -> Any:
        """
        执行工具。

        Args:
            name: 工具名称
            confirm_callback: 危险工具确认回调
            **kwargs: 工具参数

        Returns:
            工具执行结果

        Raises:
            ValueError: 工具不存在
            PermissionError: 用户拒绝执行危险工具
        """
        tool = self.get(name)
        if tool is None:
            raise ValueError(f"工具 '{name}' 不存在")

        # 危险工具需要确认
        if self._danger_confirm and tool.metadata.danger_level in (
            DangerLevel.MEDIUM,
            DangerLevel.HIGH,
        ):
            if confirm_callback is None:
                raise PermissionError(f"工具 '{name}' 需要确认但未提供确认回调")

            if not confirm_callback(name, tool.metadata.danger_level):
                raise PermissionError(f"用户拒绝执行工具 '{name}'")

        return tool.execute(**kwargs)

    def to_openai_tools(self) -> List[Dict[str, Any]]:
        """转换为 OpenAI tools 格式。"""
        return [tool.to_openai_schema() for tool in self._tools.values()]
