"""STM32 log diagnostics for faults, HAL status, and debug probe failures."""

from __future__ import annotations

import re
from typing import Any


_FAULT_REG_RE = re.compile(r"\b(HFSR|CFSR|MMFAR|BFAR|DFSR|AFSR)\s*=\s*(0x[0-9a-fA-F]+)")
_HAL_RE = re.compile(r"\b(HAL_TIMEOUT|HAL_ERROR|HAL_BUSY|HAL_OK)\b")


def diagnose_stm32_log(log: str) -> dict[str, Any]:
    """Diagnose STM32 firmware and flashing logs."""
    if not log or not log.strip():
        return {"success": False, "error": "日志为空，无法诊断"}

    result: dict[str, Any] = {
        "success": True,
        "summary": "未发现 STM32 fault/HAL/debug-probe 特征",
        "fault": None,
        "hal": None,
        "debug_probe": None,
        "hints": [],
    }

    lowered = log.lower()

    if "hardfault" in lowered or "hardfault_handler" in lowered:
        registers = dict(_FAULT_REG_RE.findall(log))
        result["fault"] = {"type": "HardFault", "registers": registers}
        result["summary"] = "STM32 HardFault detected"
        result["hints"].append("HardFault 优先检查栈溢出、空指针、非法函数指针和中断优先级配置。")
        if "CFSR" in registers:
            result["hints"].append("CFSR 可进一步拆解 MemManage/BusFault/UsageFault 子原因。")

    hal = _HAL_RE.search(log)
    if hal:
        status = hal.group(1)
        result["hal"] = {"status": status}
        if result["summary"].startswith("未发现"):
            result["summary"] = f"STM32 HAL status: {status}"
        result["hints"].append(_hal_hint(status))

    if "timed out while waiting for target halted" in lowered or "target not halted" in lowered:
        result["debug_probe"] = {"tool": "openocd", "issue": "target_not_halted"}
        result["summary"] = "STM32 OpenOCD target halt failed"
        result["hints"].append("检查 SWD 接线、NRST、BOOT0、调试器供电参考电压，并尝试 connect-under-reset。")

    if "no stm32 target found" in lowered:
        result["debug_probe"] = {"tool": "stm32cubeprog", "issue": "no_target"}
        result["summary"] = "STM32CubeProgrammer target not found"
        result["hints"].append("确认 ST-Link 固件、SWD 接线、目标板供电和 RDP/低功耗状态。")

    return result


def _hal_hint(status: str) -> str:
    if status == "HAL_TIMEOUT":
        return "HAL_TIMEOUT 表示外设等待超时，检查时钟、总线挂起、外设 ready 标志和中断/DMA 状态。"
    if status == "HAL_BUSY":
        return "HAL_BUSY 表示外设状态机未空闲，检查并发调用、未完成 DMA/IRQ 和锁状态。"
    if status == "HAL_ERROR":
        return "HAL_ERROR 表示 HAL 层通用错误，继续读取外设错误码寄存器和 HAL handle ErrorCode。"
    return "HAL_OK 表示 HAL 调用成功，若行为异常应继续检查业务状态或硬件信号。"
