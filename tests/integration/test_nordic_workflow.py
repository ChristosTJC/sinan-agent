"""Nordic 平台端到端集成测试 — 验证完整开发工作流。"""

import pytest

pytestmark = pytest.mark.integration
import tempfile
from pathlib import Path
from agent.platforms.nordic import NordicPlatform, detect_nrf_variant
from agent.tools.pyocd_flasher import PyOCDFlasher, detect_target_from_chip


@pytest.fixture
def nrf52840_project():
    """创建模拟的 nRF52840 CMake 项目"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(nrf52840_blinky C ASM)

set(BOARD nrf52840dk_nrf52840)
set(BOARD_ROOT ${CMAKE_CURRENT_SOURCE_DIR})

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})

target_sources(app PRIVATE src/main.c)
""")

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
    """测试完整工作流命令生成（NordicPlatform 真实路径）"""
    platform = NordicPlatform()
    variant = detect_nrf_variant("nRF52840")
    assert variant is not None

    build_cmd = platform.generate_build_command(
        project_dir=str(nrf52840_project),
        variant="nRF52840"
    )
    assert "cmake" in build_cmd

    flash_cmd = platform.generate_flash_command(
        firmware_path=str(nrf52840_project / "build" / "zephyr" / "zephyr.hex"),
        variant="nRF52840"
    )
    assert "pyocd" in flash_cmd or "nrfjprog" in flash_cmd

    assert build_cmd is not None
    assert flash_cmd is not None


def test_multi_platform_support():
    """测试多平台支持（STM32 + nRF）"""
    from agent.platforms.base import get_global_registry

    registry = get_global_registry()

    nrf_family = registry.get("nRF")
    assert nrf_family is not None
    assert nrf_family.vendor == "Nordic Semiconductor"

    cmake = registry.get_build_system("cmake")
    assert cmake is not None

    pyocd = registry.get_flash_tool("pyocd")
    assert pyocd is not None
    assert "nRF" in pyocd.supported_families
