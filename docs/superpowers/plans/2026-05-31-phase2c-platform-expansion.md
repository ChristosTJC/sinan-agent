# Phase 2C: 横向扩展平台支持 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扩展司南支持 Nordic nRF 系列芯片（nRF52/nRF53）、CMake 构建系统、pyOCD 烧录工具，并扩充知识库，实现真正的多平台嵌入式开发支持。

**Architecture:** 
- **平台抽象层**：定义统一的 ChipFamily、BuildSystem、FlashTool 接口
- **插件式扩展**：Nordic nRF 作为新平台插件，与现有 STM32 平台并行
- **工具链扩展**：CMake 构建器、pyOCD 烧录器作为独立工具注册
- **知识库扩展**：添加 Nordic nRF52840/nRF5340 芯片手册、BLE 协议栈文档

**Tech Stack:** Python 3.10+, pyOCD, OpenOCD, CMake, Nordic nRF SDK, dataclasses, pytest

**设计原则:**
- **零侵入**：新平台不影响现有 STM32 工作流
- **可扩展**：抽象层设计支持未来添加 ESP32、RISC-V 等平台
- **工具解耦**：构建系统、烧录工具独立于芯片平台
- **知识驱动**：智能体通过知识库自动识别芯片型号和工具链

---

## 文件结构

### 新增文件
- `agent/platforms/base.py` - 平台抽象层基础定义（ChipFamily, BuildSystem, FlashTool）
- `agent/platforms/nordic.py` - Nordic nRF 平台支持（nRF52/nRF53 变体检测）
- `agent/platforms/__init__.py` - 平台模块导出
- `agent/tools/cmake_builder.py` - CMake 构建工具（检测 CMakeLists.txt、生成构建命令）
- `agent/tools/pyocd_flasher.py` - pyOCD 烧录工具（目标检测、烧录命令）
- `board_knowledge/nordic/nrf52840.md` - nRF52840 芯片手册（引脚、外设、功耗）
- `board_knowledge/nordic/nrf5340.md` - nRF5340 芯片手册（双核架构、TrustZone）
- `board_knowledge/protocols/ble.md` - BLE 协议栈文档（GAP/GATT/ATT）
- `tests/test_platforms_base.py` - 平台抽象层测试
- `tests/test_platforms_nordic.py` - Nordic 平台测试
- `tests/test_cmake_builder.py` - CMake 构建测试
- `tests/test_pyocd_flasher.py` - pyOCD 烧录测试

### 修改文件
- `agent/tools/__init__.py` - 导出新工具（cmake_builder, pyocd_flasher）
- `config.defaults.yaml` - 添加 Nordic 平台配置
- `README.md` - 更新支持的平台列表

---

## Task 1: 平台抽象层设计

**Files:**
- Create: `agent/platforms/base.py`
- Create: `agent/platforms/__init__.py`
- Create: `tests/test_platforms_base.py`

### Step 1.1: 编写平台抽象层测试

- [ ] **编写 ChipFamily 测试**

```python
# tests/test_platforms_base.py
import pytest
from agent.platforms.base import ChipFamily, ChipVariant, BuildSystem, FlashTool, PlatformRegistry

def test_chip_family_creation():
    """测试芯片家族创建"""
    stm32 = ChipFamily(
        name="STM32",
        vendor="STMicroelectronics",
        architecture="ARM Cortex-M",
        supported_build_systems=["make", "cmake"],
        supported_flash_tools=["openocd", "stlink"]
    )
    
    assert stm32.name == "STM32"
    assert stm32.vendor == "STMicroelectronics"
    assert "make" in stm32.supported_build_systems
    assert "openocd" in stm32.supported_flash_tools

def test_chip_variant_detection():
    """测试芯片变体检测"""
    variant = ChipVariant(
        family="STM32",
        series="F4",
        model="STM32F405RGT6",
        flash_size_kb=1024,
        ram_size_kb=192,
        max_freq_mhz=168
    )
    
    assert variant.family == "STM32"
    assert variant.series == "F4"
    assert variant.flash_size_kb == 1024

def test_platform_registry():
    """测试平台注册表"""
    registry = PlatformRegistry()
    
    stm32 = ChipFamily(
        name="STM32",
        vendor="STMicroelectronics",
        architecture="ARM Cortex-M",
        supported_build_systems=["make"],
        supported_flash_tools=["openocd"]
    )
    
    registry.register(stm32)
    
    assert registry.get("STM32") == stm32
    assert "STM32" in registry.list_families()

def test_platform_registry_duplicate():
    """测试重复注册检测"""
    registry = PlatformRegistry()
    
    stm32 = ChipFamily(
        name="STM32",
        vendor="STMicroelectronics",
        architecture="ARM Cortex-M",
        supported_build_systems=["make"],
        supported_flash_tools=["openocd"]
    )
    
    registry.register(stm32)
    
    with pytest.raises(ValueError, match="已注册"):
        registry.register(stm32)
```

- [ ] **Step 1.2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_platforms_base.py::test_chip_family_creation -v`
Expected: FAIL with "No module named 'agent.platforms.base'"

- [ ] **Step 1.3: 实现平台抽象层基础结构**

```python
# agent/platforms/base.py
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
```

```python
# agent/platforms/__init__.py
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
```

- [ ] **Step 1.4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_platforms_base.py -v`
Expected: PASS (4 tests)

- [ ] **Step 1.5: 提交平台抽象层**

```bash
git add agent/platforms/base.py agent/platforms/__init__.py tests/test_platforms_base.py
git commit -m "feat(platforms): 添加平台抽象层基础结构

- 定义 ChipFamily、ChipVariant、BuildSystem、FlashTool 抽象
- 实现 PlatformRegistry 注册表
- 支持多平台扩展（STM32、nRF、ESP32 等）
- 解耦构建系统和烧录工具
- 添加单元测试

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## Task 2: Nordic nRF 平台支持

**Files:**
- Create: `agent/platforms/nordic.py`
- Create: `tests/test_platforms_nordic.py`

### Step 2.1: 编写 Nordic 平台测试

- [ ] **编写 nRF52 变体检测测试**

```python
# tests/test_platforms_nordic.py
import pytest
from agent.platforms.nordic import (
    NordicPlatform,
    detect_nrf_variant,
    NRF52_VARIANTS,
    NRF53_VARIANTS,
)
from agent.platforms.base import ChipVariant

def test_nordic_platform_registration():
    """测试 Nordic 平台注册"""
    platform = NordicPlatform()
    family = platform.get_chip_family()
    
    assert family.name == "nRF"
    assert family.vendor == "Nordic Semiconductor"
    assert "cmake" in family.supported_build_systems
    assert "pyocd" in family.supported_flash_tools

def test_detect_nrf52840():
    """测试 nRF52840 变体检测"""
    variant = detect_nrf_variant("nRF52840")
    
    assert variant is not None
    assert variant.family == "nRF"
    assert variant.series == "52"
    assert variant.model == "nRF52840"
    assert variant.flash_size_kb == 1024
    assert variant.ram_size_kb == 256

def test_detect_nrf5340():
    """测试 nRF5340 双核变体检测"""
    variant = detect_nrf_variant("nRF5340")
    
    assert variant is not None
    assert variant.family == "nRF"
    assert variant.series == "53"
    assert variant.model == "nRF5340"
    assert variant.flash_size_kb == 1024
    assert variant.ram_size_kb == 512
    assert "dual_core" in variant.metadata

def test_nrf52_variants_list():
    """测试 nRF52 系列变体列表"""
    assert "nRF52832" in NRF52_VARIANTS
    assert "nRF52840" in NRF52_VARIANTS
    
    nrf52832 = NRF52_VARIANTS["nRF52832"]
    assert nrf52832["flash_kb"] == 512
    assert nrf52832["ram_kb"] == 64

def test_nrf53_variants_list():
    """测试 nRF53 系列变体列表"""
    assert "nRF5340" in NRF53_VARIANTS
    
    nrf5340 = NRF53_VARIANTS["nRF5340"]
    assert nrf5340["flash_kb"] == 1024
    assert nrf5340["ram_kb"] == 512
    assert nrf5340["cores"] == 2

def test_detect_unknown_variant():
    """测试未知变体检测"""
    variant = detect_nrf_variant("nRF99999")
    assert variant is None

def test_nordic_build_commands():
    """测试 Nordic 构建命令生成"""
    platform = NordicPlatform()
    
    build_cmd = platform.generate_build_command(
        project_dir="/path/to/project",
        variant="nRF52840"
    )
    
    assert "cmake" in build_cmd
    assert "nRF52840" in build_cmd or "NRF52840" in build_cmd

def test_nordic_flash_commands():
    """测试 Nordic 烧录命令生成"""
    platform = NordicPlatform()
    
    flash_cmd = platform.generate_flash_command(
        firmware_path="/path/to/firmware.hex",
        variant="nRF52840"
    )
    
    assert "pyocd" in flash_cmd or "nrfjprog" in flash_cmd
    assert "nrf52840" in flash_cmd.lower()
```

- [ ] **Step 2.2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_platforms_nordic.py::test_nordic_platform_registration -v`
Expected: FAIL with "No module named 'agent.platforms.nordic'"

- [ ] **Step 2.3: 实现 Nordic 平台支持**

