"""STM32 platform support for common Cortex-M MCU families."""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Optional

from agent.platforms.base import BuildSystem, ChipFamily, ChipVariant, FlashTool, get_global_registry


STM32_VARIANTS: dict[str, dict[str, Any]] = {
    "STM32F103": {
        "series": "F1",
        "flash_kb": 128,
        "ram_kb": 20,
        "max_freq_mhz": 72,
        "core": "cortex-m3",
        "openocd_target": "stm32f1x",
        "peripherals": ["GPIO", "USART", "SPI", "I2C", "ADC", "CAN"],
    },
    "STM32F407": {
        "series": "F4",
        "flash_kb": 1024,
        "ram_kb": 192,
        "max_freq_mhz": 168,
        "core": "cortex-m4",
        "openocd_target": "stm32f4x",
        "peripherals": ["GPIO", "USART", "SPI", "I2C", "ADC", "CAN", "USB", "ETH"],
    },
}


def _normalize_model(model: str) -> str:
    return model.replace("-", "").replace("_", "").upper()


def detect_stm32_variant(model: str) -> Optional[ChipVariant]:
    """Detect a supported STM32 variant from a chip or board model string."""
    normalized = _normalize_model(model)
    for variant_name, specs in STM32_VARIANTS.items():
        if variant_name in normalized:
            return ChipVariant(
                family="STM32",
                series=specs["series"],
                model=variant_name,
                flash_size_kb=specs["flash_kb"],
                ram_size_kb=specs["ram_kb"],
                max_freq_mhz=specs["max_freq_mhz"],
                peripherals=specs.get("peripherals", []),
                metadata={
                    "vendor": "STMicroelectronics",
                    "core": specs["core"],
                    "openocd_target": specs["openocd_target"],
                },
            )
    return None


class STM32Platform:
    """STM32 platform command and metadata adapter."""

    def __init__(self) -> None:
        self._chip_family = ChipFamily(
            name="STM32",
            vendor="STMicroelectronics",
            architecture="ARM Cortex-M",
            supported_build_systems=["cmake", "make"],
            supported_flash_tools=["stm32cubeprog", "openocd", "pyocd"],
            default_build_system="cmake",
            default_flash_tool="stm32cubeprog",
            metadata={"sdk": "STM32Cube HAL"},
        )

    def get_chip_family(self) -> ChipFamily:
        """Return the STM32 chip family definition."""
        return self._chip_family

    def get_cmake_definitions(self, variant: str) -> dict[str, str]:
        """Return CMake definitions for a supported STM32 variant."""
        detected = detect_stm32_variant(variant)
        definitions = {"CHIP": variant}
        if detected is not None:
            definitions["MCU_FAMILY"] = f"STM32{detected.series}"
            definitions["CMAKE_SYSTEM_PROCESSOR"] = str(detected.metadata["core"])
        return definitions

    def generate_build_command(
        self,
        project_dir: str,
        variant: str,
        build_type: str = "Release",
    ) -> str:
        """Generate a CMake build command for STM32 dry-run workflows."""
        definitions = self.get_cmake_definitions(variant)
        flags = " ".join(f"-D{k}={v}" for k, v in definitions.items())
        return (
            f"cmake -B build -S {project_dir} {flags} "
            f"-DCMAKE_BUILD_TYPE={build_type} && cmake --build build"
        )

    def generate_flash_command(
        self,
        firmware_path: str,
        variant: str,
        tool: str = "stm32cubeprog",
    ) -> str:
        """Generate a flash command for a supported STM32 tool."""
        detected = detect_stm32_variant(variant)
        openocd_target = (
            str(detected.metadata["openocd_target"]) if detected is not None else "stm32f4x"
        )

        if tool == "stm32cubeprog":
            return f"STM32_Programmer_CLI -c port=SWD -w {firmware_path} -v -rst"
        if tool == "openocd":
            return (
                "openocd -f interface/stlink.cfg "
                f"-f target/{openocd_target}.cfg "
                f"-c 'program {firmware_path} verify reset exit'"
            )
        if tool == "pyocd":
            return f"pyocd flash -t {variant.lower()} {firmware_path}"
        raise ValueError(f"不支持的 STM32 烧录工具: {tool}")


def register_stm32_platform() -> None:
    """Register STM32 metadata in the global platform registry."""
    registry = get_global_registry()
    platform = STM32Platform()

    with suppress(ValueError):
        registry.register(platform.get_chip_family())

    with suppress(ValueError):
        registry.register_build_system(BuildSystem(
            name="cmake",
            display_name="CMake",
            config_files=["CMakeLists.txt"],
            build_command="cmake --build build",
            clean_command="cmake --build build --target clean",
        ))

    with suppress(ValueError):
        registry.register_flash_tool(FlashTool(
            name="stm32cubeprog",
            display_name="STM32CubeProgrammer",
            supported_families=["STM32"],
            flash_command_template="STM32_Programmer_CLI -c port=SWD -w {firmware} -v -rst",
        ))


register_stm32_platform()
