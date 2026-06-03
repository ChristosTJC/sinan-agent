from agent.tools.nordic_diagnostics import diagnose_nordic_log


def test_detects_zephyr_fatal_error():
    log = """
    ***** HARD FAULT *****
      Fault escalation (see below)
    ***** BUS FAULT *****
    r0/a1:  0x00000000  r1/a2:  0x20000100
    Fatal error 3: Kernel oops on CPU 0
    """

    result = diagnose_nordic_log(log)

    assert result["success"] is True
    assert result["fault"]["type"] == "HARD FAULT"
    assert result["fault"]["fatal_error"] == 3
    assert "Kernel oops" in result["summary"]


def test_detects_zephyr_assertion():
    log = "ASSERTION FAIL [buf != NULL] @ WEST_TOPDIR/zephyr/subsys/bluetooth/host/conn.c:123\n"

    result = diagnose_nordic_log(log)

    assert result["success"] is True
    assert result["assertion"]["expression"] == "buf != NULL"
    assert result["assertion"]["location"].endswith("conn.c:123")


def test_detects_watchdog_reset_reason():
    log = "Reset reason: 0x00000002 (DOG)\n"

    result = diagnose_nordic_log(log)

    assert result["success"] is True
    assert result["reset"]["reason"] == "DOG"
    assert any("watchdog" in hint.lower() for hint in result["hints"])


def test_empty_nordic_log_returns_failure():
    result = diagnose_nordic_log("")

    assert result["success"] is False
    assert "日志为空" in result["error"]