```python
# agent/platforms/nordic.py
"""Nordic nRF 平台支持 — nRF52/nRF53 系列芯片。

支持的芯片系列：
- nRF52 系列：nRF52832, nRF52833, nRF52840（ARM Cortex-M4F）
- nRF53 系列：nRF5340（双核 ARM Cortex-M33）

构建系统：
- CMake（Nordic nRF SDK 默认）
- Segger Embedded Studio

烧录工具：
- pyOCD（开源，支持 CMSIS-DAP）
- nrfjprog（Nordic 官方，需要 nRF Command Line Tools）
- OpenOCD（社区支持）
"""

from __future__ import annotations
from typing import Optional, Dict, Any
from agent.platforms.base import ChipFamily, ChipVariant, BuildSystem, FlashTool


# nRF52 系列变体规格
NRF52_VARIANTS: Dict[str, Dict[str, Any]] = {
    "nRF52810": {
        "flash_kb": 192,
        "ram_kb": 24,
        "max_freq_mhz": 64,
        "package": "QFN48",
        "peripherals": ["BLE5.0", "GPIO", "SPI", "I2C", "UART", "ADC"],
    },
    "nRF52832": {
        "flash_kb": 512,
        "ram_kb": 64,
        "max_freq_mhz": 64,
        "package": "QFN48",
        "peripherals": ["BLE5.0", "NFC", "GPIO", "SPI", "I2C", "UART", "ADC", "PWM"],
    },
    "nRF52833": {
        "flash_kb": 512,
        "ram_kb": 128,
        "max_freq_mhz": 64,
        "package": "QFN48",
        "peripherals": ["BLE5.1", "Thread", "Zigbee", "GPIO", "SPI", "I2C", "UART", "ADC", "USB"],
    },
    "nRF52840": {
        "flash_kb": 1024,
        "ram_kb": 256,
        "max_freq_mhz": 64,
        "package": "QFN73",
        "peripherals": ["BLE5.1", "Thread", "Zigbee", "GPIO", "SPI", "I2C", "UART", "ADC", "USB", "NFC"],
    },
}

# nRF53 系列变体规格
NRF53_VARIANTS: Dict[str, Dict[str, Any]] = {
    "nRF5340": {
        "flash_kb": 1024,
        "ram_kb": 512,
        "max_freq_mhz": 128,  # 应用核 128MHz，网络核 64MHz
        "package": "QFN94",
        "peripherals": ["BLE5.2", "Thread", "Zigbee", "GPIO", "SPI", "I2C", "UART", "ADC", "USB", "NFC"],
        "cores": 2,
        "core_app": "ARM Cortex-M33 @ 128MHz",
        "core_net": "ARM Cortex-M33 @ 64MHz",
        "trustzone": True,
    },
}


def detect_nrf_variant(model: str) -> Optional[ChipVariant]:
    """检测 nRF 芯片变体。
    
    Args:
        model: 芯片型号，如 "nRF52840", "nRF5340"
    
    Returns:
        ChipVariant 对象，如果未知则返回 None
    """
    # 规范化型号名称
    model_normalized = model.replace("-", "").replace("_", "").upper()
    
    # 检查 nRF52 系列
    for variant_name, specs in NRF52_VARIANTS.items():
        if variant_name.upper() in model_normalized:
            return ChipVariant(
                family="nRF",
                series="52",
                model=variant_name,
                flash_size_kb=specs["flash_kb"],
                ram_size_kb=specs["ram_kb"],
                max_freq_mhz=specs["max_freq_mhz"],
                package=specs.get("package"),
                peripherals=specs.get("peripherals", []),
                metadata={"vendor": "Nordic Semiconductor"},
            )
    
    # 检查 nRF53 系列
    for variant_name, specs in NRF53_VARIANTS.items():
        if variant_name.upper() in model_normalized:
            return ChipVariant(
                family="nRF",
                series="53",
                model=variant_name,
                flash_size_kb=specs["flash_kb"],
                ram_size_kb=specs["ram_kb"],
                max_freq_mhz=specs["max_freq_mhz"],
                package=specs.get("package"),
                peripherals=specs.get("peripherals", []),
                metadata={
                    "vendor": "Nordic Semiconductor",
                    "dual_core": True,
                    "cores": specs.get("cores", 1),
                    "core_app": specs.get("core_app"),
                    "core_net": specs.get("core_net"),
                    "trustzone": specs.get("trustzone", False),
                },
            )
    
    return None


class NordicPlatform:
    """Nordic nRF 平台封装。"""
    
    def __init__(self):
        self._chip_family = ChipFamily(
            name="nRF",
            vendor="Nordic Semiconductor",
            architecture="ARM Cortex-M",
            supported_build_systems=["cmake", "segger"],
            supported_flash_tools=["pyocd", "nrfjprog", "openocd"],
            default_build_system="cmake",
            default_flash_tool="pyocd",
            metadata={
                "sdk": "nRF Connect SDK",
                "protocol_stack": "SoftDevice (BLE)",
            },
        )
    
    def get_chip_family(self) -> ChipFamily:
        """获取芯片家族定义"""
        return self._chip_family
    
    def generate_build_command(
        self,
        project_dir: str,
        variant: str,
        build_type: str = "Release",
    ) -> str:
        """生成 CMake 构建命令。
        
        Args:
            project_dir: 项目目录
            variant: 芯片型号，如 "nRF52840"
            build_type: 构建类型，如 "Release", "Debug"
        
        Returns:
            构建命令字符串
        """
        board = self._variant_to_board(variant)
        return (
            f"cmake -B build -S {project_dir} "
            f"-DBOARD={board} "
            f"-DCMAKE_BUILD_TYPE={build_type} && "
            f"cmake --build build"
        )
    
    def generate_flash_command(
        self,
        firmware_path: str,
        variant: str,
        tool: str = "pyocd",
    ) -> str:
        """生成烧录命令。
        
        Args:
            firmware_path: 固件路径（.hex 或 .bin）
            variant: 芯片型号
            tool: 烧录工具，如 "pyocd", "nrfjprog"
        
        Returns:
            烧录命令字符串
        """
        target = self._variant_to_target(variant)
        
        if tool == "pyocd":
            return f"pyocd flash -t {target} {firmware_path}"
        elif tool == "nrfjprog":
            return f"nrfjprog --program {firmware_path} --chiperase --verify --reset"
        elif tool == "openocd":
            return (
                f"openocd -f interface/cmsis-dap.cfg "
                f"-f target/{target}.cfg "
                f"-c 'program {firmware_path} verify reset exit'"
            )
        else:
            raise ValueError(f"不支持的烧录工具: {tool}")
    
    def _variant_to_board(self, variant: str) -> str:
        """将芯片型号转换为 CMake BOARD 参数。
        
        示例：nRF52840 -> nrf52840dk_nrf52840
        """
        variant_lower = variant.lower().replace("-", "").replace("_", "")
        
        if "nrf52840" in variant_lower:
            return "nrf52840dk_nrf52840"
        elif "nrf52833" in variant_lower:
            return "nrf52833dk_nrf52833"
        elif "nrf52832" in variant_lower:
            return "nrf52dk_nrf52832"
        elif "nrf5340" in variant_lower:
            return "nrf5340dk_nrf5340_cpuapp"  # 默认应用核
        else:
            return f"{variant_lower}dk_{variant_lower}"
    
    def _variant_to_target(self, variant: str) -> str:
        """将芯片型号转换为烧录工具目标名称。
        
        示例：nRF52840 -> nrf52840
        """
        return variant.lower().replace("-", "").replace("_", "")


# 注册 Nordic 平台到全局注册表
def register_nordic_platform():
    """注册 Nordic 平台到全局注册表"""
    from agent.platforms.base import get_global_registry
    
    platform = NordicPlatform()
    registry = get_global_registry()
    
    try:
        registry.register(platform.get_chip_family())
    except ValueError:
        # 已注册，跳过
        pass
    
    # 注册 CMake 构建系统（如果未注册）
    try:
        registry.register_build_system(BuildSystem(
            name="cmake",
            display_name="CMake",
            config_files=["CMakeLists.txt"],
            build_command="cmake --build build",
            clean_command="cmake --build build --target clean",
        ))
    except ValueError:
        pass
    
    # 注册 pyOCD 烧录工具（如果未注册）
    try:
        registry.register_flash_tool(FlashTool(
            name="pyocd",
            display_name="pyOCD",
            supported_families=["nRF", "STM32"],
            flash_command_template="pyocd flash -t {target} {firmware}",
            verify_command_template="pyocd verify -t {target} {firmware}",
        ))
    except ValueError:
        pass


# 自动注册
register_nordic_platform()
```

- [ ] **Step 2.4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_platforms_nordic.py -v`
Expected: PASS (8 tests)

- [ ] **Step 2.5: 提交 Nordic 平台支持**

```bash
git add agent/platforms/nordic.py tests/test_platforms_nordic.py
git commit -m "feat(platforms): 添加 Nordic nRF 平台支持

- 支持 nRF52 系列（nRF52810/832/833/840）
- 支持 nRF53 系列（nRF5340 双核）
- 自动检测芯片变体和规格
- 生成 CMake 构建命令
- 生成 pyOCD/nrfjprog 烧录命令
- 自动注册到全局平台注册表
- 添加单元测试

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## Task 3: CMake 构建系统支持

**Files:**
- Create: `agent/tools/cmake_builder.py`
- Create: `tests/test_cmake_builder.py`

### Step 3.1: 编写 CMake 构建器测试

- [ ] **编写 CMake 项目检测测试**

