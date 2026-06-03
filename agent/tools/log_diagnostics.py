"""Generic embedded serial log diagnostics router."""

from __future__ import annotations

from typing import Any, Optional

from agent.tools.esp32_diagnostics import diagnose_esp32_log
from agent.tools.nordic_diagnostics import diagnose_nordic_log
from agent.tools.stm32_diagnostics import diagnose_stm32_log


def diagnose_log(log: str, platform: Optional[str] = None) -> dict[str, Any]:
    """Diagnose a serial log, auto-detecting the embedded platform when omitted."""
    if not log or not log.strip():
        return {"success": False, "error": "日志为空，无法诊断"}

    selected = (platform or _detect_platform(log)).lower()
    if selected in ("esp32", "esp", "espressif"):
        return {"success": True, "platform": "esp32", "diagnostic": diagnose_esp32_log(log)}
    if selected in ("stm32", "st"):
        return {"success": True, "platform": "stm32", "diagnostic": diagnose_stm32_log(log)}
    if selected in ("nordic", "nrf", "zephyr"):
        return {"success": True, "platform": "nordic", "diagnostic": diagnose_nordic_log(log)}

    return {
        "success": True,
        "platform": "unknown",
        "diagnostic": None,
        "summary": "未识别出已支持的平台日志特征",
    }


def _detect_platform(log: str) -> str:
    lowered = log.lower()
    if "guru meditation" in lowered or "brownout detector" in lowered or "rst:" in lowered:
        return "esp32"
    if "hardfault" in lowered or "hal_timeout" in lowered or "hal_error" in lowered or "no stm32 target" in lowered:
        return "stm32"
    if "fatal error" in lowered or "assertion fail" in lowered or "zephyr" in lowered or "kernel oops" in lowered:
        return "nordic"
    return "unknown"
