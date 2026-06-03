"""Additional direct coverage for firmware flashing helpers."""

from __future__ import annotations

import types

from agent.tools import firmware_flasher
from agent.tools.firmware_flasher import (
    detect_flash_method,
    flash_firmware,
    get_bootloader_info,
    verify_flash,
)
from tests.conftest import Completed


def test_detect_flash_method_prefers_project_specific_markers(tmp_path):
    (tmp_path / "openocd.cfg").write_text("source board.cfg\n")
    assert detect_flash_method(str(tmp_path)) == "openocd"

    (tmp_path / "openocd.cfg").unlink()
    (tmp_path / "flash.jlink").write_text("r\n")
    assert detect_flash_method(str(tmp_path)) == "jlink"

    (tmp_path / "flash.jlink").unlink()
    (tmp_path / "platformio.ini").write_text("[env]\nplatform = espressif32\n")
    assert detect_flash_method(str(tmp_path)) == "esptool"


def test_get_bootloader_info_detects_esp32_rom(monkeypatch):
    class FakeSerial:
        in_waiting = 32

        def __init__(self, **_kwargs):
            self.closed = False

        def send_break(self, _duration):
            return None

        def write(self, _data):
            return 4

        def flush(self):
            return None

        def read(self, _size):
            return b"waiting for download"

        def close(self):
            self.closed = True

    fake_serial = types.SimpleNamespace(Serial=FakeSerial, SerialException=OSError)
    monkeypatch.setitem(__import__("sys").modules, "serial", fake_serial)
    monkeypatch.setattr(firmware_flasher.time, "sleep", lambda _seconds: None)

    info = get_bootloader_info("/dev/ttyUSB0")

    assert info["in_bootloader"] is True
    assert info["bootloader_type"] == "ESP32 ROM"
    assert info["recommended_tool"] == "esptool"


def test_flash_firmware_rejects_unknown_method(tmp_path):
    result = flash_firmware(str(tmp_path), "/dev/ttyUSB0", method="mystery")

    assert result["success"] is False
    assert "不支持" in result["errors"][0]


