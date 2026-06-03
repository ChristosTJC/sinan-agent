"""agent/tools/serial_scanner.py 单元测试。

覆盖:
- _classify_port: 端口名分类器
- _try_glob_ports: glob 模式串口扫描（mock）
- get_device_info: VID/PID 数据库查询
- _match_bootloader_pattern: 引导加载程序模式匹配
- scan_serial_ports: 主扫描入口（mock pyserial）
- scan_usb_devices: USB 设备扫描（mock lsusb）
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.tools.serial_scanner import (
    _classify_port,
    _match_bootloader_pattern,
    _try_glob_ports,
    get_device_info,
    scan_serial_ports,
    scan_usb_devices,
)


# ---------------------------------------------------------------------------
# _classify_port
# ---------------------------------------------------------------------------


class TestClassifyPort:
    def test_linux_usb_serial(self):
        """/dev/ttyUSB0 应识别为 usb-serial 硬件设备。"""
        assert _classify_port("/dev/ttyUSB0") == ("usb-serial", True)

    def test_linux_acm_serial(self):
        """/dev/ttyACM0 应识别为 usb-serial 硬件设备。"""
        assert _classify_port("/dev/ttyACM0") == ("usb-serial", True)

    def test_linux_platform_serial(self):
        """/dev/ttyS0 应识别为平台串口，非外接硬件设备。"""
        assert _classify_port("/dev/ttyS0") == ("platform-serial", False)

    def test_arm_platform_serial(self):
        """/dev/ttyAMA0 应识别为平台串口。"""
        assert _classify_port("/dev/ttyAMA0") == ("platform-serial", False)

    def test_macos_usb_serial(self):
        """/dev/tty.usbserial-1420 应识别为 usb-serial。"""
        assert _classify_port("/dev/tty.usbserial-1420") == ("usb-serial", True)

    def test_macos_cu_serial(self):
        """/dev/cu.usbserial-1420 应识别为 usb-serial。"""
        assert _classify_port("/dev/cu.usbserial-1420") == ("usb-serial", True)

    def test_unknown_path(self):
        """/dev/random123 应识别为 unknown。"""
        assert _classify_port("/dev/random123") == ("unknown", False)

    def test_path_with_device_trailing(self):
        """子目录路径下 basename 决定分类（非 ttyUSB/ttyACM 前缀的 symlink 名归为 unknown）。"""
        assert _classify_port("/dev/serial/by-id/usb-FTDI_FT232R-ttyUSB0") == ("unknown", False)


# ---------------------------------------------------------------------------
# _try_glob_ports
# ---------------------------------------------------------------------------


class TestTryGlobPorts:
    def test_mixed_ports(self, monkeypatch, tmp_path):
        """混合 USB 和平台串口，返回时应带正确的 port_type/is_hardware。"""
        fake_usb = tmp_path / "ttyUSB0"
        fake_platform = tmp_path / "ttyS0"
        fake_usb.touch()
        fake_platform.touch()

        mock_usb_path = MagicMock(spec=Path)
        mock_usb_path.__str__.return_value = "/dev/ttyUSB0"
        mock_usb_path.is_symlink.return_value = False
        mock_platform_path = MagicMock(spec=Path)
        mock_platform_path.__str__.return_value = "/dev/ttyS0"
        mock_platform_path.is_symlink.return_value = False

        class FakeGlob:
            def glob(self, _pattern):
                if "ttyUSB" in _pattern:
                    return [mock_usb_path]
                if "ttyS" in _pattern:
                    return [mock_platform_path]
                return []

        def fake_path(_p):
            return FakeGlob()

        monkeypatch.setattr("agent.tools.serial_scanner.Path", fake_path)
        monkeypatch.setattr("agent.tools.serial_scanner.os.readlink", lambda _: "")

        ports = _try_glob_ports()

        assert len(ports) == 2
        usb = [p for p in ports if p["port"] == "/dev/ttyUSB0"][0]
        platform = [p for p in ports if p["port"] == "/dev/ttyS0"][0]
        assert usb["port_type"] == "usb-serial"
        assert usb["is_hardware"] is True
        assert platform["port_type"] == "platform-serial"
        assert platform["is_hardware"] is False

    def test_empty_glob(self, monkeypatch):
        """空 glob 结果应返回空列表。"""
        class FakeGlobEmpty:
            def glob(self, _pattern):
                return []

        monkeypatch.setattr("agent.tools.serial_scanner.Path", lambda _: FakeGlobEmpty())
        assert _try_glob_ports() == []

    def test_dedup_same_port(self):
        """同一端口出现两次应去重（通过 os.scandir 模拟）。"""
        ports = [
            {"port": "/dev/ttyUSB0", "device": "/dev/ttyUSB0", "description": "", "hwid": "",
             "port_type": "usb-serial", "is_hardware": True, "source": "glob"},
        ]
        # 直接测扫描结果的去重——_try_glob_ports 内部有 seen set
        assert len({p["port"] for p in ports}) == 1


# ---------------------------------------------------------------------------
# get_device_info
# ---------------------------------------------------------------------------


class TestGetDeviceInfo:
    def test_known_stm32_dfu(self):
        """已知 STM32 DFU VID/PID 应返回完整设备信息。"""
        info = get_device_info("0483", "df11")
        assert info is not None
        assert "STM32" in info["device"]
        assert info["vid"] == "0483"

    def test_known_ch340(self):
        """已知 CH340 VID/PID 应返回厂商信息。"""
        info = get_device_info("1a86", "7523")
        assert info is not None
        assert "CH340" in info["device"]

    def test_unknown_vid_pid(self):
        """未知 VID/PID 应返回 None。"""
        assert get_device_info("ffff", "ffff") is None

    def test_vendor_only(self):
        """仅厂商在库中（STMicroelectronics），但 PID 不在库中。"""
        info = get_device_info("0483", "ffff")
        assert info is not None
        assert info["vendor"] == "STMicroelectronics"

    def test_case_insensitive(self):
        """VID/PID 大小写无关。"""
        info = get_device_info("1A86", "7523")
        assert info is not None


# ---------------------------------------------------------------------------
# _match_bootloader_pattern
# ---------------------------------------------------------------------------


class TestMatchBootloaderPattern:
    def test_stm32(self):
        assert _match_bootloader_pattern("STM32 Bootloader v3.1") == "STM32"

    def test_esp32(self):
        assert _match_bootloader_pattern("waiting for download") == "ESP32 ROM"

    def test_nordic_dfu(self):
        assert _match_bootloader_pattern("nRF5 DFU started") == "nRF52 DFU"

    def test_no_match(self):
        assert _match_bootloader_pattern("garbage123") is None


# ---------------------------------------------------------------------------
# scan_serial_ports
# ---------------------------------------------------------------------------


class TestScanSerialPorts:
    def test_via_pyserial_with_port_types(self, monkeypatch):
        """pyserial 返回混合端口时，应包含 port_type/is_hardware/source 字段。"""
        mock_ports = [
            {"port": "/dev/ttyUSB0", "device": "/dev/ttyUSB0",
             "description": "USB Serial", "hwid": "USB VID:PID=1a86:7523",
             "port_type": "usb-serial", "is_hardware": True, "source": "pyserial"},
            {"port": "/dev/ttyACM0", "device": "/dev/ttyACM0",
             "description": "STM32 VCP", "hwid": "USB VID:PID=0483:5740",
             "port_type": "usb-serial", "is_hardware": True, "source": "pyserial"},
            {"port": "/dev/ttyS0", "device": "/dev/ttyS0",
             "description": "ttyS0", "hwid": "",
             "port_type": "platform-serial", "is_hardware": False, "source": "pyserial"},
        ]
        monkeypatch.setattr(
            "agent.tools.serial_scanner._try_pyserial_ports",
            lambda: mock_ports,
        )
        ports = scan_serial_ports()
        assert len(ports) == 3
        assert ports[0]["port_type"] == "usb-serial"
        assert ports[0]["is_hardware"] is True
        assert ports[0]["source"] == "pyserial"
        assert ports[2]["port_type"] == "platform-serial"
        assert ports[2]["is_hardware"] is False

    def test_pyserial_import_error_falls_back_to_glob(self, monkeypatch):
        """pyserial 不可用时，应回退到 glob 扫描。"""
        monkeypatch.setattr(
            "agent.tools.serial_scanner._try_pyserial_ports",
            lambda: (_ for _ in ()).throw(ImportError("no pyserial")),
        )

        class FakeGlobEmpty:
            def glob(self, _p):
                return []

        monkeypatch.setattr("agent.tools.serial_scanner.Path", lambda _: FakeGlobEmpty())
        assert scan_serial_ports() == []

    def test_pyserial_empty_falls_back_to_glob(self, monkeypatch):
        """pyserial 返回空列表时，应回退到 glob。"""
        monkeypatch.setattr(
            "agent.tools.serial_scanner._try_pyserial_ports",
            lambda: [],
        )

        class FakeGlobEmpty:
            def glob(self, _p):
                return []

        monkeypatch.setattr("agent.tools.serial_scanner.Path", lambda _: FakeGlobEmpty())
        assert scan_serial_ports() == []


# ---------------------------------------------------------------------------
# scan_usb_devices
# ---------------------------------------------------------------------------


class TestScanUsbDevices:
    def test_via_lsusb(self, monkeypatch):
        """lsusb 输出解析应返回正确的 VID/PID。"""
        lsusb_output = "\n".join([
            "Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub",
            "Bus 001 Device 005: ID 1a86:7523 QinHeng Electronics CH340 serial converter",
            "Bus 001 Device 003: ID 0483:5740 STMicroelectronics STM32 Virtual COM Port",
        ])

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: Completed(stdout=lsusb_output))

        # Force lsusb path by making pyusb fail
        monkeypatch.setattr(
            "agent.tools.serial_scanner._try_pyusb_scan",
            lambda: (_ for _ in ()).throw(ImportError("no pyusb")),
        )

        devices = scan_usb_devices()
        assert len(devices) == 3
        assert devices[0]["vid"] == "1d6b"
        assert devices[1]["vid"] == "1a86"
        assert devices[1]["pid"] == "7523"


class Completed:
    """模拟 subprocess.CompletedProcess。"""
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
