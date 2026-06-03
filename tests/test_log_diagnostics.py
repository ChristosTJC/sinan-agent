from agent.tools.log_diagnostics import diagnose_log


def test_auto_detects_esp32_log():
    result = diagnose_log("Guru Meditation Error: Core  0 panic'ed (StoreProhibited).")

    assert result["success"] is True
    assert result["platform"] == "esp32"
    assert result["diagnostic"]["panic"]["reason"] == "StoreProhibited"


def test_auto_detects_stm32_log():
    result = diagnose_log("HardFault_Handler entered\nHFSR=0x40000000\n")

    assert result["success"] is True
    assert result["platform"] == "stm32"
    assert result["diagnostic"]["fault"]["type"] == "HardFault"


def test_auto_detects_nordic_zephyr_log():
    result = diagnose_log("Fatal error 3: Kernel oops on CPU 0\n")

    assert result["success"] is True
    assert result["platform"] == "nordic"
    assert result["diagnostic"]["fault"]["fatal_error"] == 3


def test_unknown_log_returns_no_match():
    result = diagnose_log("hello world\n")

    assert result["success"] is True
    assert result["platform"] == "unknown"
    assert result["diagnostic"] is None
