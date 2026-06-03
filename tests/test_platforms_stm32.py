from agent.platforms.stm32 import STM32Platform, detect_stm32_variant


def test_detect_stm32f407_variant():
    variant = detect_stm32_variant("STM32F407VGT6")

    assert variant is not None
    assert variant.family == "STM32"
    assert variant.series == "F4"
    assert variant.model == "STM32F407"
    assert variant.flash_size_kb == 1024
    assert variant.ram_size_kb == 192


def test_stm32_generates_cmake_definitions_and_openocd_flash():
    platform = STM32Platform()

    assert platform.get_cmake_definitions("STM32F407VG") == {
        "CHIP": "STM32F407VG",
        "MCU_FAMILY": "STM32F4",
        "CMAKE_SYSTEM_PROCESSOR": "cortex-m4",
    }

    flash_cmd = platform.generate_flash_command(
        firmware_path="build/firmware.elf",
        variant="STM32F407VG",
        tool="openocd",
    )
    assert "openocd" in flash_cmd
    assert "target/stm32f4x.cfg" in flash_cmd
    assert "program build/firmware.elf verify reset exit" in flash_cmd
