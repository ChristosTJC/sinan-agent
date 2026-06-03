"""agent/workflows/hardware_golden_path.py 集成测试。

覆盖:
- detect_board: 板卡检测（有设备 / 无端口 / 扫描失败）
- build_firmware: 编译阶段
- flash_firmware: 烧写阶段（成功 / 失败 / 缺 port）
- verify_firmware: 串口验证（检测到引导 / 未检测 / 缺 port）
- run 完整黄金路径
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agent.tools import DangerLevel
from agent.workflows.hardware_golden_path import HardwareGoldenPath


# ---------------------------------------------------------------------------
# FakeRegistry（复用 conftest 模式，额外支持 serial_monitor）
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_registry():
    """创建可配置响应的 FakeRegistry。"""
    from tests.conftest import FakeRegistry

    reg = FakeRegistry()
    # 注入 verify_firmware 所需的 serial_monitor 默认响应
    reg.responses["serial_monitor"] = {
        "success": True,
        "lines": ["Boot", "init done", "system ready"],
    }
    return reg


# ---------------------------------------------------------------------------
# detect_board
# ---------------------------------------------------------------------------


class TestDetectBoard:
    def test_with_connected_device(self, fake_registry, monkeypatch):
        """检测到 ttyUSB0 且 identify_board 返回 STM32 时，应返回成功。"""
        fake_registry.responses["scan_serial"] = {
            "success": True,
            "result": [{"port": "/dev/ttyUSB0"}],
        }
        monkeypatch.setattr(
            "agent.workflows.hardware_golden_path.identify_board",
            lambda _: "STM32",
        )

        path = HardwareGoldenPath(registry=fake_registry)
        result = path.detect_board()

        assert result["success"] is True
        assert result["board_type"] == "STM32"
        assert "/dev/ttyUSB0" in result["ports"]

    def test_no_serial_ports(self, fake_registry):
        """无串口时应返回错误。"""
        fake_registry.responses["scan_serial"] = {
            "success": True,
            "result": [],
        }

        path = HardwareGoldenPath(registry=fake_registry)
        result = path.detect_board()

        assert result["success"] is False
        assert "未检测到" in result.get("error", "")

    def test_scan_failure(self, fake_registry):
        """串口扫描工具返回失败时应传播错误。"""
        fake_registry.responses["scan_serial"] = {
            "success": False,
            "error": "串口权限不足",
        }

        path = HardwareGoldenPath(registry=fake_registry)
        result = path.detect_board()

        assert result["success"] is False
        assert "串口权限不足" in result.get("error", "")

    def test_with_vid_pid_enriched(self, fake_registry, monkeypatch):
        """检测板卡时应同时获取 USB VID/PID 信息。"""
        fake_registry.responses["scan_serial"] = {
            "success": True,
            "result": [{"port": "/dev/ttyACM0"}],
        }
        fake_registry.responses["scan_usb"] = {
            "success": True,
            "result": [{"vid": "0483", "pid": "5740"}],
        }
        monkeypatch.setattr(
            "agent.workflows.hardware_golden_path.identify_board",
            lambda _: None,
        )

        path = HardwareGoldenPath(registry=fake_registry)
        result = path.detect_board()

        assert result["success"] is True
        assert result["vid_pid"] is not None
        assert len(result["vid_pid"]) == 1


# ---------------------------------------------------------------------------
# build_firmware
# ---------------------------------------------------------------------------


class TestBuildFirmware:
    def test_success(self, fake_registry):
        fake_registry.responses["build_firmware"] = {"success": True, "output": "BUILD OK"}
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.build_firmware("/fake/project")
        assert result["success"] is True

    def test_failure(self, fake_registry):
        fake_registry.responses["build_firmware"] = {"success": False, "output": "error", "errors": ["link error"]}
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.build_firmware("/fake/project")
        assert result["success"] is False
        assert "link error" in result.get("errors", [])


# ---------------------------------------------------------------------------
# flash_firmware
# ---------------------------------------------------------------------------


class TestFlashFirmware:
    def test_success(self, fake_registry):
        fake_registry.responses["flash_firmware"] = {"success": True, "output": "FLASH OK"}
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.flash_firmware("/fake/project", "/dev/ttyUSB0")
        assert result["success"] is True

    def test_missing_port(self, fake_registry):
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.flash_firmware("/fake/project", "")
        assert result["success"] is False
        assert "port" in str(result.get("errors", "")).lower()

    def test_failure(self, fake_registry):
        fake_registry.responses["flash_firmware"] = {"success": False, "output": "", "errors": ["verify failed"]}
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.flash_firmware("/fake/project", "/dev/ttyUSB0")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# verify_firmware
# ---------------------------------------------------------------------------


class TestVerifyFirmware:
    def test_boot_detected(self, fake_registry):
        fake_registry.responses["serial_monitor"] = {
            "success": True,
            "lines": ["Boot", "init done", "system ready"],
        }
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.verify_firmware("/dev/ttyUSB0")
        assert result["boot_detected"] is True
        assert result["success"] is True

    def test_no_boot_detected(self, fake_registry):
        fake_registry.responses["serial_monitor"] = {
            "success": True,
            "lines": ["garbage", "random", "noise"],
        }
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.verify_firmware("/dev/ttyUSB0")
        assert result["boot_detected"] is False
        assert result["success"] is True  # 工具调用成功，只是没匹配到引导

    def test_missing_port(self, fake_registry):
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.verify_firmware("")
        assert result["success"] is False
        assert "port" in str(result.get("error", "")).lower()

    def test_monitor_failure(self, fake_registry):
        fake_registry.responses["serial_monitor"] = {
            "success": False,
            "error": "无法打开串口",
        }
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.verify_firmware("/dev/ttyUSB0")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# run — 完整流水线
# ---------------------------------------------------------------------------


class TestRunFull:
    def test_run_full_success(self, fake_registry, monkeypatch, tmp_path):
        """完整黄金路径：检测 → 编译 → 烧写 → 验证 全部成功。"""
        project = tmp_path / "fw"
        project.mkdir()
        (project / "CMakeLists.txt").write_text("project(test)")

        fake_registry.responses["scan_serial"] = {
            "success": True,
            "result": [{"port": "/dev/ttyUSB0"}],
        }
        fake_registry.responses["scan_usb"] = {
            "success": True,
            "result": [],
        }
        fake_registry.responses["build_firmware"] = {"success": True, "output": ""}
        fake_registry.responses["flash_firmware"] = {"success": True, "output": ""}
        fake_registry.responses["serial_monitor"] = {
            "success": True,
            "lines": ["Boot OK", "init done"],
        }

        monkeypatch.setattr(
            "agent.workflows.hardware_golden_path.identify_board",
            lambda _: "STM32",
        )
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.run(str(project))

        assert result["success"] is True
        assert result.get("phases")
        verify_phase = [p for p in result["phases"] if p["phase"] == "verify"][0]
        assert verify_phase["status"] == "ok"
        assert result["total_duration_ms"] > 0

    def test_run_fails_at_detect(self, fake_registry):
        """板卡检测失败时应终止流水线，不进入编译。"""
        fake_registry.responses["scan_serial"] = {
            "success": False,
            "error": "无串口权限",
        }
        path = HardwareGoldenPath(registry=fake_registry)
        result = path.run("/fake/project")
        assert result["success"] is False
        # 编译和烧写阶段不应被调用
        build_calls = [c for c in fake_registry.calls if c[0] == "build_firmware"]
        assert len(build_calls) == 0
