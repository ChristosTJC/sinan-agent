"""ESP32 端到端干运行集成测试。

验证完整链路：build_firmware → flash_firmware → diagnose，全部通过 mock
subprocess 执行，不依赖真实硬件。
"""

import subprocess

import pytest

pytestmark = pytest.mark.integration

from agent.tools import firmware_builder, firmware_flasher
from agent.tools.firmware_builder import build_firmware
from agent.tools.firmware_flasher import flash_firmware
from agent.tools.esp32_diagnostics import diagnose_esp32_log

from tests.conftest import Completed


# ── 构建链路 ──────────────────────────────────────────────────────────────────


def test_esp32_build_uses_idf_py_set_target_and_build(esp32_idf_project, monkeypatch):
    """ESP-IDF 项目构建生成正确的 idf.py 命令序列。"""
    calls = []

    monkeypatch.setattr(firmware_builder.shutil, "which",
                        lambda name: "/usr/bin/idf.py" if name == "idf.py" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(esp32_idf_project), platform="esp32", chip="ESP32-S3")

    assert result["success"] is True
    assert calls == [["idf.py", "set-target", "esp32s3"], ["idf.py", "build"]]


def test_esp32_build_requires_idf_py_when_sdkconfig_present(esp32_idf_project, monkeypatch):
    """当 idf.py 不可用时，ESP32 构建报错（不会回退到 CMake）。"""
    monkeypatch.setattr(firmware_builder.shutil, "which", lambda _name: None)
    result = build_firmware(str(esp32_idf_project), platform="esp32", chip="ESP32-S3")
    assert result["success"] is False
    assert any("idf.py" in e for e in result["errors"])


# ── 烧录链路 ──────────────────────────────────────────────────────────────────


def test_esp32_flash_via_idf_py_sets_target_and_port(esp32_idf_project, monkeypatch):
    """ESP32 idf.py flash 将 target 和端口注入命令。"""
    calls = []

    monkeypatch.setattr(firmware_flasher.shutil, "which",
                        lambda name: "/usr/bin/idf.py" if name == "idf.py" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_flasher, "_run_command", fake_run)

    result = flash_firmware(
        project_path=str(esp32_idf_project),
        port="/dev/ttyUSB0",
        method="auto",
        platform="esp32",
        chip="ESP32-S3",
    )

    assert result["success"] is True
    assert calls == [["idf.py", "-p", "/dev/ttyUSB0", "-DIDF_TARGET=esp32s3", "flash"]]


# ── 诊断链路 ──────────────────────────────────────────────────────────────────


def test_esp32_diagnose_panic_with_backtrace():
    """ESP32 Guru Meditation panic 被正确解析，含 backtrace 行。"""
    log = """
    Guru Meditation Error: Core  0 panic'ed (StoreProhibited). Exception was unhandled.
    Core  0 register dump:
    PC      : 0x400d5678  PS      : 0x00060f30
    Backtrace: 0x400d5678:0x3ffb1f20 0x40081234:0x3ffb1f40
    """

    result = diagnose_esp32_log(log)

    assert result["success"] is True
    assert result["panic"]["reason"] == "StoreProhibited"
    assert result["panic"]["core"] == 0
    assert result["backtrace"] == ["0x400d5678", "0x40081234"]
    assert "StoreProhibited" in result["hints"][0]


def test_esp32_diagnose_reset_brownout_combo():
    """ESP32 复位 + 欠压组合被同时识别。"""
    log = "rst:0x7 (SW_CPU_RESET)\nBrownout detector was triggered\n"

    result = diagnose_esp32_log(log)

    assert result["success"] is True
    assert result["reset"]["reason"] == "SW_CPU_RESET"
    assert result["power"]["brownout"] is True


# ── 端到端：构建→烧录→诊断 全链路 ────────────────────────────────────────────


def test_esp32_e2e_dry_run_build_flash_diagnose(esp32_idf_project, monkeypatch):
    """ESP32 完整干运行链路：从 platform/chip 到 idf.py 命令到 panic 诊断。

    模拟真实的 ESP-IDF 工作流：set-target → build → flash → 诊断 panic 日志。
    """
    # ── 阶段 1：构建 ──
    build_calls = []
    monkeypatch.setattr(firmware_builder.shutil, "which",
                        lambda name: "/usr/bin/idf.py" if name == "idf.py" else None)

    def fake_build(cmd, cwd, timeout=300):
        build_calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_build)

    build_result = build_firmware(str(esp32_idf_project), platform="esp32", chip="ESP32-S3")
    assert build_result["success"] is True
    assert build_calls == [["idf.py", "set-target", "esp32s3"], ["idf.py", "build"]]

    # ── 阶段 2：烧录 ──
    flash_calls = []
    monkeypatch.setattr(firmware_flasher.shutil, "which",
                        lambda name: "/usr/bin/idf.py" if name == "idf.py" else None)

    def fake_flash(cmd, cwd, timeout=300):
        flash_calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_flasher, "_run_command", fake_flash)

    flash_result = flash_firmware(
        project_path=str(esp32_idf_project),
        port="/dev/ttyUSB0",
        method="auto",
        platform="esp32",
        chip="ESP32-S3",
    )
    assert flash_result["success"] is True
    expected = ["idf.py", "-p", "/dev/ttyUSB0", "-DIDF_TARGET=esp32s3", "flash"]
    assert flash_calls == [expected]

    # ── 阶段 3：诊断 ──
    diag = diagnose_esp32_log(
        "Guru Meditation Error: Core  1 panic'ed (LoadProhibited). Exception was unhandled.\n"
        "Backtrace: 0x400d1234:0x3ffb0000 0x400d5678:0x3ffb0020\n"
    )
    assert diag["success"] is True
    assert diag["panic"]["reason"] == "LoadProhibited"
    assert diag["backtrace"] == ["0x400d1234", "0x400d5678"]
