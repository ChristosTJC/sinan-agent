from agent.tools import firmware_flasher
from agent.tools.firmware_flasher import flash_firmware


class Completed:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_flash_firmware_uses_esp_idf_when_platform_is_esp32(tmp_path, monkeypatch):
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n")
    (tmp_path / "sdkconfig").write_text('CONFIG_IDF_TARGET="esp32s3"\n')
    calls = []

    monkeypatch.setattr(firmware_flasher.shutil, "which", lambda name: "/usr/bin/idf.py" if name == "idf.py" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_flasher, "_run_command", fake_run)

    result = flash_firmware(
        project_path=str(tmp_path),
        port="/dev/ttyUSB0",
        method="auto",
        platform="esp32",
        chip="ESP32-S3",
    )

    assert result["success"] is True
    assert calls == [["idf.py", "-p", "/dev/ttyUSB0", "-DIDF_TARGET=esp32s3", "flash"]]


def test_flash_firmware_uses_west_flash_for_nordic_zephyr_project(tmp_path, monkeypatch):
    (tmp_path / "CMakeLists.txt").write_text("find_package(Zephyr REQUIRED)\n")
    calls = []

    monkeypatch.setattr(firmware_flasher.shutil, "which", lambda name: "/usr/bin/west" if name == "west" else None)

    def fake_run(cmd, cwd, timeout=300):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(firmware_flasher, "_run_command", fake_run)

    result = flash_firmware(
        project_path=str(tmp_path),
        port="",
        method="auto",
        platform="nordic",
        chip="nRF52840",
    )

    assert result["success"] is True
    assert calls == [["west", "flash", "--build-dir", str(tmp_path / "build")]]


def test_flash_firmware_uses_nrfjprog_when_requested(tmp_path, monkeypatch):
    build_dir = tmp_path / "build" / "zephyr"
    build_dir.mkdir(parents=True)
    firmware = build_dir / "zephyr.hex"
    firmware.write_text(":00000001FF\n")
    calls = []

    monkeypatch.setattr(firmware_flasher.shutil, "which", lambda name: "/usr/bin/nrfjprog" if name == "nrfjprog" else None)

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr("agent.tools.nrfjprog_flasher.subprocess.run", fake_run)

    result = flash_firmware(
        project_path=str(tmp_path),
        port="",
        method="nrfjprog",
        platform="nordic",
        chip="nRF52840",
    )

    assert result["success"] is True
    assert calls == [[
        "nrfjprog",
        "--program",
        str(firmware),
        "--family",
        "NRF52",
        "--sectorerase",
        "--verify",
        "--reset",
    ]]
