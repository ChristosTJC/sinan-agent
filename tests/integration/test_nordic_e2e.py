"""Nordic 端到端干运行集成测试。

验证完整链路：build_firmware → flash_firmware → diagnose，覆盖 west/pyOCD/nrfjprog
三条烧录路径，全部 mock subprocess，不依赖真实硬件。
"""

import subprocess

import pytest

pytestmark = pytest.mark.integration

from agent.tools import firmware_builder, firmware_flasher
from agent.tools.firmware_builder import build_firmware
from agent.tools.firmware_flasher import flash_firmware
from agent.tools.nordic_diagnostics import diagnose_nordic_log

from tests.conftest import Completed


# ── 构建链路 ──────────────────────────────────────────────────────────────────


def test_nordic_build_uses_west_for_zephyr_project(nordic_zephyr_project, monkeypatch):
    """Nordic Zephyr 项目通过 west build 构建，板型从 chip 推导。"""
    calls = []

    monkeypatch.setattr(firmware_builder.shutil, "which",
                        lambda name: "/usr/bin/west" if name == "west" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(nordic_zephyr_project), platform="nordic", chip="nRF52840")

    assert result["success"] is True
    assert calls == [["west", "build", "-b", "nrf52840dk_nrf52840", str(nordic_zephyr_project)]]


def test_nordic_build_requires_west_when_zephyr_project(nordic_zephyr_project, monkeypatch):
    """当 west 不可用时，Nordic Zephyr 项目构建报错（不会回退到 CMake）。"""
    monkeypatch.setattr(firmware_builder.shutil, "which", lambda _name: None)
    result = build_firmware(str(nordic_zephyr_project), platform="nordic", chip="nRF52840")
    assert result["success"] is False
    assert any("west" in e for e in result["errors"])


# ── 烧录链路 ──────────────────────────────────────────────────────────────────


def test_nordic_flash_via_west_flash_with_build_dir(nordic_zephyr_project, monkeypatch):
    """Nordic Zephyr 项目通过 west flash 烧录，自动指向 build 目录。"""
    calls = []

    monkeypatch.setattr(firmware_flasher.shutil, "which",
                        lambda name: "/usr/bin/west" if name == "west" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_flasher, "_run_command", fake_run)

    result = flash_firmware(
        project_path=str(nordic_zephyr_project),
        port="",
        method="auto",
        platform="nordic",
        chip="nRF52840",
    )

    assert result["success"] is True
    assert calls == [["west", "flash", "--build-dir", str(nordic_zephyr_project / "build")]]


def test_nordic_flash_via_nrfjprog_with_auto_hex_lookup(nordic_zephyr_project, monkeypatch):
    """Nordic nrfjprog 烧录自动查找 build/zephyr/zephyr.hex 并生成 NRF52 family 命令。"""
    build_dir = nordic_zephyr_project / "build" / "zephyr"
    build_dir.mkdir(parents=True)
    firmware = build_dir / "zephyr.hex"
    firmware.write_text(":00000001FF\n")

    calls = []

    monkeypatch.setattr(firmware_flasher.shutil, "which",
                        lambda name: "/usr/bin/nrfjprog" if name == "nrfjprog" else None)

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr("agent.tools.nrfjprog_flasher.subprocess.run", fake_run)

    result = flash_firmware(
        project_path=str(nordic_zephyr_project),
        port="",
        method="nrfjprog",
        platform="nordic",
        chip="nRF52840",
    )

    assert result["success"] is True
    cmd = calls[0]
    assert cmd[0] == "nrfjprog"
    assert "--family" in cmd
    assert "NRF52" in cmd
    assert "--sectorerase" in cmd
    assert "--verify" in cmd
    assert "--reset" in cmd
    assert str(firmware) in cmd


# ── 诊断链路 ──────────────────────────────────────────────────────────────────


def test_nordic_diagnose_fatal_error():
    """Nordic Zephyr fatal error 被正确解析，含错误码和原因。"""
    log = "Fatal error 4: Kernel panic. CPU exception. r0/a1: 0x00000000\n"

    result = diagnose_nordic_log(log)

    assert result["success"] is True
    assert result["fault"]["type"] == "FATAL ERROR"
    assert result["fault"]["fatal_error"] == 4
    assert "Kernel panic" in result["summary"]


def test_nordic_diagnose_assertion():
    """Zephyr ASSERTION FAIL 被正确解析，含表达式和位置。"""
    result = diagnose_nordic_log(
        "ASSERTION FAIL [buf != NULL] @ WEST_TOPDIR/zephyr/subsys/bt/conn.c:456\n"
    )

    assert result["success"] is True
    assert result["assertion"]["expression"] == "buf != NULL"
    assert "conn.c:456" in result["assertion"]["location"]


# ── 端到端：构建→烧录→诊断 全链路 ────────────────────────────────────────────


def test_nordic_e2e_dry_run_build_flash_diagnose(nordic_zephyr_project, monkeypatch):
    """Nordic 完整干运行链路：west build → west flash / nrfjprog → Zephyr fatal 诊断。

    覆盖三条烧录路径（west flash auto、nrfjprog）和诊断入口，
    验证 platform/chip 在整条链路上的数据流一致性。
    """
    # ── 阶段 1：构建 ──
    build_calls = []
    monkeypatch.setattr(firmware_builder.shutil, "which",
                        lambda name: "/usr/bin/west" if name == "west" else None)

    def fake_build(cmd, cwd, timeout=300):
        build_calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_build)

    build_result = build_firmware(str(nordic_zephyr_project), platform="nordic", chip="nRF52840")
    assert build_result["success"] is True
    assert ["west", "build", "-b", "nrf52840dk_nrf52840", str(nordic_zephyr_project)] in build_calls

    # ── 阶段 2a：west flash ──
    west_calls = []
    monkeypatch.setattr(firmware_flasher.shutil, "which",
                        lambda name: "/usr/bin/west" if name == "west" else None)

    def fake_west(cmd, cwd, timeout=300):
        west_calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_flasher, "_run_command", fake_west)

    west_result = flash_firmware(
        project_path=str(nordic_zephyr_project),
        port="",
        method="auto",
        platform="nordic",
        chip="nRF52840",
    )
    assert west_result["success"] is True
    assert "--build-dir" in " ".join(west_calls[0])

    # ── 阶段 2b：nrfjprog ──
    build_dir = nordic_zephyr_project / "build" / "zephyr"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "zephyr.hex").write_text(":00000001FF\n")

    nrf_calls = []
    monkeypatch.setattr(firmware_flasher.shutil, "which",
                        lambda name: "/usr/bin/nrfjprog" if name == "nrfjprog" else None)

    def fake_nrf(cmd, **_kwargs):
        nrf_calls.append(cmd)
        return Completed()

    monkeypatch.setattr("agent.tools.nrfjprog_flasher.subprocess.run", fake_nrf)

    nrf_result = flash_firmware(
        project_path=str(nordic_zephyr_project),
        port="",
        method="nrfjprog",
        platform="nordic",
        chip="nRF52840",
    )
    assert nrf_result["success"] is True
    assert nrf_calls[0][0] == "nrfjprog"
    assert "NRF52" in nrf_calls[0]

    # ── 阶段 3：诊断 ──
    diag = diagnose_nordic_log(
        "***** HARD FAULT *****\n"
        "  Fault escalation (see below)\n"
        "Fatal error 3: Kernel oops on CPU 0\n"
    )
    assert diag["success"] is True
    assert diag["fault"]["fatal_error"] == 3
    assert "Kernel oops" in diag["summary"]