```python
# tests/test_cmake_builder.py
import pytest
import tempfile
from pathlib import Path
from agent.tools.cmake_builder import CMakeBuilder, CMakeProject, detect_cmake_project

def test_detect_cmake_project():
    """测试 CMake 项目检测"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # 创建 CMakeLists.txt
        (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(test_project C)

add_executable(firmware main.c)
""")
        
        project = detect_cmake_project(str(project_dir))
        
        assert project is not None
        assert project.project_dir == project_dir
        assert project.has_cmakelists

def test_detect_non_cmake_project():
    """测试非 CMake 项目检测"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = detect_cmake_project(tmpdir)
        assert project is None

def test_cmake_builder_configure():
    """测试 CMake 配置命令生成"""
    builder = CMakeBuilder()
    
    cmd = builder.generate_configure_command(
        source_dir="/path/to/src",
        build_dir="/path/to/build",
        build_type="Release",
        toolchain_file="/path/to/toolchain.cmake"
    )
    
    assert "cmake" in cmd
    assert "-S /path/to/src" in cmd
    assert "-B /path/to/build" in cmd
    assert "-DCMAKE_BUILD_TYPE=Release" in cmd
    assert "-DCMAKE_TOOLCHAIN_FILE=/path/to/toolchain.cmake" in cmd

def test_cmake_builder_build():
    """测试 CMake 构建命令生成"""
    builder = CMakeBuilder()
    
    cmd = builder.generate_build_command(
        build_dir="/path/to/build",
        target="firmware",
        parallel_jobs=4
    )
    
    assert "cmake --build /path/to/build" in cmd
    assert "--target firmware" in cmd
    assert "-j 4" in cmd or "--parallel 4" in cmd

def test_cmake_builder_clean():
    """测试 CMake 清理命令生成"""
    builder = CMakeBuilder()
    
    cmd = builder.generate_clean_command(build_dir="/path/to/build")
    
    assert "cmake --build /path/to/build" in cmd
    assert "--target clean" in cmd

def test_cmake_project_parse():
    """测试 CMakeLists.txt 解析"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(my_firmware C CXX ASM)

set(MCU_FAMILY STM32F4)
set(MCU_MODEL STM32F405RGT6)

add_executable(firmware.elf
    src/main.c
    src/startup.s
)
""")
        
        project = detect_cmake_project(str(project_dir))
        info = project.parse_project_info()
        
        assert info["project_name"] == "my_firmware"
        assert "C" in info["languages"]
        assert "CXX" in info["languages"]

def test_cmake_builder_with_definitions():
    """测试带自定义定义的 CMake 配置"""
    builder = CMakeBuilder()
    
    cmd = builder.generate_configure_command(
        source_dir="/src",
        build_dir="/build",
        definitions={
            "BOARD": "nrf52840dk",
            "USE_BLE": "ON",
            "LOG_LEVEL": "DEBUG"
        }
    )
    
    assert "-DBOARD=nrf52840dk" in cmd
    assert "-DUSE_BLE=ON" in cmd
    assert "-DLOG_LEVEL=DEBUG" in cmd
```

