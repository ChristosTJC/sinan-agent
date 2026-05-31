"""
配置管理模块。

提供基于 Pydantic 的配置模型和加载器。
"""

from .models import (
    ContextConfig,
    MemoryConfig,
    ModelConfig,
    SinanSettings,
    TaskConfig,
    ThinkingConfig,
    ToolsConfig,
)
from .loader import ConfigLoader

# 导入旧配置系统的函数（向后兼容）
from .legacy import (
    apply_settings,
    create_default_config,
    get_model_config,
    get_tools_config,
    load_settings,
    SETTINGS_FILE,
    SINAN_HOME,
)

__all__ = [
    "ThinkingConfig",
    "ModelConfig",
    "ToolsConfig",
    "ContextConfig",
    "MemoryConfig",
    "TaskConfig",
    "SinanSettings",
    "ConfigLoader",
    # 旧配置系统
    "apply_settings",
    "create_default_config",
    "get_model_config",
    "get_tools_config",
    "load_settings",
    "SETTINGS_FILE",
    "SINAN_HOME",
]
