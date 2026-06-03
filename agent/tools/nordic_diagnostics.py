"""Nordic nRF / Zephyr serial log diagnostics."""

from __future__ import annotations

import re
from typing import Any


_FATAL_RE = re.compile(r"Fatal error\s+(?P<code>\d+):\s*(?P<reason>.+)", re.IGNORECASE)
_FAULT_RE = re.compile(r"\*{3,}\s*(?P<type>[A-Z ]+FAULT)\s*\*{3,}", re.IGNORECASE)
_ASSERT_RE = re.compile(r"ASSERTION FAIL\s+\[(?P<expr>.+?)\]\s+@\s+(?P<loc>\S+)")
_RESET_RE = re.compile(r"Reset reason:\s*(?P<code>0x[0-9a-fA-F]+)\s+\((?P<reason>[^)]+)\)", re.IGNORECASE)


def diagnose_nordic_log(log: str) -> dict[str, Any]:
    """Diagnose Nordic/Zephyr fatal errors, assertions, and reset reasons."""
    if not log or not log.strip():
        return {"success": False, "error": "日志为空，无法诊断"}

    result: dict[str, Any] = {
        "success": True,
        "summary": "未发现 Nordic/Zephyr fatal/assert/reset 特征",
        "fault": None,
        "assertion": None,
        "reset": None,
        "hints": [],
    }

    fault = _FAULT_RE.search(log)
    fatal = _FATAL_RE.search(log)
    if fault or fatal:
        fault_type = fault.group("type").strip().upper() if fault else "FATAL ERROR"
        fault_data: dict[str, Any] = {"type": fault_type}
        if fatal:
            fault_data["fatal_error"] = int(fatal.group("code"))
            fault_data["reason"] = fatal.group("reason").strip()
            result["summary"] = f"Nordic/Zephyr fatal: {fault_data['reason']}"
        else:
            result["summary"] = f"Nordic/Zephyr fault: {fault_type}"
        result["fault"] = fault_data
        result["hints"].append("Zephyr fatal/fault 后优先解码 PC/LR 和线程栈，检查栈溢出、NULL 指针和非法中断上下文调用。")

    assertion = _ASSERT_RE.search(log)
    if assertion:
        result["assertion"] = {
            "expression": assertion.group("expr"),
            "location": assertion.group("loc"),
        }
        result["summary"] = f"Zephyr assertion failed: {assertion.group('expr')}"
        result["hints"].append("ASSERTION FAIL 指向 Zephyr 内部或应用前置条件失败，先检查日志给出的文件行。")

    reset = _RESET_RE.search(log)
    if reset:
        reason = reset.group("reason")
        result["reset"] = {
            "code": reset.group("code").lower(),
            "reason": reason,
        }
        result["summary"] = f"Nordic reset: {reason}"
        result["hints"].append(_reset_hint(reason))

    return result


def _reset_hint(reason: str) -> str:
    upper = reason.upper()
    if "DOG" in upper or "WDT" in upper:
        return "Watchdog reset：检查主循环/线程是否喂狗、是否长时间关中断或高优先级任务阻塞。"
    if "PIN" in upper:
        return "Pin reset：检查复位引脚、调试器 reset、按钮抖动和外部复位电路。"
    if "LOCKUP" in upper:
        return "CPU lockup reset：通常与 fault 未处理或异常嵌套有关，结合 fault dump 分析。"
    return f"{reason} reset：结合 Nordic RESETREAS 位定义确认复位来源。"
