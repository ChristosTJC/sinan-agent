from agent.tools.stm32_diagnostics import diagnose_stm32_log


def test_detects_hardfault_and_register_dump():
    log = """
    HardFault_Handler entered
    HFSR=0x40000000 CFSR=0x00008200 MMFAR=0x20000000 BFAR=0x08001234
    """

    result = diagnose_stm32_log(log)

    assert result["success"] is True
    assert result["fault"]["type"] == "HardFault"
    assert result["fault"]["registers"]["HFSR"] == "0x40000000"
    assert result["fault"]["registers"]["CFSR"] == "0x00008200"
    assert "HardFault" in result["summary"]


def test_detects_hal_error_status():
    result = diagnose_stm32_log("I2C read failed: HAL_TIMEOUT\n")

    assert result["success"] is True
    assert result["hal"]["status"] == "HAL_TIMEOUT"
    assert any("超时" in hint for hint in result["hints"])


def test_detects_openocd_target_connection_failure():
    log = "Error: timed out while waiting for target halted\nError: target not halted\n"

    result = diagnose_stm32_log(log)

    assert result["success"] is True
    assert result["debug_probe"]["tool"] == "openocd"
    assert result["debug_probe"]["issue"] == "target_not_halted"
    assert any("SWD" in hint for hint in result["hints"])


def test_detects_cubeprogrammer_no_target():
    result = diagnose_stm32_log("Error: No STM32 target found!\n")

    assert result["success"] is True
    assert result["debug_probe"]["tool"] == "stm32cubeprog"
    assert result["debug_probe"]["issue"] == "no_target"


def test_empty_stm32_log_returns_failure():
    result = diagnose_stm32_log("")

    assert result["success"] is False
    assert "日志为空" in result["error"]
