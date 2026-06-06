"""
配置管理模块。

提供 legacy 配置加载与 SINAN_HOME 路径管理。
"""

from .legacy import (
    apply_settings,
    create_default_config,
    get_model_config,
    get_sinan_home,
    get_tools_config,
    load_settings,
    SETTINGS_FILE,
    SINAN_HOME,
)

__all__ = [
    "apply_settings",
    "create_default_config",
    "get_model_config",
    "get_sinan_home",
    "get_tools_config",
    "load_settings",
    "SETTINGS_FILE",
    "SINAN_HOME",
]
