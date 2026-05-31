"""Nordic nRF 平台支持 — nRF52/nRF53 系列芯片。"""

from __future__ import annotations
from typing import Optional, Dict, Any
from agent.platforms.base import ChipFamily, ChipVariant, BuildSystem, FlashTool


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

NRF53_VARIANTS: Dict[str, Dict[str, Any]] = {
    "nRF5340": {
        "flash_kb": 1024,
        "ram_kb": 512,
        "max_freq_mhz": 128,
        "package": "QFN94",
        "peripherals": ["BLE5.2", "Thread", "Zigbee", "GPIO", "SPI", "I2C", "UART", "ADC", "USB", "NFC"],
        "cores": 2,
        "core_app": "ARM Cortex-M33 @ 128MHz",
        "core_net": "ARM Cortex-M33 @ 64MHz",
        "trustzone": True,
    },
}


def detect_nrf_variant(model: str) -> Optional[ChipVariant]:
    """检测 nRF 芯片变体。"""
    model_normalized = model.replace("-", "").replace("_", "").upper()

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
        """生成 CMake 构建命令。"""
        board = self._variant_to_board(variant)
        return (
            f"cmake -B build -S {project_dir} "
            f"-DBOARD={board} "
            f"-DCHIP={variant} "
            f"-DCMAKE_BUILD_TYPE={build_type} && "
            f"cmake --build build"
        )

    def generate_flash_command(
        self,
        firmware_path: str,
        variant: str,
        tool: str = "pyocd",
    ) -> str:
        """生成烧录命令。"""
        target = self._variant_to_target(variant)

        if tool == "pyocd":
            return f"pyocd flash -t {target} {firmware_path}"
        if tool == "nrfjprog":
            return f"nrfjprog --program {firmware_path} --chiperase --verify --reset"
        if tool == "openocd":
            return (
                f"openocd -f interface/cmsis-dap.cfg "
                f"-f target/{target}.cfg "
                f"-c 'program {firmware_path} verify reset exit'"
            )
        raise ValueError(f"不支持的烧录工具: {tool}")

    def _variant_to_board(self, variant: str) -> str:
        """将芯片型号转换为 CMake BOARD 参数。"""
        variant_lower = variant.lower().replace("-", "").replace("_", "")

        if "nrf52840" in variant_lower:
            return "nrf52840dk_nrf52840"
        if "nrf52833" in variant_lower:
            return "nrf52833dk_nrf52833"
        if "nrf52832" in variant_lower:
            return "nrf52dk_nrf52832"
        if "nrf5340" in variant_lower:
            return "nrf5340dk_nrf5340_cpuapp"
        return f"{variant_lower}dk_{variant_lower}"

    def _variant_to_target(self, variant: str) -> str:
        """将芯片型号转换为烧录工具目标名称。"""
        return variant.lower().replace("-", "").replace("_", "")


def register_nordic_platform():
    """注册 Nordic 平台到全局注册表"""
    from agent.platforms.base import get_global_registry

    platform = NordicPlatform()
    registry = get_global_registry()

    try:
        registry.register(platform.get_chip_family())
    except ValueError:
        pass

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


register_nordic_platform()
