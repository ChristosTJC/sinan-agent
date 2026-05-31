"""平台抽象层 — 定义芯片家族、构建系统、烧录工具的统一接口。

设计目标：
- 支持多芯片平台（STM32、nRF、ESP32、RISC-V）
- 解耦构建系统和烧录工具
- 支持芯片变体自动检测
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum


class Architecture(str, Enum):
    """处理器架构"""
    ARM_CORTEX_M = "ARM Cortex-M"
    ARM_CORTEX_A = "ARM Cortex-A"
    RISC_V = "RISC-V"
    XTENSA = "Xtensa"
    AVR = "AVR"


@dataclass
class ChipFamily:
    """芯片家族定义 — 描述一类芯片的共性。

    示例：
    - STM32（STMicroelectronics，ARM Cortex-M）
    - nRF52（Nordic，ARM Cortex-M4）
    - ESP32（Espressif，Xtensa LX6）
    """
    name: str                           # 家族名称，如 "STM32", "nRF52"
    vendor: str                         # 厂商，如 "STMicroelectronics"
    architecture: str                   # 架构，如 "ARM Cortex-M"
    supported_build_systems: List[str]  # 支持的构建系统，如 ["make", "cmake"]
    supported_flash_tools: List[str]    # 支持的烧录工具，如 ["openocd", "pyocd"]
    default_build_system: Optional[str] = None
    default_flash_tool: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.default_build_system is None and self.supported_build_systems:
            self.default_build_system = self.supported_build_systems[0]
        if self.default_flash_tool is None and self.supported_flash_tools:
            self.default_flash_tool = self.supported_flash_tools[0]


@dataclass
class ChipVariant:
    """芯片变体 — 描述具体型号的规格。

    示例：
    - STM32F405RGT6（STM32 F4 系列，1MB Flash，192KB RAM，168MHz）
    - nRF52840（nRF52 系列，1MB Flash，256KB RAM，64MHz）
    """
    family: str                         # 所属家族，如 "STM32"
    series: str                         # 系列，如 "F4", "52"
    model: str                          # 完整型号，如 "STM32F405RGT6"
    flash_size_kb: int                  # Flash 大小（KB）
    ram_size_kb: int                    # RAM 大小（KB）
    max_freq_mhz: int                   # 最大频率（MHz）
    package: Optional[str] = None       # 封装，如 "LQFP64", "QFN48"
    peripherals: List[str] = field(default_factory=list)  # 外设列表
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_memory_layout(self) -> Dict[str, int]:
        """获取内存布局"""
        return {
            "flash_kb": self.flash_size_kb,
            "ram_kb": self.ram_size_kb,
        }


@dataclass
class BuildSystem:
    """构建系统定义 — 描述如何编译固件。

    示例：
    - Make（检测 Makefile，运行 make）
    - CMake（检测 CMakeLists.txt，运行 cmake + make）
    - PlatformIO（检测 platformio.ini，运行 pio run）
    """
    name: str                           # 构建系统名称，如 "make", "cmake"
    display_name: str                   # 显示名称，如 "GNU Make", "CMake"
    config_files: List[str]             # 配置文件列表，如 ["Makefile"], ["CMakeLists.txt"]
    build_command: str                  # 构建命令模板，如 "make", "cmake --build build"
    clean_command: Optional[str] = None # 清理命令，如 "make clean"

    def detect(self, project_dir: str) -> bool:
        """检测项目是否使用此构建系统"""
        from pathlib import Path
        project_path = Path(project_dir)
        return any((project_path / cfg).exists() for cfg in self.config_files)


@dataclass
class FlashTool:
    """烧录工具定义 — 描述如何烧录固件。

    示例：
    - OpenOCD（支持 STM32、nRF，通过 JTAG/SWD）
    - pyOCD（支持 ARM Cortex-M，通过 CMSIS-DAP）
    - ST-Link（STM32 专用）
    """
    name: str                           # 工具名称，如 "openocd", "pyocd"
    display_name: str                   # 显示名称，如 "OpenOCD", "pyOCD"
    supported_families: List[str]       # 支持的芯片家族
    flash_command_template: str         # 烧录命令模板
    verify_command_template: Optional[str] = None  # 验证命令模板

    def supports_family(self, family: str) -> bool:
        """检查是否支持指定芯片家族"""
        return family in self.supported_families


class PlatformRegistry:
    """平台注册表 — 管理所有已注册的芯片平台。"""

    def __init__(self):
        self._families: Dict[str, ChipFamily] = {}
        self._build_systems: Dict[str, BuildSystem] = {}
        self._flash_tools: Dict[str, FlashTool] = {}

    def register(self, family: ChipFamily) -> None:
        """注册芯片家族"""
        if family.name in self._families:
            raise ValueError(f"芯片家族已注册: {family.name}")
        self._families[family.name] = family

    def register_build_system(self, build_system: BuildSystem) -> None:
        """注册构建系统"""
        if build_system.name in self._build_systems:
            raise ValueError(f"构建系统已注册: {build_system.name}")
        self._build_systems[build_system.name] = build_system

    def register_flash_tool(self, flash_tool: FlashTool) -> None:
        """注册烧录工具"""
        if flash_tool.name in self._flash_tools:
            raise ValueError(f"烧录工具已注册: {flash_tool.name}")
        self._flash_tools[flash_tool.name] = flash_tool

    def get(self, family_name: str) -> Optional[ChipFamily]:
        """获取芯片家族"""
        return self._families.get(family_name)

    def get_build_system(self, name: str) -> Optional[BuildSystem]:
        """获取构建系统"""
        return self._build_systems.get(name)

    def get_flash_tool(self, name: str) -> Optional[FlashTool]:
        """获取烧录工具"""
        return self._flash_tools.get(name)

    def list_families(self) -> List[str]:
        """列出所有芯片家族"""
        return list(self._families.keys())

    def list_build_systems(self) -> List[str]:
        """列出所有构建系统"""
        return list(self._build_systems.keys())

    def list_flash_tools(self) -> List[str]:
        """列出所有烧录工具"""
        return list(self._flash_tools.keys())

    def detect_platform(self, project_dir: str) -> Optional[ChipFamily]:
        """自动检测项目使用的平台（通过构建文件、源码等）"""
        # TODO: 实现自动检测逻辑
        # 1. 检查 CMakeLists.txt 中的 CMAKE_TOOLCHAIN_FILE
        # 2. 检查 Makefile 中的 MCU 定义
        # 3. 扫描源码中的 #include 头文件
        return None


# 全局注册表实例
_global_registry = PlatformRegistry()


def get_global_registry() -> PlatformRegistry:
    """获取全局平台注册表"""
    return _global_registry
