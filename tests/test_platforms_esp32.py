from agent.platforms.esp32 import ESP32Platform, detect_esp32_variant


def test_detect_esp32s3_variant():
    variant = detect_esp32_variant("ESP32-S3-WROOM-1")

    assert variant is not None
    assert variant.family == "ESP32"
    assert variant.series == "S3"
    assert variant.model == "ESP32-S3"
    assert variant.metadata["idf_target"] == "esp32s3"


def test_esp32_generates_idf_build_and_flash_commands():
    platform = ESP32Platform()

    build_cmd = platform.generate_build_command("/project", "ESP32-S3")
    assert "idf.py" in build_cmd
    assert "set-target esp32s3" in build_cmd
    assert "build" in build_cmd

    flash_cmd = platform.generate_flash_command(
        firmware_path="",
        variant="ESP32-S3",
        port="/dev/ttyUSB0",
    )
    assert "idf.py" in flash_cmd
    assert "-p /dev/ttyUSB0" in flash_cmd
    assert "flash" in flash_cmd
