import subprocess

from agent.tools import firmware_builder
from agent.tools.firmware_builder import build_firmware


class Completed:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_build_firmware_uses_esp_idf_when_sdkconfig_present(tmp_path, monkeypatch):
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n")
    (tmp_path / "sdkconfig").write_text('CONFIG_IDF_TARGET="esp32s3"\n')
    calls = []

    monkeypatch.setattr(firmware_builder.shutil, "which", lambda name: "/usr/bin/idf.py" if name == "idf.py" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(tmp_path), platform="esp32", chip="ESP32-S3")

    assert result["success"] is True
    assert calls == [["idf.py", "set-target", "esp32s3"], ["idf.py", "build"]]


def test_build_firmware_uses_west_for_nordic_zephyr_project(tmp_path, monkeypatch):
    (tmp_path / "CMakeLists.txt").write_text("find_package(Zephyr REQUIRED)\n")
    calls = []

    monkeypatch.setattr(firmware_builder.shutil, "which", lambda name: "/usr/bin/west" if name == "west" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(tmp_path), platform="nordic", chip="nRF52840")

    assert result["success"] is True
    assert calls == [["west", "build", "-b", "nrf52840dk_nrf52840", str(tmp_path)]]


def test_build_firmware_adds_stm32_cmake_definitions(tmp_path, monkeypatch):
    (tmp_path / "CMakeLists.txt").write_text("project(stm32_app C)\n")
    calls = []

    monkeypatch.setattr(firmware_builder.shutil, "which", lambda name: "/usr/bin/cmake" if name == "cmake" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(tmp_path), platform="stm32", chip="STM32F407VG")

    assert result["success"] is True
    configure_cmd = calls[0]
    assert "-DCHIP=STM32F407VG" in configure_cmd
    assert "-DCMAKE_SYSTEM_PROCESSOR=cortex-m4" in configure_cmd


def test_build_firmware_fails_when_no_build_system_detected(tmp_path):
    result = build_firmware(str(tmp_path))

    assert result["success"] is False
    assert len(result["errors"]) == 1
    assert "未检测到已知构建系统" in result["errors"][0]


def test_build_firmware_detects_platformio(tmp_path, monkeypatch):
    (tmp_path / "platformio.ini").write_text("[env:esp32]\nboard = esp32dev\n")
    calls = []

    monkeypatch.setattr(firmware_builder.shutil, "which", lambda name: "/usr/bin/pio" if name == "pio" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(tmp_path))

    assert result["success"] is True
    assert calls == [["pio", "run", "-d", str(tmp_path)]]


def test_build_firmware_detects_arduino(tmp_path, monkeypatch):
    (tmp_path / "blink.ino").write_text("void setup() {}\nvoid loop() {}\n")
    calls = []

    monkeypatch.setenv("ARDUINO_FQBN", "arduino:avr:uno")
    monkeypatch.setattr(firmware_builder.shutil, "which", lambda name: "/usr/bin/arduino-cli" if name == "arduino-cli" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(tmp_path))

    assert result["success"] is True
    assert calls[0][0] == "arduino-cli"
    assert "--fqbn" in calls[0]
    assert "compile" in calls[0]


def test_build_firmware_detects_make(tmp_path, monkeypatch):
    (tmp_path / "Makefile").write_text("all:\n\t@echo ok\n")
    calls = []

    monkeypatch.setattr(firmware_builder.shutil, "which", lambda name: "/usr/bin/make" if name == "make" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(tmp_path))

    assert result["success"] is True
    assert calls == [["make", "-C", str(tmp_path)]]


def test_build_firmware_cmake_build_dir(tmp_path, monkeypatch):
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\nproject(test C)\n")
    calls = []

    monkeypatch.setattr(firmware_builder.shutil, "which", lambda name: "/usr/bin/cmake" if name == "cmake" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(tmp_path))

    assert result["success"] is True
    assert calls[0] == ["cmake", "-B", "build", "-S", "."]
    assert calls[1][0:2] == ["cmake", "--build"]
    assert calls[1][2].endswith("build")


def test_build_firmware_subprocess_failure(tmp_path, monkeypatch):
    (tmp_path / "Makefile").write_text("all:\n\t@exit 1\n")

    monkeypatch.setattr(firmware_builder.shutil, "which", lambda name: "/usr/bin/make" if name == "make" else None)

    def fake_run(cmd, cwd, timeout=300):
        return Completed(returncode=1, stdout="", stderr="make: *** [all] Error 1")

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(tmp_path))

    assert result["success"] is False
    assert len(result["errors"]) > 0


def test_build_firmware_missing_tool(tmp_path, monkeypatch):
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\nproject(test C)\n")

    monkeypatch.setattr(firmware_builder.shutil, "which", lambda name: None)

    result = build_firmware(str(tmp_path))

    assert result["success"] is False
    assert "CMake 未安装" in result["errors"][0]


def test_build_firmware_with_force_flag(tmp_path, monkeypatch):
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\nproject(test C)\n")
    calls = []

    monkeypatch.setattr(firmware_builder.shutil, "which", lambda name: "/usr/bin/cmake" if name == "cmake" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_builder, "_run_command", fake_run)

    result = build_firmware(str(tmp_path), force=True)

    assert result["success"] is True
    assert "--clean-first" in calls[1]
