from agent.tools.esp32_diagnostics import diagnose_esp32_log


def test_detects_reset_reason_from_rom_boot_line():
    log = """
    rst:0xc (SW_CPU_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)
    configsip: 0, SPIWP:0xee
    """

    result = diagnose_esp32_log(log)

    assert result["success"] is True
    assert result["reset"]["code"] == "0xc"
    assert result["reset"]["reason"] == "SW_CPU_RESET"
    assert result["summary"] == "ESP32 reset: SW_CPU_RESET"


def test_detects_guru_meditation_panic_and_backtrace():
    log = """
    Guru Meditation Error: Core  1 panic'ed (LoadProhibited). Exception was unhandled.
    Core  1 register dump:
    PC      : 0x400d1234  PS      : 0x00060f30  A0      : 0x800d5678
    Backtrace: 0x400d1234:0x3ffb1f20 0x400d5678:0x3ffb1f40 0x40081234:0x3ffb1f70
    """

    result = diagnose_esp32_log(log)

    assert result["success"] is True
    assert result["panic"]["core"] == 1
    assert result["panic"]["reason"] == "LoadProhibited"
    assert result["panic"]["handled"] is False
    assert result["backtrace"] == ["0x400d1234", "0x400d5678", "0x40081234"]
    assert "LoadProhibited" in result["hints"][0]


def test_detects_brownout_as_power_issue():
    result = diagnose_esp32_log("Brownout detector was triggered\n")

    assert result["success"] is True
    assert result["power"]["brownout"] is True
    assert any("供电" in hint for hint in result["hints"])


def test_empty_log_returns_failure():
    result = diagnose_esp32_log("")

    assert result["success"] is False
    assert "日志为空" in result["error"]