- [ ] **Step 3.2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_cmake_builder.py::test_detect_cmake_project -v`
Expected: FAIL with "No module named 'agent.tools.cmake_builder'"

- [ ] **Step 3.3: 实现 CMake 构建器**

```python
# agent/tools/cmake_builder.py
"""CMake 构建系统支持 — 检测、配置、构建 CMake 项目。

功能：
- 检测 CMakeLists.txt
- 生成配置命令（cmake -S ... -B ...）
- 生成构建命令（cmake --build ...）
- 解析项目信息（项目名、语言、目标）
- 支持交叉编译工具链
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List, Any
import re


@dataclass
class CMakeProject:
    """CMake 项目描述"""
    project_dir: Path
    has_cmakelists: bool
    build_dir: Optional[Path] = None
    toolchain_file: Optional[Path] = None
    
    def parse_project_info(self) -> Dict[str, Any]:
        """解析 CMakeLists.txt 获取项目信息。
        
        Returns:
            包含 project_name, languages, targets 等信息的字典
        """
        cmakelists = self.project_dir / "CMakeLists.txt"
        if not cmakelists.exists():
            return {}
        
        content = cmakelists.read_text(encoding="utf-8", errors="ignore")
        
        info: Dict[str, Any] = {
            "project_name": None,
            "languages": [],
            "targets": [],
            "variables": {},
        }
        
        # 解析 project() 命令
        project_match = re.search(
            r'project\s*\(\s*(\w+)\s+([^)]*)\)',
            content,
            re.IGNORECASE
        )
        if project_match:
            info["project_name"] = project_match.group(1)
            languages_str = project_match.group(2)
            # 提取语言列表
            for lang in ["C", "CXX", "ASM", "Fortran"]:
                if lang in languages_str:
                    info["languages"].append(lang)
        
        # 解析 add_executable() 和 add_library()
        target_pattern = r'add_(executable|library)\s*\(\s*(\w+)'
        for match in re.finditer(target_pattern, content, re.IGNORECASE):
            target_type = match.group(1)
            target_name = match.group(2)
            info["targets"].append({
                "name": target_name,
                "type": target_type,
            })
        
        # 解析 set() 变量
        set_pattern = r'set\s*\(\s*(\w+)\s+([^)]+)\)'
        for match in re.finditer(set_pattern, content):
            var_name = match.group(1)
            var_value = match.group(2).strip().strip('"')
            info["variables"][var_name] = var_value
        
        return info


def detect_cmake_project(project_dir: str) -> Optional[CMakeProject]:
    """检测目录是否为 CMake 项目。
    
    Args:
        project_dir: 项目目录路径
    
    Returns:
        CMakeProject 对象，如果不是 CMake 项目则返回 None
    """
    project_path = Path(project_dir)
    cmakelists = project_path / "CMakeLists.txt"
    
    if not cmakelists.exists():
        return None
    
    # 检查是否有 build 目录
    build_dir = project_path / "build"
    if not build_dir.exists():
        build_dir = None
    
    # 检查是否有工具链文件
    toolchain_candidates = [
        project_path / "cmake" / "toolchain.cmake",
        project_path / "toolchain.cmake",
    ]
    toolchain_file = None
    for candidate in toolchain_candidates:
        if candidate.exists():
            toolchain_file = candidate
            break
    
    return CMakeProject(
        project_dir=project_path,
        has_cmakelists=True,
        build_dir=build_dir,
        toolchain_file=toolchain_file,
    )


class CMakeBuilder:
    """CMake 构建器 — 生成 CMake 命令。"""
    
    def __init__(self, cmake_executable: str = "cmake"):
        self.cmake_executable = cmake_executable
    
    def generate_configure_command(
        self,
        source_dir: str,
        build_dir: str,
        build_type: str = "Release",
        toolchain_file: Optional[str] = None,
        definitions: Optional[Dict[str, str]] = None,
        generator: Optional[str] = None,
    ) -> str:
        """生成 CMake 配置命令。
        
        Args:
            source_dir: 源码目录（包含 CMakeLists.txt）
            build_dir: 构建目录
            build_type: 构建类型（Release/Debug/RelWithDebInfo/MinSizeRel）
            toolchain_file: 工具链文件路径
            definitions: 自定义 CMake 变量字典
            generator: 生成器（如 "Ninja", "Unix Makefiles"）
        
        Returns:
            CMake 配置命令字符串
        """
        cmd_parts = [self.cmake_executable]
        
        # 源码和构建目录
        cmd_parts.append(f"-S {source_dir}")
        cmd_parts.append(f"-B {build_dir}")
        
        # 构建类型
        cmd_parts.append(f"-DCMAKE_BUILD_TYPE={build_type}")
        
        # 工具链文件
        if toolchain_file:
            cmd_parts.append(f"-DCMAKE_TOOLCHAIN_FILE={toolchain_file}")
        
        # 生成器
        if generator:
            cmd_parts.append(f"-G \"{generator}\"")
        
        # 自定义定义
        if definitions:
            for key, value in definitions.items():
                cmd_parts.append(f"-D{key}={value}")
        
        return " ".join(cmd_parts)
    
    def generate_build_command(
        self,
        build_dir: str,
        target: Optional[str] = None,
        parallel_jobs: Optional[int] = None,
        verbose: bool = False,
    ) -> str:
        """生成 CMake 构建命令。
        
        Args:
            build_dir: 构建目录
            target: 目标名称（如 "firmware"），None 表示构建所有目标
            parallel_jobs: 并行任务数
            verbose: 是否显示详细输出
        
        Returns:
            CMake 构建命令字符串
        """
        cmd_parts = [self.cmake_executable, "--build", build_dir]
        
        if target:
            cmd_parts.extend(["--target", target])
        
        if parallel_jobs:
            cmd_parts.extend(["--parallel", str(parallel_jobs)])
        
        if verbose:
            cmd_parts.append("--verbose")
        
        return " ".join(cmd_parts)
    
    def generate_clean_command(self, build_dir: str) -> str:
        """生成 CMake 清理命令。
        
        Args:
            build_dir: 构建目录
        
        Returns:
            CMake 清理命令字符串
        """
        return f"{self.cmake_executable} --build {build_dir} --target clean"
    
    def generate_install_command(
        self,
        build_dir: str,
        install_prefix: Optional[str] = None,
    ) -> str:
        """生成 CMake 安装命令。
        
        Args:
            build_dir: 构建目录
            install_prefix: 安装前缀（覆盖 CMAKE_INSTALL_PREFIX）
        
        Returns:
            CMake 安装命令字符串
        """
        cmd = f"{self.cmake_executable} --install {build_dir}"
        if install_prefix:
            cmd += f" --prefix {install_prefix}"
        return cmd
    
    def detect_toolchain(self, platform: str) -> Optional[str]:
        """检测平台对应的工具链文件。
        
        Args:
            platform: 平台名称，如 "stm32", "nrf52"
        
        Returns:
            工具链文件路径，如果未找到则返回 None
        """
        # 常见工具链文件位置
        toolchain_paths = [
            f"/usr/share/cmake/toolchains/{platform}.cmake",
            f"~/.local/share/cmake/toolchains/{platform}.cmake",
            f"cmake/{platform}-toolchain.cmake",
        ]
        
        for path_str in toolchain_paths:
            path = Path(path_str).expanduser()
            if path.exists():
                return str(path)
        
        return None


# 工具注册
def register_cmake_tool():
    """注册 CMake 构建工具到工具注册表"""
    from agent.tools import ToolRegistry
    
    registry = ToolRegistry()
    
    def cmake_build(project_dir: str, build_type: str = "Release", **kwargs):
        """CMake 构建工具函数"""
        project = detect_cmake_project(project_dir)
        if not project:
            return {"success": False, "error": "未找到 CMakeLists.txt"}
        
        builder = CMakeBuilder()
        build_dir = str(project.project_dir / "build")
        
        # 配置
        configure_cmd = builder.generate_configure_command(
            source_dir=str(project.project_dir),
            build_dir=build_dir,
            build_type=build_type,
            toolchain_file=str(project.toolchain_file) if project.toolchain_file else None,
        )
        
        # 构建
        build_cmd = builder.generate_build_command(build_dir=build_dir)
        
        return {
            "success": True,
            "configure_command": configure_cmd,
            "build_command": build_cmd,
            "full_command": f"{configure_cmd} && {build_cmd}",
        }
    
    registry.register(
        name="cmake_build",
        func=cmake_build,
        description="使用 CMake 构建嵌入式项目",
        parameters={
            "project_dir": {"type": "string", "description": "项目目录路径"},
            "build_type": {"type": "string", "description": "构建类型（Release/Debug）", "default": "Release"},
        }
    )
```

- [ ] **Step 3.4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_cmake_builder.py -v`
Expected: PASS (7 tests)

- [ ] **Step 3.5: 提交 CMake 构建支持**

```bash
git add agent/tools/cmake_builder.py tests/test_cmake_builder.py
git commit -m "feat(tools): 添加 CMake 构建系统支持

- 检测 CMakeLists.txt 项目
- 生成配置命令（支持工具链、自定义变量）
- 生成构建命令（支持并行、目标选择）
- 解析项目信息（项目名、语言、目标）
- 自动检测工具链文件
- 注册到工具注册表
- 添加单元测试

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## Task 4: pyOCD 烧录工具集成

**Files:**
- Create: `agent/tools/pyocd_flasher.py`
- Create: `tests/test_pyocd_flasher.py`

### Step 4.1: 编写 pyOCD 烧录器测试

- [ ] **编写 pyOCD 目标检测测试**

```python
# tests/test_pyocd_flasher.py
import pytest
from unittest.mock import patch, MagicMock
from agent.tools.pyocd_flasher import (
    PyOCDFlasher,
    list_connected_targets,
    detect_target_from_chip,
    SUPPORTED_TARGETS,
)

def test_pyocd_flasher_init():
    """测试 pyOCD 烧录器初始化"""
    flasher = PyOCDFlasher()
    assert flasher.executable == "pyocd"

def test_supported_targets():
    """测试支持的目标列表"""
    assert "nrf52840" in SUPPORTED_TARGETS
    assert "nrf5340" in SUPPORTED_TARGETS
    assert "stm32f405rg" in SUPPORTED_TARGETS

def test_detect_target_from_chip():
    """测试从芯片型号检测 pyOCD 目标"""
    assert detect_target_from_chip("nRF52840") == "nrf52840"
    assert detect_target_from_chip("nRF5340") == "nrf5340"
    assert detect_target_from_chip("STM32F405RGT6") == "stm32f405rg"
    assert detect_target_from_chip("STM32F407VGT6") == "stm32f407vg"

def test_detect_unknown_chip():
    """测试未知芯片检测"""
    result = detect_target_from_chip("UNKNOWN_CHIP_9999")
    assert result is None

@patch("subprocess.run")
def test_list_connected_targets(mock_run):
    """测试列出已连接的目标"""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="0 => nRF52840 [nrf52840]\n1 => STM32F405RG [stm32f405rg]\n"
    )
    
    targets = list_connected_targets()
    
    assert len(targets) == 2
    assert targets[0]["name"] == "nRF52840"
    assert targets[0]["target"] == "nrf52840"
    assert targets[1]["name"] == "STM32F405RG"

def test_generate_flash_command():
    """测试生成烧录命令"""
    flasher = PyOCDFlasher()
    
    cmd = flasher.generate_flash_command(
        firmware_path="/path/to/firmware.hex",
        target="nrf52840"
    )
    
    assert "pyocd flash" in cmd
    assert "-t nrf52840" in cmd
    assert "/path/to/firmware.hex" in cmd

def test_generate_erase_command():
    """测试生成擦除命令"""
    flasher = PyOCDFlasher()
    
    cmd = flasher.generate_erase_command(target="nrf52840")
    
    assert "pyocd erase" in cmd
    assert "-t nrf52840" in cmd
    assert "--chip" in cmd

def test_generate_reset_command():
    """测试生成复位命令"""
    flasher = PyOCDFlasher()
    
    cmd = flasher.generate_reset_command(target="nrf52840")
    
    assert "pyocd reset" in cmd
    assert "-t nrf52840" in cmd

def test_generate_flash_command_with_options():
    """测试带选项的烧录命令"""
    flasher = PyOCDFlasher()
    
    cmd = flasher.generate_flash_command(
        firmware_path="/path/to/firmware.bin",
        target="nrf52840",
        base_address=0x00000000,
        erase_mode="chip",
        verify=True
    )
    
    assert "--base-address 0x00000000" in cmd or "--base 0x00000000" in cmd
    assert "--erase chip" in cmd
    # pyOCD 默认验证，无需额外参数

def test_flash_multiple_files():
    """测试烧录多个文件"""
    flasher = PyOCDFlasher()
    
    files = [
        ("/path/to/bootloader.hex", 0x00000000),
        ("/path/to/app.hex", 0x00010000),
    ]
    
    commands = flasher.generate_multi_flash_commands(
        files=files,
        target="nrf52840"
    )
    
    assert len(commands) == 2
    assert "bootloader.hex" in commands[0]
    assert "app.hex" in commands[1]
```

- [ ] **Step 4.2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_pyocd_flasher.py::test_pyocd_flasher_init -v`
Expected: FAIL with "No module named 'agent.tools.pyocd_flasher'"

- [ ] **Step 4.3: 实现 pyOCD 烧录器**

```python
# agent/tools/pyocd_flasher.py
"""pyOCD 烧录工具集成 — 支持 ARM Cortex-M 芯片烧录。

pyOCD 是开源的 ARM Cortex-M 调试和烧录工具，支持：
- CMSIS-DAP 调试器
- nRF52/nRF53 系列
- STM32 系列
- 其他 ARM Cortex-M 芯片

