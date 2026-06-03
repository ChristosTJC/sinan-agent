"""Espressif ESP32 platform support."""

from __future__ import annotations

from typing import Any, Optional

from agent.platforms.base import BuildSystem, ChipFamily, ChipVariant, FlashTool, get_global_registry


ESP32_VARIANTS: dict[str, dict[str, Any]] = {
    "ESP32": {
        "series": "Classic",
        "flash_kb": 4096,
        "ram_kb": 520,
        "max_freq_mhz": 240,
        "architecture": "Xtensa LX6",
        "idf_target": "esp32",
        "peripherals": ["WiFi", "BLE", "GPIO", "SPI", "I2C", "UART", "ADC"],
    },
    "ESP32-S3": {
        "series": "S3",
        "flash_kb": 8192,
        "ram_kb": 512,
        "max_freq_mhz": 240,
        "architecture": "Xtensa LX7",
        "idf_target": "esp32s3",
        "peripherals": ["WiFi", "BLE5", "USB", "GPIO", "SPI", "I2C", "UART", "ADC"],
    },
    "ESP32-C3": {
        "series": "C3",
        "flash_kb": 4096,
        "ram_kb": 400,
        "max_freq_mhz": 160,
        "architecture": "RISC-V",
        "idf_target": "esp32c3",
        "peripherals": ["WiFi", "BLE5", "GPIO", "SPI", "I2C", "UART", "ADC"],
    },
}


def _normalize_model(model: str) -> str:
    return model.replace("_", "-").upper()


def detect_esp32_variant(model: str) -> Optional[ChipVariant]:
    """Detect a supported ESP32 variant from chip, module, or board text."""
    normalized = _normalize_model(model)
    for variant_name in ("ESP32-S3", "ESP32-C3", "ESP32"):
        specs = ESP32_VARIANTS[variant_name]
        compact = variant_name.replace("-", "")
        if variant_name in normalized or compact in normalized.replace("-", ""):
            return ChipVariant(
                family="ESP32",
                series=specs["series"],
                model=variant_name,
                flash_size_kb=specs["flash_kb"],
                ram_size_kb=specs["ram_kb"],
                max_freq_mhz=specs["max_freq_mhz"],
                peripherals=specs.get("peripherals", []),
                metadata={
                    "vendor": "Espressif",
                    "architecture": specs["architecture"],
                    "idf_target": specs["idf_target"],
                },
            )
    return None


class ESP32Platform:
    """ESP32 platform command and metadata adapter."""

    def __init__(self) -> None:
        self._chip_family = ChipFamily(
            name="ESP32",
            vendor="Espressif",
            architecture="Xtensa/RISC-V",
            supported_build_systems=["esp-idf", "platformio", "arduino"],
            supported_flash_tools=["esptool", "esp-idf", "platformio"],
            default_build_system="esp-idf",
            default_flash_tool="esp-idf",
            metadata={"sdk": "ESP-IDF"},
        )

    def get_chip_family(self) -> ChipFamily:
        """Return the ESP32 chip family definition."""
        return self._chip_family

    def idf_target(self, variant: str) -> str:
        """Return the ESP-IDF target for a variant string."""
        detected = detect_esp32_variant(variant)
        if detected is None:
            return "esp32"
        return str(detected.metadata["idf_target"])

    def generate_build_command(self, project_dir: str, variant: str) -> str:
        """Generate an ESP-IDF build command for dry-run workflows."""
        target = self.idf_target(variant)
        return f"cd {project_dir} && idf.py set-target {target} && idf.py build"

    def generate_flash_command(
        self,
        firmware_path: str,
        variant: str,
        port: str,
        tool: str = "esp-idf",
    ) -> str:
        """Generate a flash command for ESP32 dry-run workflows."""
        target = self.idf_target(variant)
        if tool == "esp-idf":
            return f"idf.py -p {port} -DIDF_TARGET={target} flash"
        if tool == "esptool":
            firmware = firmware_path or "build/firmware.bin"
            return f"esptool.py --chip {target} --port {port} write_flash 0x10000 {firmware}"
        raise ValueError(f"不支持的 ESP32 烧录工具: {tool}")


def register_esp32_platform() -> None:
    """Register ESP32 metadata in the global platform registry."""
    registry = get_global_registry()
    platform = ESP32Platform()

    try:
        registry.register(platform.get_chip_family())
    except ValueError:
        pass

    try:
        registry.register_build_system(BuildSystem(
            name="esp-idf",
            display_name="ESP-IDF",
            config_files=["sdkconfig", "CMakeLists.txt"],
            build_command="idf.py build",
            clean_command="idf.py fullclean",
        ))
    except ValueError:
        pass

    try:
        registry.register_flash_tool(FlashTool(
            name="esptool",
            display_name="esptool.py",
            supported_families=["ESP32"],
            flash_command_template="esptool.py --chip {target} --port {port} write_flash 0x10000 {firmware}",
        ))
    except ValueError:
        pass


register_esp32_platform()
