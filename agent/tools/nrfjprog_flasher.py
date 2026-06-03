"""nrfjprog flashing integration for Nordic nRF52/nRF53 devices."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import shutil
import subprocess


def detect_family_from_chip(chip_model: str) -> Optional[str]:
    """Return nrfjprog family name for a Nordic chip model."""
    normalized = chip_model.lower().replace("-", "").replace("_", "")
    if "nrf52" in normalized:
        return "NRF52"
    if "nrf53" in normalized:
        return "NRF53"
    return None


class NrfjprogFlasher:
    """nrfjprog command generator and executor."""

    def __init__(self, executable: str = "nrfjprog") -> None:
        self.executable = executable

    def generate_flash_args(
        self,
        firmware_path: str,
        chip_model: str,
        *,
        coprocessor: Optional[str] = None,
        erase_mode: str = "sector",
        verify: bool = True,
        reset: bool = True,
    ) -> list[str]:
        """Generate nrfjprog flash command arguments."""
        family = detect_family_from_chip(chip_model)
        if family is None:
            raise ValueError(f"不支持的 Nordic 芯片型号: {chip_model}")

        args = [
            self.executable,
            "--program",
            firmware_path,
            "--family",
            family,
        ]
        if coprocessor:
            args.extend(["--coprocessor", coprocessor])
        if erase_mode == "chip":
            args.append("--chiperase")
        elif erase_mode == "sector":
            args.append("--sectorerase")
        if verify:
            args.append("--verify")
        if reset:
            args.append("--reset")
        return args

    def generate_flash_command(
        self,
        firmware_path: str,
        chip_model: str,
        *,
        coprocessor: Optional[str] = None,
        erase_mode: str = "sector",
        verify: bool = True,
        reset: bool = True,
    ) -> str:
        """Generate an nrfjprog flash command string."""
        return " ".join(self.generate_flash_args(
            firmware_path,
            chip_model,
            coprocessor=coprocessor,
            erase_mode=erase_mode,
            verify=verify,
            reset=reset,
        ))

    def check_availability(self) -> bool:
        """Return True when nrfjprog is available in PATH."""
        return shutil.which(self.executable) is not None

    def flash(
        self,
        firmware_path: str,
        chip_model: str,
        *,
        coprocessor: Optional[str] = None,
        erase_mode: str = "sector",
        check_available: bool = True,
    ) -> dict:
        """Flash a firmware file with nrfjprog."""
        if not firmware_path:
            return {"success": False, "error": "缺少参数: firmware_path"}
        if not chip_model:
            return {"success": False, "error": "缺少参数: chip_model"}

        firmware = Path(firmware_path).expanduser()
        if not firmware.is_file():
            return {"success": False, "error": f"固件文件不存在: {firmware}"}
        if check_available and not self.check_availability():
            return {"success": False, "error": "nrfjprog 未安装或不在 PATH 中"}

        try:
            args = self.generate_flash_args(
                str(firmware),
                chip_model,
                coprocessor=coprocessor,
                erase_mode=erase_mode,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=120)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {"success": False, "error": str(exc), "command": args}

        return {
            "success": result.returncode == 0,
            "command": args,
            "output": result.stdout,
            "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
        }


def flash_with_nrfjprog(
    firmware_path: str,
    chip_model: str,
    *,
    coprocessor: Optional[str] = None,
    erase_mode: str = "sector",
    check_available: bool = True,
) -> dict:
    """Flash firmware using nrfjprog."""
    return NrfjprogFlasher().flash(
        firmware_path,
        chip_model,
        coprocessor=coprocessor,
        erase_mode=erase_mode,
        check_available=check_available,
    )