安装：pip install pyocd
文档：https://pyocd.io/
"""

from __future__ import annotations
from typing import Optional, List, Dict, Tuple
import subprocess
import re


# pyOCD 支持的目标列表（常用芯片）
SUPPORTED_TARGETS = {
    # Nordic nRF52 系列
    "nrf52810": "nRF52810",
    "nrf52832": "nRF52832",
    "nrf52833": "nRF52833",
    "nrf52840": "nRF52840",
    
    # Nordic nRF53 系列
    "nrf5340": "nRF5340",
    
    # STM32 F4 系列
    "stm32f401re": "STM32F401RE",
    "stm32f405rg": "STM32F405RG",
    "stm32f407vg": "STM32F407VG",
    "stm32f411re": "STM32F411RE",
    "stm32f429zi": "STM32F429ZI",
    
    # STM32 F7 系列
    "stm32f746zg": "STM32F746ZG",
    "stm32f767zi": "STM32F767ZI",
    
    # STM32 H7 系列
    "stm32h743zi": "STM32H743ZI",
    "stm32h750vb": "STM32H750VB",
}


def detect_target_from_chip(chip_model: str) -> Optional[str]:
    """从芯片型号检测 pyOCD 目标名称。
    
    Args:
        chip_model: 芯片型号，如 "nRF52840", "STM32F405RGT6"
    
    Returns:
        pyOCD 目标名称，如 "nrf52840", "stm32f405rg"
        如果未知则返回 None
    """
    # 规范化：去除连字符、下划线，转小写
    normalized = chip_model.lower().replace("-", "").replace("_", "")
    
    # 直接匹配
    if normalized in SUPPORTED_TARGETS:
        return normalized
    
    # 模糊匹配（去除封装后缀）
    for target_key in SUPPORTED_TARGETS.keys():
        if target_key in normalized:
            return target_key
    
    # STM32 特殊处理：STM32F405RGT6 -> stm32f405rg
    if normalized.startswith("stm32"):
        # 提取系列和型号前缀
        match = re.match(r'(stm32[a-z]\d{2,3}[a-z]{0,2})', normalized)
        if match:
            prefix = match.group(1)
            if prefix in SUPPORTED_TARGETS:
                return prefix
    
    return None


def list_connected_targets() -> List[Dict[str, str]]:
    """列出已连接的调试器和目标。
    
    Returns:
        目标列表，每个元素包含 index, name, target
    """
    try:
        result = subprocess.run(
            ["pyocd", "list"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return []
        
        targets = []
        # 解析输出：0 => nRF52840 [nrf52840]
        for line in result.stdout.splitlines():
            match = re.match(r'(\d+)\s*=>\s*([^\[]+)\s*\[([^\]]+)\]', line)
            if match:
                targets.append({
                    "index": int(match.group(1)),
                    "name": match.group(2).strip(),
                    "target": match.group(3).strip(),
                })
        
        return targets
    
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


class PyOCDFlasher:
    """pyOCD 烧录器 — 生成 pyOCD 烧录命令。"""
    
    def __init__(self, executable: str = "pyocd"):
        self.executable = executable
    
    def generate_flash_command(
        self,
        firmware_path: str,
        target: str,
        base_address: Optional[int] = None,
        erase_mode: str = "sector",
        verify: bool = True,
        frequency: Optional[int] = None,
    ) -> str:
        """生成烧录命令。
        
        Args:
            firmware_path: 固件文件路径（.hex, .bin, .elf）
            target: pyOCD 目标名称，如 "nrf52840"
            base_address: 基地址（仅 .bin 文件需要）
            erase_mode: 擦除模式（"sector", "chip", "auto"）
            verify: 是否验证（pyOCD 默认验证）
            frequency: SWD 频率（Hz），如 1000000 表示 1MHz
        
        Returns:
            pyOCD 烧录命令字符串
        """
        cmd_parts = [self.executable, "flash"]
        
        # 目标
        cmd_parts.extend(["-t", target])
        
        # 频率
        if frequency:
            cmd_parts.extend(["-f", str(frequency)])
        
        # 擦除模式
        if erase_mode != "auto":
            cmd_parts.extend(["--erase", erase_mode])
        
        # 基地址（.bin 文件）
        if base_address is not None:
            cmd_parts.extend(["--base-address", hex(base_address)])
        
        # 固件文件
        cmd_parts.append(firmware_path)
        
        return " ".join(cmd_parts)
    
    def generate_erase_command(
        self,
        target: str,
        erase_mode: str = "chip",
    ) -> str:
        """生成擦除命令。
        
        Args:
            target: pyOCD 目标名称
            erase_mode: 擦除模式（"chip", "sector"）
        
        Returns:
            pyOCD 擦除命令字符串
        """
        return f"{self.executable} erase -t {target} --chip"
    
    def generate_reset_command(
        self,
        target: str,
        reset_type: str = "hw",
    ) -> str:
        """生成复位命令。
        
        Args:
            target: pyOCD 目标名称
            reset_type: 复位类型（"hw", "sw"）
        
        Returns:
            pyOCD 复位命令字符串
        """
        return f"{self.executable} reset -t {target}"
    
    def generate_multi_flash_commands(
        self,
        files: List[Tuple[str, int]],
        target: str,
    ) -> List[str]:
        """生成多文件烧录命令列表。
        
        Args:
            files: 文件列表，每个元素为 (文件路径, 基地址)
            target: pyOCD 目标名称
        
        Returns:
            命令列表
        """
        commands = []
        for firmware_path, base_address in files:
            cmd = self.generate_flash_command(
                firmware_path=firmware_path,
                target=target,
                base_address=base_address,
                erase_mode="sector",  # 多文件烧录使用扇区擦除
            )
            commands.append(cmd)
        return commands
    
    def check_availability(self) -> bool:
        """检查 pyOCD 是否可用。
        
        Returns:
            True 如果 pyOCD 已安装且可执行
        """
        try:
            result = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False


# 工具注册
def register_pyocd_tool():
    """注册 pyOCD 烧录工具到工具注册表"""
    from agent.tools import ToolRegistry
    
    registry = ToolRegistry()
    
    def pyocd_flash(firmware_path: str, chip_model: str, **kwargs):
        """pyOCD 烧录工具函数"""
        flasher = PyOCDFlasher()
        
        # 检查可用性
        if not flasher.check_availability():
            return {
                "success": False,
                "error": "pyOCD 未安装或不可用，请运行: pip install pyocd"
            }
        
        # 检测目标
        target = detect_target_from_chip(chip_model)
        if not target:
            return {
                "success": False,
                "error": f"不支持的芯片型号: {chip_model}",
                "supported": list(SUPPORTED_TARGETS.values())
            }
        
        # 生成烧录命令
        cmd = flasher.generate_flash_command(
            firmware_path=firmware_path,
            target=target,
            **kwargs
        )
        
        return {
            "success": True,
            "target": target,
            "command": cmd,
        }
    
    registry.register(
        name="pyocd_flash",
        func=pyocd_flash,
        description="使用 pyOCD 烧录 ARM Cortex-M 芯片",
        parameters={
            "firmware_path": {"type": "string", "description": "固件文件路径"},
            "chip_model": {"type": "string", "description": "芯片型号（如 nRF52840, STM32F405RGT6）"},
            "base_address": {"type": "integer", "description": "基地址（可选，仅 .bin 文件）"},
            "erase_mode": {"type": "string", "description": "擦除模式（sector/chip/auto）", "default": "sector"},
        }
    )
```

- [ ] **Step 4.4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_pyocd_flasher.py -v`
Expected: PASS (9 tests)

- [ ] **Step 4.5: 提交 pyOCD 烧录支持**

```bash
git add agent/tools/pyocd_flasher.py tests/test_pyocd_flasher.py
git commit -m "feat(tools): 添加 pyOCD 烧录工具集成

- 支持 nRF52/nRF53/STM32 系列芯片
- 自动检测芯片型号到 pyOCD 目标映射
- 生成烧录、擦除、复位命令
- 支持多文件烧录
- 列出已连接的调试器
- 检查 pyOCD 可用性
- 注册到工具注册表
- 添加单元测试

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## Task 5: 知识库扩展 - Nordic 平台

**Files:**
- Create: `board_knowledge/nordic/nrf52840.md`
- Create: `board_knowledge/nordic/nrf5340.md`
- Create: `board_knowledge/protocols/ble.md`

### Step 5.1: 创建 nRF52840 芯片手册

- [ ] **编写 nRF52840 知识库文档**

```markdown
# board_knowledge/nordic/nrf52840.md
# nRF52840 芯片手册

## 基本信息

- **厂商**: Nordic Semiconductor
- **系列**: nRF52 系列
- **架构**: ARM Cortex-M4F（带 FPU）
- **主频**: 64 MHz
- **Flash**: 1 MB
- **RAM**: 256 KB
- **封装**: QFN73 (7x7mm)

## 核心特性

### 处理器
- ARM Cortex-M4 32-bit processor with FPU
- 64 MHz maximum CPU clock
- 1.7-5.5V supply voltage range
- -40°C to +85°C operating temperature

### 内存
- 1 MB Flash memory
- 256 KB RAM
- 支持外部 QSPI Flash（最大 256 MB）

### 无线协议
- **Bluetooth 5.1**: 支持 LE 2M PHY, LE Coded PHY, Advertising Extensions
- **Thread**: 基于 IEEE 802.15.4 的 IPv6 网状网络
- **Zigbee**: 支持 Zigbee 3.0
- **ANT**: 2.4 GHz 专有协议
- **2.4 GHz 专有协议**: 自定义无线协议

### 射频性能
- TX 功率: +8 dBm (最大)
- RX 灵敏度: -95 dBm (BLE 1M PHY)
- 链路预算: 103 dB

## 外设资源

### 通信接口
- **UART**: 2 个（支持硬件流控）
- **SPI**: 4 个（SPI Master/Slave）
- **I2C**: 2 个（TWI Master/Slave）
- **USB 2.0**: 全速设备（12 Mbps）
- **QSPI**: 1 个（用于外部 Flash）
- **NFC-A**: Tag 模式

### GPIO
- 48 个 GPIO 引脚
- 支持中断、上拉/下拉
- 最大输出电流: 15 mA per pin

### 定时器
- **TIMER**: 5 个 32-bit 定时器
- **RTC**: 3 个实时计数器
- **PWM**: 4 个 PWM 模块（每个 4 通道）

### 模拟外设
- **ADC**: 12-bit, 8 通道, 200 ksps
- **COMP**: 1 个模拟比较器
- **TEMP**: 片上温度传感器

### 其他外设
- **WDT**: 看门狗定时器
- **RNG**: 硬件随机数生成器
- **AES**: 硬件 AES-128 加密
- **ECC**: 硬件椭圆曲线加密（用于 BLE）

## 引脚定义

### 电源引脚
- VDD: 1.7-5.5V 主电源
- VDDH: 高压电源（用于 GPIO 高驱动）
- DECRF: 射频去耦
- DEC1-DEC4: 内部稳压器去耦

### 射频引脚
- ANT: 天线接口（需要匹配网络）

### 调试接口
- SWDIO: SWD 数据
- SWDCLK: SWD 时钟

### USB 引脚
- D+: USB 数据正
- D-: USB 数据负

## 开发板

### nRF52840 DK (PCA10056)
- 官方开发板
- 板载 Segger J-Link 调试器
- 4 个 LED, 4 个按钮
- Arduino 兼容接口
- NFC 天线接口

### nRF52840 Dongle (PCA10059)
- USB Dongle 形态
- 板载 RGB LED
- 用于无线 Sniffer 和开发

## 软件开发

### SDK
- **nRF Connect SDK**: 基于 Zephyr RTOS（推荐）
- **nRF5 SDK**: 传统 SDK（维护模式）

### 构建系统
- CMake（nRF Connect SDK）
- Makefile（nRF5 SDK）
- Segger Embedded Studio

### 烧录工具
- nrfjprog（Nordic 官方）
- pyOCD（开源）
- OpenOCD（社区支持）

### 调试器
- Segger J-Link
- CMSIS-DAP

## 功耗特性

### 电流消耗
- TX @ 0 dBm: 4.8 mA
- RX @ 1 Mbps: 4.6 mA
- System ON idle: 1.5 µA
- System OFF: 0.4 µA

### 低功耗模式
- Constant latency mode
- Low power mode
- System OFF mode

## 应用场景

- 智能家居（Thread/Zigbee 网关）
- 可穿戴设备（BLE 心率监测）
- 无线音频（BLE Audio）
- USB Dongle（无线适配器）
- 资产跟踪（BLE + GPS）

## 参考资料

- [nRF52840 Product Specification](https://infocenter.nordicsemi.com/pdf/nRF52840_PS_v1.7.pdf)
- [nRF52840 DK User Guide](https://infocenter.nordicsemi.com/pdf/nRF52840_DK_User_Guide_v1.4.2.pdf)
- [nRF Connect SDK Documentation](https://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/index.html)
```

- [ ] **Step 5.2: 创建 nRF5340 芯片手册**

```markdown
# board_knowledge/nordic/nrf5340.md
# nRF5340 芯片手册

## 基本信息

- **厂商**: Nordic Semiconductor
- **系列**: nRF53 系列
- **架构**: 双核 ARM Cortex-M33（应用核 + 网络核）
- **主频**: 应用核 128 MHz, 网络核 64 MHz
- **Flash**: 1 MB（应用核）+ 256 KB（网络核）
- **RAM**: 512 KB（应用核）+ 64 KB（网络核）
- **封装**: QFN94 (10x10mm)

## 核心特性

### 双核架构
- **应用核**: ARM Cortex-M33 @ 128 MHz（带 FPU 和 DSP）
- **网络核**: ARM Cortex-M33 @ 64 MHz（专用无线协议栈）
- **核间通信**: IPC（Inter-Processor Communication）

### 处理器
- ARM Cortex-M33 with TrustZone
- 128 MHz (应用核) / 64 MHz (网络核)
- 1.7-5.5V supply voltage range
- -40°C to +105°C operating temperature

### 内存
- **应用核**: 1 MB Flash + 512 KB RAM
- **网络核**: 256 KB Flash + 64 KB RAM
- 支持外部 QSPI Flash（最大 256 MB）

### 安全特性
- **ARM TrustZone**: 硬件隔离安全区和非安全区
- **Secure Boot**: 安全启动
- **Root of Trust**: 硬件信任根
- **Crypto**: AES-128/256, SHA-256, ECC P-256

### 无线协议
- **Bluetooth 5.2**: LE Audio, Direction Finding
- **Thread**: IEEE 802.15.4 网状网络
- **Zigbee**: Zigbee 3.0
- **ANT**: 2.4 GHz 专有协议
- **2.4 GHz 专有协议**: 自定义无线协议

### 射频性能
- TX 功率: +3 dBm (典型), +8 dBm (最大)
- RX 灵敏度: -97 dBm (BLE 1M PHY)
- 链路预算: 105 dB

## 外设资源（应用核）

### 通信接口
- **UART**: 4 个（支持硬件流控）
- **SPI**: 5 个（SPI Master/Slave）
- **I2C**: 4 个（TWI Master/Slave）
- **USB 2.0**: 全速设备（12 Mbps）
- **QSPI**: 1 个（用于外部 Flash）
- **NFC-A**: Tag 模式

### GPIO
- 48 个 GPIO 引脚（应用核）
- 支持中断、上拉/下拉
- 最大输出电流: 15 mA per pin

### 定时器
- **TIMER**: 3 个 32-bit 定时器
- **RTC**: 2 个实时计数器
- **PWM**: 4 个 PWM 模块（每个 4 通道）

### 模拟外设
- **ADC**: 12-bit, 8 通道, 200 ksps
- **COMP**: 1 个模拟比较器
- **LPCOMP**: 低功耗比较器
- **TEMP**: 片上温度传感器

### 其他外设
- **WDT**: 2 个看门狗定时器
- **RNG**: 硬件随机数生成器
- **PDM**: 脉冲密度调制（用于数字麦克风）
- **I2S**: 音频接口

## 核间通信（IPC）

### IPC 机制
- 共享内存（Shared RAM）
- 中断触发（IPC 事件）
- 信号量（Mutex）

### 典型用法
- 应用核处理应用逻辑
- 网络核运行 BLE 协议栈
- 通过 IPC 传递数据和命令

## 引脚定义

### 电源引脚
- VDD: 1.7-5.5V 主电源
- VDDH: 高压电源（用于 GPIO 高驱动）
- DECRF: 射频去耦
- DEC1-DEC6: 内部稳压器去耦

### 射频引脚
- ANT: 天线接口（需要匹配网络）

### 调试接口
- **应用核**: SWDIO_APP, SWDCLK_APP
- **网络核**: SWDIO_NET, SWDCLK_NET

### USB 引脚
- D+: USB 数据正
- D-: USB 数据负

## 开发板

### nRF5340 DK (PCA10095)
- 官方开发板
- 板载 Segger J-Link 调试器（支持双核调试）
- 4 个 LED, 4 个按钮
- Arduino 兼容接口
- NFC 天线接口

## 软件开发

### SDK
- **nRF Connect SDK**: 基于 Zephyr RTOS（推荐）
- 支持双核开发和 TrustZone

### 构建系统
- CMake（nRF Connect SDK）
- 支持多镜像构建（应用核 + 网络核）

### 烧录工具
- nrfjprog（Nordic 官方，支持双核）
- pyOCD（开源）
- OpenOCD（社区支持）

### 调试器
- Segger J-Link（支持双核调试）
- CMSIS-DAP

## 功耗特性

### 电流消耗
- TX @ 0 dBm: 3.6 mA
- RX @ 1 Mbps: 3.4 mA
- System ON idle: 2.0 µA
- System OFF: 0.5 µA

### 低功耗模式
- Constant latency mode
- Low power mode
- System OFF mode

## 应用场景

- 高性能智能家居网关（Thread + BLE）
- 工业物联网（安全通信）
- 医疗设备（TrustZone 安全）
- 音频设备（BLE Audio + I2S）
- 可穿戴设备（双核低功耗）

## 参考资料

- [nRF5340 Product Specification](https://infocenter.nordicsemi.com/pdf/nRF5340_PS_v1.3.pdf)
- [nRF5340 DK User Guide](https://infocenter.nordicsemi.com/pdf/nRF5340_DK_User_Guide_v1.4.1.pdf)
- [nRF Connect SDK Documentation](https://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/index.html)
```

- [ ] **Step 5.3: 创建 BLE 协议栈文档**

```markdown
# board_knowledge/protocols/ble.md
# Bluetooth Low Energy (BLE) 协议栈

## 概述

Bluetooth Low Energy（BLE，蓝牙低功耗）是 Bluetooth 4.0 引入的低功耗无线通信协议，专为物联网设备设计。

## 协议栈架构

```
┌─────────────────────────────────┐
│      应用层 (Application)        │
├─────────────────────────────────┤
│      GAP (通用访问配置文件)      │
│      GATT (通用属性配置文件)     │
├─────────────────────────────────┤
│      ATT (属性协议)              │
│      SMP (安全管理协议)          │
├─────────────────────────────────┤
│      L2CAP (逻辑链路控制)        │
├─────────────────────────────────┤
│      HCI (主机控制接口)          │
├─────────────────────────────────┤
│      Link Layer (链路层)         │
├─────────────────────────────────┤
│      Physical Layer (物理层)     │
└─────────────────────────────────┘
```

## GAP (Generic Access Profile)

### 角色
- **Central**: 中心设备（扫描、连接）
- **Peripheral**: 外设（广播、被连接）
- **Broadcaster**: 广播者（仅广播）
- **Observer**: 观察者（仅扫描）

### 广播类型
- **ADV_IND**: 可连接、可扫描
- **ADV_DIRECT_IND**: 定向广播
- **ADV_NONCONN_IND**: 不可连接
- **ADV_SCAN_IND**: 可扫描、不可连接

### 连接参数
- **Connection Interval**: 7.5ms - 4s
- **Slave Latency**: 0 - 499
- **Supervision Timeout**: 100ms - 32s

## GATT (Generic Attribute Profile)

### 层次结构
```
Profile
  └─ Service (服务)
       └─ Characteristic (特征)
            ├─ Value (值)
            └─ Descriptor (描述符)
```

### 特征属性
- **Read**: 可读
- **Write**: 可写（需要响应）
- **Write Without Response**: 可写（无需响应）
- **Notify**: 通知（无需确认）
- **Indicate**: 指示（需要确认）

### 标准服务
- **0x1800**: Generic Access
- **0x1801**: Generic Attribute
- **0x180A**: Device Information
- **0x180D**: Heart Rate
- **0x180F**: Battery Service

## ATT (Attribute Protocol)

### 操作类型
- **Read**: 读取属性
- **Write**: 写入属性
- **Notify**: 服务器主动通知
- **Indicate**: 服务器主动指示（需确认）

### MTU (Maximum Transmission Unit)
- 默认: 23 字节
- 最大: 512 字节（BLE 5.2）
- 协商: ATT_MTU_REQ / ATT_MTU_RSP

## SMP (Security Manager Protocol)

### 配对方式
- **Just Works**: 无需用户交互
- **Passkey Entry**: 输入密钥
- **Numeric Comparison**: 数字比较
- **Out of Band**: 带外配对

### 安全等级
- **Level 1**: 无安全
- **Level 2**: 未认证配对
- **Level 3**: 认证配对
- **Level 4**: 认证 LE Secure Connections

## BLE 5.x 新特性

### BLE 5.0
- **2M PHY**: 2 Mbps 物理层（提升吞吐量）
- **Coded PHY**: 编码物理层（提升距离）
- **Advertising Extensions**: 扩展广播（最大 255 字节）

### BLE 5.1
- **Direction Finding**: 方向查找（AoA/AoD）

### BLE 5.2
- **LE Audio**: 低功耗音频
- **EATT**: 增强 ATT（多通道）

## Nordic SoftDevice

### SoftDevice 版本
- **S132**: nRF52 系列（Central + Peripheral）
- **S140**: nRF52840（支持 BLE 5）
- **S113**: nRF5340 网络核

### API 层次
```
应用代码
    ↓
SoftDevice API (sd_ble_*)
    ↓
SoftDevice (协议栈)
    ↓
硬件 (RADIO, TIMER)
```

## 开发示例

### 初始化 BLE 栈
```c
// 启用 SoftDevice
sd_softdevice_enable(&clock_config, fault_handler);

// 配置 BLE 栈
ble_cfg_t ble_cfg;
sd_ble_cfg_set(BLE_CONN_CFG_GAP, &ble_cfg, ram_start);

// 启用 BLE 栈
sd_ble_enable(&ram_start);
```

### 开始广播
```c
ble_gap_adv_params_t adv_params = {
    .type = BLE_GAP_ADV_TYPE_ADV_IND,
    .interval = 160,  // 100ms
    .timeout = 0,     // 无超时
};

sd_ble_gap_adv_start(&adv_params, APP_BLE_CONN_CFG_TAG);
```

### 添加服务和特征
```c
// 添加服务
ble_uuid_t service_uuid = {.uuid = 0x1234, .type = BLE_UUID_TYPE_VENDOR_BEGIN};
sd_ble_gatts_service_add(BLE_GATTS_SRVC_TYPE_PRIMARY, &service_uuid, &service_handle);

// 添加特征
ble_gatts_char_md_t char_md = {
    .char_props.read = 1,
    .char_props.notify = 1,
};
sd_ble_gatts_characteristic_add(service_handle, &char_md, &attr_char_value, &char_handle);
```

## 功耗优化

### 连接间隔优化
- 短间隔（7.5-50ms）: 低延迟，高功耗
- 长间隔（100-1000ms）: 高延迟，低功耗

### Slave Latency
- 允许外设跳过连接事件
- 降低功耗，增加延迟

### 广播间隔优化
- 快速广播（20-100ms）: 快速发现，高功耗
- 慢速广播（1-10s）: 慢速发现，低功耗

## 参考资料

- [Bluetooth Core Specification](https://www.bluetooth.com/specifications/specs/)
- [Nordic nRF Connect SDK BLE Guide](https://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/ug_ble.html)
- [BLE Developer's Handbook](https://www.bluetooth.com/bluetooth-resources/)
```

- [ ] **Step 5.4: 更新知识库索引**

Run: `python3 -m agent.cli rebuild-index --knowledge-dir board_knowledge`

验证：
1. 索引包含 nRF52840、nRF5340、BLE 文档
2. 可以搜索到 "nRF52840"、"BLE"、"TrustZone" 等关键词

- [ ] **Step 5.5: 提交知识库扩展**

```bash
git add board_knowledge/nordic/ board_knowledge/protocols/ble.md
git commit -m "docs(knowledge): 添加 Nordic 平台知识库

- nRF52840 芯片手册（引脚、外设、功耗）
- nRF5340 芯片手册（双核架构、TrustZone）
- BLE 协议栈文档（GAP/GATT/ATT/SMP）
- 开发板信息和软件开发指南
- 功耗优化建议

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## Task 6: 集成测试和文档

**Files:**
- Create: `tests/integration/test_nordic_workflow.py`
- Modify: `agent/tools/__init__.py`
- Modify: `config.defaults.yaml`
- Modify: `README.md`

### Step 6.1: 编写端到端集成测试

- [ ] **编写 Nordic 开发工作流集成测试**

```python
# tests/integration/test_nordic_workflow.py
"""Nordic 平台端到端集成测试 — 验证完整开发工作流。

