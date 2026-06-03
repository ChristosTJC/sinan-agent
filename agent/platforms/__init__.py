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
from agent.platforms.esp32 import ESP32Platform, detect_esp32_variant
from agent.platforms.nordic import NordicPlatform, detect_nrf_variant
from agent.platforms.stm32 import STM32Platform, detect_stm32_variant

__all__ = [
    "ChipFamily",
    "ChipVariant",
    "BuildSystem",
    "FlashTool",
    "PlatformRegistry",
    "Architecture",
    "get_global_registry",
    "ESP32Platform",
    "STM32Platform",
    "NordicPlatform",
    "detect_esp32_variant",
    "detect_stm32_variant",
    "detect_nrf_variant",
]
