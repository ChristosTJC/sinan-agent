"""平台支持模块 — 多芯片平台抽象层。"""

from agent.platforms.base import (
    ChipFamily,
    ChipVariant,
    BuildSystem,
    FlashTool,
    PlatformRegistry,
    Architecture,
    get_global_registry,
)

__all__ = [
    "ChipFamily",
    "ChipVariant",
    "BuildSystem",
    "FlashTool",
    "PlatformRegistry",
    "Architecture",
    "get_global_registry",
]