测试场景：
1. 检测 nRF52840 项目
2. 使用 CMake 构建
3. 使用 pyOCD 烧录
"""

import pytest
import tempfile
from pathlib import Path
from agent.platforms.nordic import NordicPlatform, detect_nrf_variant
from agent.tools.cmake_builder import CMakeBuilder, detect_cmake_project
from agent.tools.pyocd_flasher import PyOCDFlasher, detect_target_from_chip


@pytest.fixture
def nrf52840_project():
    """创建模拟的 nRF52840 CMake 项目"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # 创建 CMakeLists.txt
        (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(nrf52840_blinky C ASM)

set(BOARD nrf52840dk_nrf52840)
set(BOARD_ROOT ${CMAKE_CURRENT_SOURCE_DIR})

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})

target_sources(app PRIVATE src/main.c)
""")
        
        # 创建源文件
        src_dir = project_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.c").write_text("""
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

void main(void) {
    printk("nRF52840 Blinky\\n");
    while (1) {
        k_sleep(K_MSEC(1000));
    }
}
""")
        
        yield project_dir


def test_nordic_platform_detection():
    """测试 Nordic 平台检测"""
    platform = NordicPlatform()
    family = platform.get_chip_family()
    
    assert family.name == "nRF"
    assert "cmake" in family.supported_build_systems
    assert "pyocd" in family.supported_flash_tools


def test_nrf52840_variant_detection():
    """测试 nRF52840 变体检测"""
    variant = detect_nrf_variant("nRF52840")
    
    assert variant is not None
    assert variant.flash_size_kb == 1024
    assert variant.ram_size_kb == 256


def test_cmake_project_detection(nrf52840_project):
    """测试 CMake 项目检测"""
    project = detect_cmake_project(str(nrf52840_project))
    
    assert project is not None
    assert project.has_cmakelists
    
    info = project.parse_project_info()
    assert info["project_name"] == "nrf52840_blinky"


def test_cmake_build_command_generation(nrf52840_project):
    """测试 CMake 构建命令生成"""
    builder = CMakeBuilder()
    platform = NordicPlatform()
    
    # 生成配置命令
    configure_cmd = builder.generate_configure_command(
        source_dir=str(nrf52840_project),
        build_dir=str(nrf52840_project / "build"),
        definitions={"BOARD": "nrf52840dk_nrf52840"}
    )
    
    assert "cmake" in configure_cmd
    assert "-DBOARD=nrf52840dk_nrf52840" in configure_cmd
    
    # 生成构建命令
    build_cmd = builder.generate_build_command(
        build_dir=str(nrf52840_project / "build")
    )
    
    assert "cmake --build" in build_cmd


def test_pyocd_target_detection():
    """测试 pyOCD 目标检测"""
    target = detect_target_from_chip("nRF52840")
    
    assert target == "nrf52840"


def test_pyocd_flash_command_generation():
    """测试 pyOCD 烧录命令生成"""
    flasher = PyOCDFlasher()
    
    cmd = flasher.generate_flash_command(
        firmware_path="/path/to/zephyr.hex",
        target="nrf52840"
    )
    
    assert "pyocd flash" in cmd
    assert "-t nrf52840" in cmd
    assert "zephyr.hex" in cmd


def test_full_workflow_command_generation(nrf52840_project):
    """测试完整工作流命令生成"""
    # 1. 检测平台
    platform = NordicPlatform()
    variant = detect_nrf_variant("nRF52840")
    assert variant is not None
    
    # 2. 检测 CMake 项目
    project = detect_cmake_project(str(nrf52840_project))
    assert project is not None
    
    # 3. 生成构建命令
    builder = CMakeBuilder()
    build_cmd = platform.generate_build_command(
        project_dir=str(nrf52840_project),
        variant="nRF52840"
    )
    assert "cmake" in build_cmd
    
    # 4. 生成烧录命令
    flash_cmd = platform.generate_flash_command(
        firmware_path=str(nrf52840_project / "build" / "zephyr" / "zephyr.hex"),
        variant="nRF52840"
    )
    assert "pyocd" in flash_cmd or "nrfjprog" in flash_cmd
    
    # 5. 验证完整流程
    assert build_cmd is not None
    assert flash_cmd is not None


def test_multi_platform_support():
    """测试多平台支持（STM32 + nRF）"""
    from agent.platforms.base import get_global_registry
    
    registry = get_global_registry()
    
    # 验证 nRF 平台已注册
    nrf_family = registry.get("nRF")
    assert nrf_family is not None
    assert nrf_family.vendor == "Nordic Semiconductor"
    
    # 验证 CMake 构建系统已注册
    cmake = registry.get_build_system("cmake")
    assert cmake is not None
    
    # 验证 pyOCD 烧录工具已注册
    pyocd = registry.get_flash_tool("pyocd")
    assert pyocd is not None
    assert "nRF" in pyocd.supported_families
```

- [ ] **Step 6.2: 更新工具注册表导出**

```python
# agent/tools/__init__.py (追加)
from agent.tools.cmake_builder import register_cmake_tool
from agent.tools.pyocd_flasher import register_pyocd_tool

# 自动注册新工具
register_cmake_tool()
register_pyocd_tool()

__all__ = [
    # ... 现有导出 ...
    "cmake_builder",
    "pyocd_flasher",
]
```

- [ ] **Step 6.3: 更新配置文件**

```yaml
# config.defaults.yaml (追加)

# 平台配置
platforms:
  stm32:
    enabled: true
    default_build_system: make
    default_flash_tool: openocd
  
  nordic:
    enabled: true
    default_build_system: cmake
    default_flash_tool: pyocd
    sdk_path: null  # 可选，指向 nRF Connect SDK 路径

# 构建系统配置
build_systems:
  make:
    enabled: true
    parallel_jobs: 4
  
  cmake:
    enabled: true
    parallel_jobs: 4
    generator: "Unix Makefiles"  # 或 "Ninja"

# 烧录工具配置
flash_tools:
  openocd:
    enabled: true
    interface: "stlink"
  
  pyocd:
    enabled: true
    frequency: 1000000  # 1 MHz SWD 频率
  
  nrfjprog:
    enabled: false  # 需要安装 nRF Command Line Tools
```

- [ ] **Step 6.4: 更新 README 文档**

```markdown
# README.md (追加平台支持章节)

## 支持的平台

### STM32 系列
- **厂商**: STMicroelectronics
- **架构**: ARM Cortex-M
- **构建系统**: Make, CMake
- **烧录工具**: OpenOCD, ST-Link

### Nordic nRF 系列
- **厂商**: Nordic Semiconductor
- **架构**: ARM Cortex-M
- **支持芯片**:
  - nRF52 系列: nRF52810, nRF52832, nRF52833, nRF52840
  - nRF53 系列: nRF5340（双核）
- **构建系统**: CMake（nRF Connect SDK）
- **烧录工具**: pyOCD, nrfjprog, OpenOCD

## 快速开始 - Nordic nRF52840

### 1. 安装依赖

```bash
# 安装 pyOCD
pip install pyocd

# 安装 nRF Connect SDK（可选）
# 参考: https://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/gs_installing.html
```

### 2. 创建项目

```bash
# 使用 nRF Connect SDK 创建项目
west init -m https://github.com/nrfconnect/sdk-nrf nrf-workspace
cd nrf-workspace
west update
```

### 3. 构建固件

```bash
# 使用司南构建
sinan build --platform nordic --chip nRF52840

# 或手动使用 CMake
cmake -B build -S . -DBOARD=nrf52840dk_nrf52840
cmake --build build
```

### 4. 烧录固件

```bash
# 使用司南烧录
sinan flash --chip nRF52840 --firmware build/zephyr/zephyr.hex

# 或手动使用 pyOCD
pyocd flash -t nrf52840 build/zephyr/zephyr.hex
```

## 平台扩展

司南采用插件式平台架构，支持轻松添加新平台：

1. 在 `agent/platforms/` 创建新平台模块
2. 实现 `ChipFamily` 和变体检测
3. 注册到全局 `PlatformRegistry`
4. 添加知识库文档到 `board_knowledge/`

示例：添加 ESP32 平台

```python
# agent/platforms/espressif.py
from agent.platforms.base import ChipFamily, get_global_registry

esp32_family = ChipFamily(
    name="ESP32",
    vendor="Espressif",
    architecture="Xtensa LX6",
    supported_build_systems=["cmake", "platformio"],
    supported_flash_tools=["esptool"],
)

registry = get_global_registry()
registry.register(esp32_family)
```
```

- [ ] **Step 6.5: 运行完整测试套件**

Run: `python3 -m pytest tests/ -v --cov=agent --cov-report=term-missing`

验证：
1. 所有单元测试通过
2. 集成测试通过
3. 代码覆盖率 ≥ 70%

- [ ] **Step 6.6: 提交集成测试和文档**

```bash
git add tests/integration/test_nordic_workflow.py agent/tools/__init__.py config.defaults.yaml README.md
git commit -m "feat: Phase 2C 集成测试和文档完成

- 端到端 Nordic 工作流集成测试
- 更新工具注册表导出
- 添加平台配置到 config.defaults.yaml
- 更新 README 添加 Nordic 平台支持说明
- 添加平台扩展指南

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase 2C 完成检查清单

- [ ] **平台抽象层**
  - [ ] ChipFamily、ChipVariant、BuildSystem、FlashTool 抽象定义
  - [ ] PlatformRegistry 注册表实现
  - [ ] 单元测试覆盖率 ≥ 80%

- [ ] **Nordic nRF 平台**
  - [ ] nRF52 系列支持（nRF52810/832/833/840）
  - [ ] nRF53 系列支持（nRF5340 双核）
  - [ ] 芯片变体自动检测
  - [ ] 构建和烧录命令生成
  - [ ] 单元测试覆盖率 ≥ 80%

- [ ] **CMake 构建系统**
  - [ ] CMakeLists.txt 检测和解析
  - [ ] 配置命令生成（支持工具链、自定义变量）
  - [ ] 构建命令生成（支持并行、目标选择）
  - [ ] 工具注册表集成
  - [ ] 单元测试覆盖率 ≥ 80%

- [ ] **pyOCD 烧录工具**
  - [ ] 目标检测（nRF52/nRF53/STM32）
  - [ ] 烧录命令生成
  - [ ] 擦除和复位命令
  - [ ] 多文件烧录支持
  - [ ] 工具注册表集成
  - [ ] 单元测试覆盖率 ≥ 80%

- [ ] **知识库扩展**
  - [ ] nRF52840 芯片手册（引脚、外设、功耗）
  - [ ] nRF5340 芯片手册（双核、TrustZone）
  - [ ] BLE 协议栈文档（GAP/GATT/ATT/SMP）
  - [ ] 知识库索引更新

- [ ] **集成测试**
  - [ ] 端到端 Nordic 工作流测试
  - [ ] 多平台支持验证
  - [ ] 所有测试通过

- [ ] **文档**
  - [ ] README 更新（平台支持列表）
  - [ ] 快速开始指南（Nordic nRF52840）
  - [ ] 平台扩展指南
  - [ ] 配置文件文档

---

## 执行建议

**预计时间**: 3-4 天

**执行顺序**:
1. **Day 1**: Task 1-2（平台抽象层 + Nordic 平台）
2. **Day 2**: Task 3-4（CMake + pyOCD）
3. **Day 3**: Task 5（知识库扩展）
4. **Day 4**: Task 6（集成测试 + 文档）

**注意事项**:
- pyOCD 需要安装: `pip install pyocd`
- 测试 pyOCD 需要连接支持的调试器（CMSIS-DAP）
- nRF Connect SDK 可选，用于完整开发体验
- 知识库文档参考 Nordic 官方文档
- 平台抽象层设计要考虑未来扩展（ESP32、RISC-V）

**依赖关系**:
- Task 2 依赖 Task 1（平台抽象层）
- Task 3-4 可并行开发
- Task 5 独立，可提前开始
- Task 6 依赖 Task 1-5 全部完成

---

## 反模式防护

| 反模式 | 防护措施 |
|--------|----------|
| 硬编码芯片型号 | 使用 ChipVariant 抽象，支持动态检测 |
| 构建系统耦合 | BuildSystem 独立于芯片平台 |
| 烧录工具绑定 | FlashTool 支持多工具切换 |
| 知识库过时 | 引用官方文档链接，定期更新 |
| 平台扩展困难 | 插件式架构，注册表管理 |
| 测试覆盖不足 | TDD 5-step 模式，覆盖率 ≥ 80% |
| 文档缺失 | 每个 Task 包含文档更新 |

---

## 性能指标

- **平台检测**: < 100ms
- **命令生成**: < 10ms
- **知识库搜索**: < 100ms（Phase 2B 索引）
- **单元测试**: < 5s（全部）
- **集成测试**: < 30s（全部）

---

## 未来扩展方向

### Phase 2D: 更多平台支持
- ESP32 系列（Espressif）
- RISC-V 系列（SiFive, GigaDevice）
- AVR 系列（Microchip）

### Phase 2E: 高级功能
- 多核调试支持
- RTOS 感知调试
- 性能分析工具集成
- OTA 固件更新

### Phase 2F: 云端集成
- 远程烧录和调试
- 固件版本管理
- 设备群组管理

---

## 参考资料

- [Nordic nRF Connect SDK](https://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/index.html)
- [pyOCD Documentation](https://pyocd.io/)
- [CMake Documentation](https://cmake.org/documentation/)
- [Bluetooth Core Specification](https://www.bluetooth.com/specifications/specs/)
- [ARM Cortex-M Programming Guide](https://developer.arm.com/documentation/)

