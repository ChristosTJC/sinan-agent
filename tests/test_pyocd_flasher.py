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
