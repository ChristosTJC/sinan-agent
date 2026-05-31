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
