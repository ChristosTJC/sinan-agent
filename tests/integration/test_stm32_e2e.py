"""STM32 端到端干运行集成测试。

⚠️ 重要：这些是纯 dry-run 测试，不依赖真实硬件。只验证：
- 命令生成正确性（工具链参数、芯片型号映射）
- 诊断解析逻辑（HardFault/assert/复位模式识别）
- 不证明真实硬件烧录闭环！

验证完整链路：build_firmware → flash_firmware → diagnose，全部通过 mock
subprocess 执行，不依赖真实硬件。
"""

import subprocess

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.dryrun]

from agent.tools import firmware_builder, firmware_flasher
from agent.tools.firmware_builder import build_firmware
from agent.tools.firmware_flasher import flash_firmware
from agent.tools.stm32_diagnostics import diagnose_stm32_log

from tests.conftest import Completed


# ── 构建链路 ──────────────────────────────────────────────────────────────────


def test_stm32_build_injects_cmake_definitions(stm32_cmake_project, monkeypatch):
    """STM32 CMake 构建注入正确的 MCU 定义。"""
    calls = []

    monkeypatch.setattr(firmware_builder.shutil, "which",
                        lambda name: "/usr/bin/cmake" if name == "cmake" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(stm32_cmake_project), platform="stm32", chip="STM32F407VG")

    assert result["success"] is True
    # 阶段 1: cmake 配置
    configure_cmd_str = " ".join(calls[0])
    assert "-DCHIP=STM32F407VG" in configure_cmd_str
    assert "-DMCU_FAMILY=STM32F4" in configure_cmd_str
    assert "-DCMAKE_SYSTEM_PROCESSOR=cortex-m4" in configure_cmd_str
    # 阶段 2: cmake 构建
    build_cmd = calls[1]
    assert build_cmd[0] == "cmake"
    assert "--build" in build_cmd


# ── 烧录链路 ──────────────────────────────────────────────────────────────────


def test_stm32_flash_via_openocd_uses_correct_firmware(stm32_cmake_project, monkeypatch):
    """STM32 通过 OpenOCD 烧录，firmware 路径正确注入命令。"""
    build_dir = stm32_cmake_project / "build"
    build_dir.mkdir()
    firmware = build_dir / "stm32_blinky.elf"
    firmware.write_text("ELF")

    calls = []

    monkeypatch.setattr(firmware_flasher.shutil, "which",
                        lambda name: "/usr/bin/openocd" if name == "openocd" else None)

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_flasher.subprocess, "run", fake_run)

    result = flash_firmware(
        project_path=str(stm32_cmake_project),
        port="",
        method="openocd",
        platform="stm32",
        chip="STM32F407VG",
    )

    assert result["success"] is True
    assert len(calls) == 1
    cmd_str = " ".join(calls[0])
    assert "openocd" in cmd_str
    assert "program" in cmd_str
    assert str(firmware) in cmd_str
    assert "verify" in cmd_str


# ── 诊断链路 ──────────────────────────────────────────────────────────────────


def test_stm32_diagnose_hardfault_produces_structured_result():
    """STM32 HardFault 日志被正确解析为结构化诊断。"""
    log = "HardFault_Handler entered\nHFSR=0x40000000 CFSR=0x00008200 BFAR=0x0800abcd\n"

    result = diagnose_stm32_log(log)

    assert result["success"] is True
    assert result["fault"]["type"] == "HardFault"
    assert result["fault"]["registers"]["CFSR"] == "0x00008200"
    assert len(result["hints"]) >= 1


def test_stm32_diagnose_hal_timeout_gives_peripheral_hints():
    """STM32 HAL_TIMEOUT 被识别并给出外设相关提示。"""
    result = diagnose_stm32_log("SPI transfer failed: HAL_TIMEOUT\n")

    assert result["success"] is True
    assert result["hal"]["status"] == "HAL_TIMEOUT"
    assert any("超时" in hint for hint in result["hints"])


# ── 端到端：构建→烧录→诊断 全链路 ────────────────────────────────────────────


def test_stm32_e2e_dry_run_build_flash_diagnose(stm32_cmake_project, monkeypatch):
    """STM32 完整干运行链路的命令生成 + 诊断验证。

    从 platform=stm32 + chip=STM32F407VG 出发，生成构建和烧录命令，
    然后将模拟的 HardFault 日志送入诊断器，验证全链路数据一致性。
    """
    # ── 阶段 1：构建 ──
    build_calls = []
    monkeypatch.setattr(firmware_builder.shutil, "which",
                        lambda name: "/usr/bin/cmake" if name == "cmake" else None)

    def fake_build(cmd, cwd, timeout=300):
        build_calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_build)

    build_result = build_firmware(str(stm32_cmake_project), platform="stm32", chip="STM32F407VG")
    assert build_result["success"] is True
    assert any("STM32F407VG" in " ".join(c) for c in build_calls)

    # ── 阶段 2：烧录 ──
    build_dir = stm32_cmake_project / "build"
    build_dir.mkdir(exist_ok=True)
    (build_dir / "stm32_blinky.elf").write_text("ELF")

    flash_calls = []
    monkeypatch.setattr(firmware_flasher.shutil, "which",
                        lambda name: "/usr/bin/openocd" if name == "openocd" else None)

    def fake_flash(cmd, **_kwargs):
        flash_calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_flasher.subprocess, "run", fake_flash)

    flash_result = flash_firmware(
        project_path=str(stm32_cmake_project),
        port="",
        method="openocd",
        platform="stm32",
        chip="STM32F407VG",
    )
    assert flash_result["success"] is True
    assert len(flash_calls) == 1

    # ── 阶段 3：诊断 ──
    diag = diagnose_stm32_log("HardFault_Handler entered\nHFSR=0x40000000\n")
    assert diag["success"] is True
    assert diag["fault"]["type"] == "HardFault"
