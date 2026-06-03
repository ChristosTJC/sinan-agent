"""ESP32 serial log diagnostics for panic, reset, and brownout events."""

from __future__ import annotations

import re
from typing import Any


_RESET_RE = re.compile(r"rst:(?P<code>0x[0-9a-fA-F]+)\s+\((?P<reason>[^)]+)\)")
_PANIC_RE = re.compile(
    r"Guru Meditation Error:\s*Core\s+(?P<core>\d+)\s+panic'ed\s+\((?P<reason>[^)]+)\)\.\s*(?P<detail>.*)",
    re.IGNORECASE,
)
_BACKTRACE_RE = re.compile(r"Backtrace:\s*(?P<frames>.+)", re.IGNORECASE)
_ADDR_RE = re.compile(r"0x[0-9a-fA-F]{8}")


def diagnose_esp32_log(log: str) -> dict[str, Any]:
    """Diagnose ESP32 boot, reset, and panic text captured from serial logs."""
    if not log or not log.strip():
        return {"success": False, "error": "日志为空，无法诊断"}

    result: dict[str, Any] = {
        "success": True,
        "summary": "未发现 ESP32 panic/reset 特征",
        "reset": None,
        "panic": None,
        "power": {"brownout": False},
        "backtrace": [],
        "hints": [],
    }

    reset = _RESET_RE.search(log)
    if reset:
        result["reset"] = {
            "code": reset.group("code").lower(),
            "reason": reset.group("reason"),
        }
        result["summary"] = f"ESP32 reset: {reset.group('reason')}"

    panic = _PANIC_RE.search(log)
    if panic:
        detail = panic.group("detail")
        reason = panic.group("reason")
        result["panic"] = {
            "core": int(panic.group("core")),
            "reason": reason,
            "detail": detail,
            "handled": "unhandled" not in detail.lower(),
        }
        result["summary"] = f"ESP32 panic: {reason}"
        result["hints"].append(_panic_hint(reason))

    backtrace = _BACKTRACE_RE.search(log)
    if backtrace:
        frames = backtrace.group("frames")
        result["backtrace"] = [
            item.split(":", 1)[0]
            for item in frames.split()
            if ":" in item and _ADDR_RE.match(item.split(":", 1)[0])
        ]
        if result["backtrace"]:
            result["hints"].append("使用 `addr2line` 或 `idf.py monitor` 将 backtrace 地址映射到源码行。")

    if "Brownout detector was triggered" in log:
        result["power"]["brownout"] = True
        result["summary"] = "ESP32 brownout reset"
        result["hints"].append("检测到 brownout，优先检查 3.3V 供电、电源纹波、USB 线材和峰值电流余量。")

    if result["reset"] and result["reset"]["reason"] == "SW_CPU_RESET":
        result["hints"].append("SW_CPU_RESET 通常来自软件复位、看门狗处理后的复位或显式 esp_restart()。")

    return result


def _panic_hint(reason: str) -> str:
    normalized = reason.lower()
    if normalized == "loadprohibited":
        return "LoadProhibited 通常表示空指针/非法地址读取，先检查崩溃 PC 附近的指针解引用。"
    if normalized == "storeprohibited":
        return "StoreProhibited 通常表示非法地址写入，先检查输出指针、缓冲区和对象生命周期。"
    if "instrfetch" in normalized:
        return "InstrFetchProhibited 通常表示函数指针或返回地址异常，检查栈破坏和非法跳转。"
    if "watchdog" in normalized or "wdt" in normalized:
        return "看门狗 panic 通常表示任务长时间阻塞，检查临界区、死循环和高优先级任务占用。"
    return f"{reason} panic：结合寄存器 dump 和 backtrace 定位触发点。"
