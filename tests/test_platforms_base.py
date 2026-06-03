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


def test_detect_platform_matches_nrf_source_headers(tmp_path):
    """源码包含 nrfx 头文件时应识别已注册的 nRF family。"""
    (tmp_path / "main.c").write_text('#include <nrfx.h>\nint main(void) { return 0; }\n')
    registry = PlatformRegistry()
    nrf = ChipFamily(
        name="nRF",
        vendor="Nordic Semiconductor",
        architecture="ARM Cortex-M",
        supported_build_systems=["cmake"],
        supported_flash_tools=["pyocd"],
    )
    registry.register(nrf)

    assert registry.detect_platform(str(tmp_path)) == nrf
