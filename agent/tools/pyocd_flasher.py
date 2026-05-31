"""pyOCD 烧录工具集成 — 支持 ARM Cortex-M 芯片烧录。"""

from __future__ import annotations
from typing import Optional, List, Dict, Tuple
import subprocess
import re


SUPPORTED_TARGETS = {
    "nrf52810": "nRF52810",
    "nrf52832": "nRF52832",
    "nrf52833": "nRF52833",
    "nrf52840": "nRF52840",
    "nrf5340": "nRF5340",
    "stm32f401re": "STM32F401RE",
    "stm32f405rg": "STM32F405RG",
    "stm32f407vg": "STM32F407VG",
    "stm32f411re": "STM32F411RE",
    "stm32f429zi": "STM32F429ZI",
    "stm32f746zg": "STM32F746ZG",
    "stm32f767zi": "STM32F767ZI",
    "stm32h743zi": "STM32H743ZI",
    "stm32h750vb": "STM32H750VB",
}


def detect_target_from_chip(chip_model: str) -> Optional[str]:
    """从芯片型号检测 pyOCD 目标名称。"""
    normalized = chip_model.lower().replace("-", "").replace("_", "")

    if normalized in SUPPORTED_TARGETS:
        return normalized

    for target_key in SUPPORTED_TARGETS.keys():
        if target_key in normalized:
            return target_key

    if normalized.startswith("stm32"):
        match = re.match(r"(stm32[a-z]\d{2,3}[a-z]{0,2})", normalized)
        if match:
            prefix = match.group(1)
            if prefix in SUPPORTED_TARGETS:
                return prefix

    return None


def list_connected_targets() -> List[Dict[str, str]]:
    """列出已连接的调试器和目标。"""
    try:
        result = subprocess.run(
            ["pyocd", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return []

        targets = []
        for line in result.stdout.splitlines():
            match = re.match(r"(\d+)\s*=>\s*([^\[]+)\s*\[([^\]]+)\]", line)
            if match:
                targets.append({
                    "index": int(match.group(1)),
                    "name": match.group(2).strip(),
                    "target": match.group(3).strip(),
                })

        return targets
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


class PyOCDFlasher:
    """pyOCD 烧录器 — 生成 pyOCD 烧录命令。"""

    def __init__(self, executable: str = "pyocd"):
        self.executable = executable

    def generate_flash_command(
        self,
        firmware_path: str,
        target: str,
        base_address: Optional[int] = None,
        erase_mode: str = "sector",
        verify: bool = True,
        frequency: Optional[int] = None,
    ) -> str:
        """生成烧录命令。"""
        cmd_parts = [self.executable, "flash", "-t", target]

        if frequency:
            cmd_parts.extend(["-f", str(frequency)])
        if erase_mode != "auto":
            cmd_parts.extend(["--erase", erase_mode])
        if base_address is not None:
            cmd_parts.extend(["--base-address", f"0x{base_address:08x}"])

        cmd_parts.append(firmware_path)
        return " ".join(cmd_parts)

    def generate_erase_command(
        self,
        target: str,
        erase_mode: str = "chip",
    ) -> str:
        """生成擦除命令。"""
        return f"{self.executable} erase -t {target} --chip"

    def generate_reset_command(
        self,
        target: str,
        reset_type: str = "hw",
    ) -> str:
        """生成复位命令。"""
        return f"{self.executable} reset -t {target}"

    def generate_multi_flash_commands(
        self,
        files: List[Tuple[str, int]],
        target: str,
    ) -> List[str]:
        """生成多文件烧录命令列表。"""
        commands = []
        for firmware_path, base_address in files:
            commands.append(self.generate_flash_command(
                firmware_path=firmware_path,
                target=target,
                base_address=base_address,
                erase_mode="sector",
            ))
        return commands

    def check_availability(self) -> bool:
        """检查 pyOCD 是否可用。"""
        try:
            result = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                timeout=2,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False


def register_pyocd_tool():
    """注册 pyOCD 烧录工具到工具注册表"""
    from agent.tools import ToolRegistry

    registry = ToolRegistry()

    def pyocd_flash(firmware_path: str, chip_model: str, **kwargs):
        """pyOCD 烧录工具函数"""
        flasher = PyOCDFlasher()
        if not flasher.check_availability():
            return {
                "success": False,
                "error": "pyOCD 未安装或不可用，请运行: pip install pyocd",
            }

        target = detect_target_from_chip(chip_model)
        if not target:
            return {
                "success": False,
                "error": f"不支持的芯片型号: {chip_model}",
                "supported": list(SUPPORTED_TARGETS.values()),
            }

        return {
            "success": True,
            "target": target,
            "command": flasher.generate_flash_command(
                firmware_path=firmware_path,
                target=target,
                **kwargs,
            ),
        }

    registry.register(
        name="pyocd_flash",
        func=pyocd_flash,
        description="使用 pyOCD 烧录 ARM Cortex-M 芯片",
        parameters={
            "firmware_path": {"type": "string", "description": "固件文件路径"},
            "chip_model": {"type": "string", "description": "芯片型号（如 nRF52840, STM32F405RGT6）"},
            "base_address": {"type": "integer", "description": "基地址（可选，仅 .bin 文件）"},
            "erase_mode": {"type": "string", "description": "擦除模式（sector/chip/auto）", "default": "sector"},
        },
    )