def test_flash_platformio_builds_upload_command(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(firmware_flasher.shutil, "which", lambda name: "/usr/bin/pio" if name == "pio" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append((cmd, cwd, timeout))
        return Completed(stdout="uploaded")

    monkeypatch.setattr(firmware_flasher, "_run_command", fake_run)

    result = flash_firmware(str(tmp_path), "/dev/ttyUSB0", method="platformio")

    assert result["success"] is True
    assert calls[0][0] == ["pio", "run", "-d", str(tmp_path), "-t", "upload", "--upload-port", "/dev/ttyUSB0"]


def test_flash_esptool_finds_bootloader_partition_and_firmware(tmp_path, monkeypatch):
    build = tmp_path / "build"
    build.mkdir()
    firmware = build / "firmware.bin"
    bootloader = build / "bootloader.bin"
    partition = build / "partition-table.bin"
    for path in (firmware, bootloader, partition):
        path.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(
        firmware_flasher.shutil,
        "which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_flasher, "_run_command", fake_run)

    result = flash_firmware(str(tmp_path), "/dev/ttyUSB0", method="esptool", chip="esp32s3")

    assert result["success"] is True
    cmd = calls[0]
    assert cmd[:6] == ["/usr/bin/esptool.py", "--port", "/dev/ttyUSB0", "--chip", "esp32s3", "write_flash"]
    assert ["0x1000", str(bootloader)] == cmd[6:8]
    assert ["0x8000", str(partition)] == cmd[8:10]
    assert ["0x10000", str(firmware)] == cmd[10:12]


def test_flash_stm32cubeprog_finds_hex_and_runs_verify_reset(tmp_path, monkeypatch):
    firmware = tmp_path / "build" / "app.hex"
    firmware.parent.mkdir()
    firmware.write_text(":00000001FF\n")
    calls = []
    monkeypatch.setattr(
        firmware_flasher.shutil,
        "which",
        lambda name: "/usr/bin/STM32_Programmer_CLI" if name == "STM32_Programmer_CLI" else None,
    )
    monkeypatch.setattr(firmware_flasher, "_run_command", lambda cmd, cwd, timeout=300: calls.append(cmd) or Completed())

    result = flash_firmware(str(tmp_path), "", method="stm32cubeprog")

    assert result["success"] is True
    assert calls[0] == [
        "/usr/bin/STM32_Programmer_CLI",
        "-c",
        "port=SWD",
        "-w",
        str(firmware),
        "-v",
        "-rst",
    ]


def test_flash_openocd_uses_board_config_and_firmware(tmp_path, monkeypatch):
    board_dir = tmp_path / "board"
    board_dir.mkdir()
    cfg = board_dir / "openocd.cfg"
    cfg.write_text("source target.cfg\n")
    firmware = tmp_path / "build" / "app.elf"
    firmware.parent.mkdir()
    firmware.write_text("elf")
    calls = []
    monkeypatch.setattr(firmware_flasher.shutil, "which", lambda name: "/usr/bin/openocd" if name == "openocd" else None)
    monkeypatch.setattr(firmware_flasher, "_run_command", lambda cmd, cwd, timeout=300: calls.append(cmd) or Completed())

    result = flash_firmware(str(tmp_path), "", method="openocd")

    assert result["success"] is True
    assert calls[0] == ["/usr/bin/openocd", "-f", str(cfg), "-c", f"program {firmware} verify reset exit"]


def test_flash_arduino_uses_detected_fqbn(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        firmware_flasher.shutil,
        "which",
        lambda name: "/usr/bin/arduino-cli" if name == "arduino-cli" else None,
    )
    monkeypatch.setattr("agent.tools.firmware_builder._detect_arduino_fqbn", lambda _path: "arduino:avr:uno")
    monkeypatch.setattr(firmware_flasher, "_run_command", lambda cmd, cwd, timeout=300: calls.append(cmd) or Completed())

    result = flash_firmware(str(tmp_path), "/dev/ttyACM0", method="arduino")

    assert result["success"] is True
    assert calls[0] == [
        "arduino-cli",
        "upload",
        "-p",
        "/dev/ttyACM0",
        "--fqbn",
        "arduino:avr:uno",
        str(tmp_path),
    ]


def test_flash_jlink_generates_temporary_script_and_cleans_it(tmp_path, monkeypatch):
    firmware = tmp_path / "app.hex"
    firmware.write_text(":00000001FF\n")
    calls = []
    created_scripts = []
    monkeypatch.setattr(firmware_flasher.shutil, "which", lambda name: "/usr/bin/JLinkExe" if name == "JLinkExe" else None)
    monkeypatch.setattr(firmware_flasher, "_run_command", lambda cmd, cwd, timeout=300: calls.append(cmd) or Completed())

    original_named_temp = firmware_flasher.NamedTemporaryFile if hasattr(firmware_flasher, "NamedTemporaryFile") else None

    result = flash_firmware(str(tmp_path), "STM32F407VE", method="jlink")

    assert result["success"] is True
    assert calls[0][0] == "/usr/bin/JLinkExe"
    script_path = calls[0][-1]
    created_scripts.append(script_path)
    assert "-CommanderScript" in calls[0]
    assert not firmware_flasher.Path(script_path).exists()
    assert original_named_temp is None


def test_flash_jlink_uses_existing_script(tmp_path, monkeypatch):
    script = tmp_path / "flash.jlink"
    script.write_text("r\n")
    calls = []
    monkeypatch.setattr(firmware_flasher.shutil, "which", lambda name: "/usr/bin/JLinkExe" if name == "JLinkExe" else None)
    monkeypatch.setattr(firmware_flasher, "_run_command", lambda cmd, cwd, timeout=300: calls.append(cmd) or Completed())

    result = flash_firmware(str(tmp_path), "", method="jlink")

    assert result["success"] is True
    assert calls[0] == ["/usr/bin/JLinkExe", "-CommanderScript", str(script)]


def test_verify_flash_esptool_runs_verify_command(tmp_path, monkeypatch):
    (tmp_path / "platformio.ini").write_text("platform = espressif32\n")
    firmware = tmp_path / ".pio" / "build" / "env" / "firmware.bin"
    firmware.parent.mkdir(parents=True)
    firmware.write_bytes(b"fw")
    calls = []
    monkeypatch.setattr(
        firmware_flasher.shutil,
        "which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    monkeypatch.setattr(firmware_flasher, "_run_command", lambda cmd, cwd, timeout=300: calls.append(cmd) or Completed())

    result = verify_flash(str(tmp_path), "/dev/ttyUSB0")

    assert result["verified"] is True
    assert calls[0] == ["/usr/bin/esptool.py", "--port", "/dev/ttyUSB0", "verify_flash", "--diff", "yes", str(firmware)]


def test_verify_flash_reports_missing_esptool(tmp_path, monkeypatch):
    (tmp_path / "platformio.ini").write_text("platform = espressif32\n")
    monkeypatch.setattr(firmware_flasher.shutil, "which", lambda _name: None)

    result = verify_flash(str(tmp_path), "/dev/ttyUSB0")

    assert result["verified"] is False
    assert "esptool.py 未安装" in result["errors"]


def test_verify_flash_openocd_runs_verify_image(tmp_path, monkeypatch):
    (tmp_path / "openocd.cfg").write_text("source target.cfg\n")
    firmware = tmp_path / "app.elf"
    firmware.write_text("elf")
    calls = []
    monkeypatch.setattr(firmware_flasher.shutil, "which", lambda name: "/usr/bin/openocd" if name == "openocd" else None)
    monkeypatch.setattr(firmware_flasher, "_run_command", lambda cmd, cwd, timeout=300: calls.append(cmd) or Completed())

    result = verify_flash(str(tmp_path), "")

    assert result["verified"] is True
    assert calls[0] == [
        "/usr/bin/openocd",
        "-f",
        str(tmp_path / "openocd.cfg"),
        "-c",
        f"verify_image {firmware}",
        "-c",
        "reset",
        "-c",
        "exit",
    ]


def test_verify_flash_returns_notice_for_methods_without_python_verify(tmp_path):
    (tmp_path / "blink.ino").write_text("void setup() {}\n")

    result = verify_flash(str(tmp_path), "/dev/ttyACM0")

    assert result["verified"] is True
    assert "暂不支持" in result["errors"][0]
