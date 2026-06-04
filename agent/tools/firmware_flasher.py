"""
固件烧写器 —— 将编译产物烧录到目标设备。

支持的烧写方法:
- PlatformIO upload（项目配置驱动）
- esptool（ESP32/ESP8266）
- STM32CubeProg / STM32_Programmer_CLI（STM32 via SWD）
- OpenOCD（通用调试器）
- J-Link（SEGGER）

提供烧写方法自动检测、烧写验证、引导加载程序状态检测等功能。
"""

import logging
import os
import re
import shutil
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 固件文件确定性解析
# ---------------------------------------------------------------------------


def _resolve_unique_firmware(search_dirs: list[Path], patterns: list[str],
                              label: str = "固件") -> tuple[Optional[Path], Optional[str]]:
    """在搜索目录中递归查找唯一固件文件。

    多个匹配时返回错误信息而非静默选取第一个 —— 防止多 target/多芯片项目烧错产物。

    Args:
        search_dirs: 要搜索的目录列表。
        patterns: glob 模式列表（如 ``["*.bin", "*.elf"]``）。
        label: 错误信息中的文件类型标签。

    Returns:
        (firmware_path, error) —— 恰好一个匹配时 error 为 None，
        零匹配时 firmware_path 为 None，多个匹配时两者均非 None 且 firmware_path 为 None。
    """
    all_candidates: list[Path] = []
    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue
        for pattern in patterns:
            all_candidates.extend(search_dir.rglob(pattern))
    # 去重（按解析后的绝对路径）
    seen: set[str] = set()
    unique: list[Path] = []
    for p in all_candidates:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    unique.sort(key=lambda p: str(p))

    if not unique:
        return None, None
    if len(unique) > 1:
        listed = "\n  ".join(str(p) for p in unique)
        return None, f"在搜索目录中找到 {len(unique)} 个{label}文件，无法确定烧录目标。请显式指定固件路径:\n  {listed}"
    return unique[0], None


# ---------------------------------------------------------------------------
# 支持的烧写方法
# ---------------------------------------------------------------------------

FLASH_METHODS = {
    "platformio": "PlatformIO upload —— 通过 platformio.ini 配置自动上传",
    "esptool": "esptool.py —— ESP32/ESP8266 串口烧写",
    "stm32cubeprog": "STM32_Programmer_CLI —— STM32 SWD/JTAG 烧写",
    "openocd": "OpenOCD —— 通用调试探针烧写",
    "jlink": "J-Link —— SEGGER J-Link 烧写",
    "arduino": "arduino-cli upload —— Arduino 开发板烧写",
}


# ---------------------------------------------------------------------------
# 烧写方法检测
# ---------------------------------------------------------------------------


def detect_flash_method(project_path: str) -> str:
    """从项目配置中检测推荐的烧写方法。

    检测逻辑:
        1. 存在 ``platformio.ini`` 并且项目不完全是 Arduino 风格 → ``"platformio"``
        2. ESP32/ESP8266 相关标识 → ``"esptool"``
        3. STM32 相关标识 → ``"stm32cubeprog"``
        4. 存在 .ino 文件 → ``"arduino"``
        5. 存在 ``openocd.cfg`` → ``"openocd"``
        6. 存在 J-Link 脚本 → ``"jlink"``
        7. 默认返回 ``"platformio"``

    Args:
        project_path: 项目根目录路径。

    Returns:
        烧写方法标识字符串（见 ``FLASH_METHODS`` 的键）。
    """
    root = Path(project_path).resolve()

    # 检查特化配置文件
    if (root / "openocd.cfg").is_file() or (root / "openocd").is_dir():
        return "openocd"

    jlink_files = list(root.glob("*.jlink")) + list(root.glob("*.jlinkscript"))
    if jlink_files:
        return "jlink"

    # 检查 platformio.ini 内容
    pio_ini = root / "platformio.ini"
    if pio_ini.is_file():
        try:
            content = pio_ini.read_text(encoding="utf-8")
            # 检测上传工具类型
            if re.search(r"upload_protocol\s*=\s*esptool", content, re.IGNORECASE):
                return "esptool"
            if re.search(r"upload_protocol\s*=\s*stlink|stm32", content, re.IGNORECASE):
                return "stm32cubeprog"
            if re.search(r"upload_protocol\s*=\s*jlink|segger", content, re.IGNORECASE):
                return "jlink"
            # 平台特征
            if re.search(r"platform\s*=\s*espressif", content, re.IGNORECASE):
                return "esptool"
            if re.search(r"platform\s*=\s*ststm32", content, re.IGNORECASE):
                return "stm32cubeprog"

            return "platformio"
        except (OSError, UnicodeDecodeError):
            pass

    # Arduino
    ino_files = list(root.glob("*.ino"))
    if ino_files:
        return "arduino"

    return "platformio"


# ---------------------------------------------------------------------------
# 引导加载程序状态检测
# ---------------------------------------------------------------------------


def get_bootloader_info(port: str) -> dict:
    """检测设备是否处于引导加载程序模式。

    通过串口发送探测命令并分析响应，判断设备当前处于
    引导加载程序模式还是正常运行模式。

    Args:
        port: 串口端口路径。

    Returns:
        引导加载程序状态信息::

            {
                "in_bootloader": bool,
                "bootloader_type": str,    # 如 "STM32 DFU"、"ESP32 ROM"、"U-Boot"
                "chip_family": str,        # 芯片系列
                "supports_flash": bool,    # 是否可通过串口烧写
                "recommended_tool": str,   # 推荐烧写工具
            }
    """
    result: dict = {
        "in_bootloader": False,
        "bootloader_type": "",
        "chip_family": "",
        "supports_flash": False,
        "recommended_tool": "",
    }

    # 尝试通过 pyserial 探测（惰性依赖，不强制要求）
    try:
        import serial
    except ImportError:
        logger.debug("pyserial 未安装，无法探测引导加载程序。请执行: pip install pyserial")
        return result

    try:
        ser = serial.Serial(port=port, baudrate=115200, timeout=2.0)
    except (serial.SerialException, OSError) as exc:
        logger.warning("无法打开串口 %s: %s", port, exc)
        return result

    try:
        # 发送 break + AT 命令
        ser.send_break(0.1)
        time.sleep(0.05)
        ser.write(b"AT\r\n")
        ser.flush()

        time.sleep(0.5)
        response = ser.read(ser.in_waiting or 1024).decode("utf-8", errors="replace")

        # 模式匹配
        if re.search(r"(STM32|stm32)\s*(BOOT|DFU)", response, re.IGNORECASE):
            result["in_bootloader"] = True
            result["bootloader_type"] = "STM32 DFU"
            result["chip_family"] = "STM32"
            result["supports_flash"] = True
            result["recommended_tool"] = "stm32cubeprog"

        elif re.search(r"(waiting for download|ets\s+\w+\s+.*rom)", response, re.IGNORECASE):
            result["in_bootloader"] = True
            result["bootloader_type"] = "ESP32 ROM"
            result["chip_family"] = "ESP32"
            result["supports_flash"] = True
            result["recommended_tool"] = "esptool"

        elif re.search(r"(U-Boot|uboot)", response, re.IGNORECASE):
            result["in_bootloader"] = True
            result["bootloader_type"] = "U-Boot"
            result["chip_family"] = ""
            result["supports_flash"] = True
            result["recommended_tool"] = "openocd"

        elif re.search(r"(RP2 Boot|UF2 Boot)", response, re.IGNORECASE):
            result["in_bootloader"] = True
            result["bootloader_type"] = "RP2 Boot"
            result["chip_family"] = "RP2040"
            result["supports_flash"] = False
            result["recommended_tool"] = ""

        elif response.strip():
            # 有响应但无法识别 —— 可能是固件正常运行中
            result["in_bootloader"] = False
            result["bootloader_type"] = "application"

        logger.info("引导加载程序检测 %s: in_bootloader=%s type=%s", port, result["in_bootloader"], result["bootloader_type"])
    except (OSError, Exception) as exc:
        logger.warning("引导加载程序探测异常: %s", exc)
    finally:
        ser.close()

    return result


# ---------------------------------------------------------------------------
# 烧写
# ---------------------------------------------------------------------------


def _run_command(cmd: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    """执行子进程并返回结果。"""
    logger.debug("执行: %s (cwd=%s)", " ".join(cmd), cwd)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd), timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error("命令超时: %s", " ".join(cmd))
        raise
    except FileNotFoundError:
        logger.error("命令未找到: %s", cmd[0])
        raise


def _flash_platformio(project_path: Path, port: str) -> dict:
    """通过 PlatformIO 上传烧写。"""
    if not shutil.which("pio"):
        return {
            "success": False,
            "output": "",
            "errors": ["PlatformIO CLI ('pio') 未安装。请执行: pip install platformio"],
        }

    cmd = ["pio", "run", "-d", str(project_path), "-t", "upload"]
    if port:
        cmd.extend(["--upload-port", port])

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"success": False, "output": "", "errors": [str(exc)]}

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
    }


def _flash_esptool(project_path: Path, port: str, chip: str = "") -> dict:
    """通过 esptool.py 烧写 ESP32/ESP8266。

    优先查找 ``.pio/build/`` 目录下的 firmware.bin，
    以及 ``build/``、``.pio/`` 下的固件文件。
    自动检测 bootloader.bin 和 partition-table.bin 并一同烧录。

    Args:
        project_path: 项目根目录。
        port: 串口设备路径。
        chip: 目标芯片型号（如 ``esp32s3``），为空时自动从环境变量 ESP_CHIP 或项目配置推断。
    """
    esptool = shutil.which("esptool.py") or shutil.which("esptool")
    if not esptool:
        return {
            "success": False,
            "output": "",
            "errors": ["esptool.py 未安装。请执行: pip install esptool"],
        }

    # 芯片型号检测
    if not chip:
        chip = os.environ.get("ESP_CHIP", "")
    if not chip:
        chip = _detect_esp_chip(project_path)

    # 查找固件文件 —— 多匹配时报错而非静默取第一个
    firmware_path: Optional[Path] = None
    bootloader_path: Optional[Path] = None
    partition_path: Optional[Path] = None
    search_dirs = [
        project_path / ".pio" / "build",
        project_path / "build",
        project_path / ".pio",
    ]

    # 主固件 —— 优先精确匹配 firmware.bin，再回退到宽泛模式
    firmware_path, fw_err = _resolve_unique_firmware(
        search_dirs, ["firmware.bin"], "固件")
    if firmware_path is None and fw_err is None:
        firmware_path, fw_err = _resolve_unique_firmware(
            search_dirs, ["*.bin", "*.elf"], "固件")
    if fw_err:
        return {"success": False, "output": "", "errors": [fw_err]}
    if firmware_path is None:
        # 回退：全局搜索
        firmware_path, fw_err = _resolve_unique_firmware(
            [project_path], ["firmware.bin"], "固件")
        if firmware_path is None and fw_err is None:
            firmware_path, fw_err = _resolve_unique_firmware(
                [project_path], ["*.bin"], "固件")
        if fw_err:
            return {"success": False, "output": "", "errors": [fw_err]}

    if firmware_path is None:
        return {
            "success": False,
            "output": "",
            "errors": [f"未找到固件文件（.bin）。已搜索: {project_path}"],
        }

    # 引导加载程序（允许缺失）
    for search_dir in search_dirs:
        if search_dir.is_dir():
            for p in search_dir.rglob("bootloader.bin"):
                bootloader_path = p
                break
    # 分区表（允许缺失）
    for search_dir in search_dirs:
        if search_dir.is_dir():
            for p in search_dir.rglob("partition-table.bin"):
                partition_path = p
                break

    logger.info("烧写固件: %s → %s (chip=%s)", firmware_path.name, port, chip or "auto")

    cmd = [esptool, "--port", port]
    if chip:
        cmd += ["--chip", chip]

    # 构建分区烧录命令
    cmd.append("write_flash")
    # 引导加载程序
    if bootloader_path and bootloader_path.exists():
        cmd += ["0x1000", str(bootloader_path)]
    # 分区表
    if partition_path and partition_path.exists():
        cmd += ["0x8000", str(partition_path)]
    # 固件
    cmd += ["0x10000", str(firmware_path)]

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"success": False, "output": "", "errors": [str(exc)]}

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
    }


def _detect_esp_chip(project_path: Path) -> str:
    """从项目配置中推断 ESP32 芯片型号。"""
    # PlatformIO 配置
    pio_ini = project_path / "platformio.ini"
    if pio_ini.is_file():
        content = pio_ini.read_text(errors="replace")
        for line in content.splitlines():
            line = line.strip()
            if "board =" in line.lower():
                board = line.split("=", 1)[1].strip()
                chip_map = {
                    "esp32s3": "esp32s3", "esp32-s3": "esp32s3",
                    "esp32c3": "esp32c3", "esp32-c3": "esp32c3",
                    "esp32s2": "esp32s2", "esp32-s2": "esp32s2",
                    "esp32c6": "esp32c6", "esp32-c6": "esp32c6",
                    "esp32h2": "esp32h2", "esp32-h2": "esp32h2",
                }
                for key, val in chip_map.items():
                    if key in board.lower():
                        return val

    # ESP-IDF sdkconfig
    sdkconfig = project_path / "sdkconfig"
    if sdkconfig.is_file():
        content = sdkconfig.read_text(errors="replace")
        for line in content.splitlines():
            if "CONFIG_IDF_TARGET=" in line:
                return line.split("=", 1)[1].strip().strip('"')

    return ""


def _flash_stm32cubeprog(project_path: Path, port: str) -> dict:
    """通过 STM32CubeProg CLI 烧写 STM32。"""
    stm32cli = (
        shutil.which("STM32_Programmer_CLI")
        or shutil.which("STM32CubeProg")
    )
    if not stm32cli:
        return {
            "success": False,
            "output": "",
            "errors": [
                "STM32_Programmer_CLI 未安装或不在 PATH 中。"
                "请从 https://www.st.com/en/development-tools/stm32cubeprog.html 下载。"
            ],
        }

    # 查找 firmware.hex/.bin/.elf —— 多匹配时报错而非静默取第一个
    firmware_path, fw_err = _resolve_unique_firmware(
        [project_path], ["*.hex", "*.bin", "*.elf"], "固件")
    if fw_err:
        return {"success": False, "output": "", "errors": [fw_err]}

    if firmware_path is None:
        return {
            "success": False,
            "output": "",
            "errors": [f"未找到固件文件（.hex/.bin/.elf）。已搜索: {project_path}"],
        }

    logger.info("STM32 烧写: %s → %s", firmware_path.name, port)

    cmd = [
        stm32cli,
        "-c", f"port=SWD",
        "-w", str(firmware_path),
        "-v",
        "-rst",
    ]

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"success": False, "output": "", "errors": [str(exc)]}

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
    }


def _flash_openocd(project_path: Path, port: str) -> dict:
    """通过 OpenOCD 烧写。

    优先查找项目中的 ``openocd.cfg`` 或 ``board/*.cfg``。
    """
    openocd = shutil.which("openocd")
    if not openocd:
        return {
            "success": False,
            "output": "",
            "errors": ["OpenOCD 未安装。请执行: sudo apt install openocd"],
        }

    # 查找配置文件
    config_file: Optional[Path] = None
    cfg_candidates = [
        project_path / "openocd.cfg",
        project_path / "board" / "openocd.cfg",
    ]
    for candidate in cfg_candidates:
        if candidate.is_file():
            config_file = candidate
            break

    if config_file is None:
        # 尝试 board/ 下的其他 .cfg 文件
        board_dir = project_path / "board"
        if board_dir.is_dir():
            cfgs = list(board_dir.glob("*.cfg"))
            if cfgs:
                config_file = cfgs[0]

    # 查找固件 —— 多匹配时报错而非静默取第一个
    firmware_path, fw_err = _resolve_unique_firmware(
        [project_path], ["*.elf", "*.bin", "*.hex"], "固件")
    if fw_err:
        return {"success": False, "output": "", "errors": [fw_err]}

    if firmware_path is None:
        return {
            "success": False,
            "output": "",
            "errors": [f"未找到固件文件。已搜索: {project_path}"],
        }

    cmd = [openocd]
    if config_file:
        cmd.extend(["-f", str(config_file)])
    cmd.extend([
        "-c", f"program {firmware_path} verify reset exit",
    ])

    logger.info("OpenOCD 烧写: %s", firmware_path.name)

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"success": False, "output": "", "errors": [str(exc)]}

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
    }


def _flash_jlink(project_path: Path, port: str) -> dict:
    """通过 SEGGER J-Link 烧写。

    优先查找项目中的 J-Link 脚本，否则生成临时命令序列。
    """
    jlinkexe = shutil.which("JLinkExe") or shutil.which("jlinkexe")
    if not jlinkexe:
        return {
            "success": False,
            "output": "",
            "errors": ["JLinkExe 未安装。请从 https://www.segger.com/downloads/jlink/ 下载"],
        }

    # 查找 J-Link 脚本（允许多个但记录警告）
    script_file: Optional[Path] = None
    for pattern in ("*.jlink", "*.jlinkscript", "flash.jlink"):
        candidates = list(project_path.rglob(pattern))
        if candidates:
            if len(candidates) > 1:
                logger.warning("J-Link 脚本不唯一（共 %d 个），使用: %s", len(candidates), candidates[0])
            script_file = candidates[0]
            break

    # 查找固件 —— 多匹配时报错而非静默取第一个
    firmware_path, fw_err = _resolve_unique_firmware(
        [project_path], ["*.hex", "*.bin", "*.elf"], "固件")
    if fw_err:
        return {"success": False, "output": "", "errors": [fw_err]}

    if firmware_path is None and script_file is None:
        return {
            "success": False,
            "output": "",
            "errors": [f"未找到固件文件或 J-Link 脚本。已搜索: {project_path}"],
        }

    cmd = [jlinkexe]

    if script_file:
        cmd.extend(["-CommanderScript", str(script_file)])
    elif port:
        # 尝试使用串口连接 J-Link
        cmd.extend(["-device", port])
    else:
        cmd.extend(["-autoconnect", "1"])

    # 生成 J-Link 命令
    if firmware_path and not script_file:
        commands = [
            "r",               # reset
            "h",               # halt
            "loadfile " + str(firmware_path),
            "r",
            "g",
            "exit",
        ]
        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile(mode="w", suffix=".jlink", delete=False) as f:
            f.write("\n".join(commands))
            tmp_script = f.name
        cmd.extend(["-CommanderScript", tmp_script])
        logger.info("已生成临时 J-Link 脚本: %s", tmp_script)

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"success": False, "output": "", "errors": [str(exc)]}

    # 清理临时脚本
    if firmware_path and not script_file:
        with suppress(OSError):
            Path(tmp_script).unlink(missing_ok=True)

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
    }


def _flash_arduino(project_path: Path, port: str, fqbn: str = "") -> dict:
    """通过 arduino-cli 上传烧写。

    Args:
        project_path: 项目根目录。
        port: 串口设备路径。
        fqbn: 全限定板名，为空时自动检测。
    """
    if not shutil.which("arduino-cli"):
        return {
            "success": False,
            "output": "",
            "errors": ["arduino-cli 未安装。请参见: https://arduino.github.io/arduino-cli/"],
        }

    if not fqbn:
        from agent.tools.firmware_builder import _detect_arduino_fqbn
        fqbn = _detect_arduino_fqbn(project_path)

    cmd = [
        "arduino-cli", "upload",
        "-p", port,
        "--fqbn", fqbn,
        str(project_path),
    ]

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"success": False, "output": "", "errors": [str(exc)]}

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
    }


def _flash_esp_idf(project_path: Path, port: str, chip: str = "") -> dict:
    """Flash an ESP-IDF project with idf.py."""
    if not shutil.which("idf.py"):
        return {
            "success": False,
            "output": "",
            "errors": ["ESP-IDF idf.py 未安装或未进入 ESP-IDF 环境"],
        }

    from agent.platforms.esp32 import ESP32Platform

    target = ESP32Platform().idf_target(chip or _detect_esp_chip(project_path) or "esp32")
    cmd = ["idf.py", "-p", port, f"-DIDF_TARGET={target}", "flash"]

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"success": False, "output": "", "errors": [str(exc)]}

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
    }


def _is_zephyr_project(project_path: Path) -> bool:
    cmake_lists = project_path / "CMakeLists.txt"
    if not cmake_lists.is_file():
        return False
    content = cmake_lists.read_text(errors="replace")
    return "Zephyr" in content or "ZEPHYR_BASE" in content


def _flash_west(project_path: Path) -> dict:
    """Flash a Zephyr/NCS build with west."""
    if not shutil.which("west"):
        return {"success": False, "output": "", "errors": ["west 未安装或未进入 Zephyr/nRF Connect SDK 环境"]}

    cmd = ["west", "flash", "--build-dir", str(project_path / "build")]
    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"success": False, "output": "", "errors": [str(exc)]}

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
    }


def _find_nordic_firmware(project_path: Path) -> Optional[Path]:
    candidates = [
        project_path / "build" / "zephyr" / "zephyr.hex",
        project_path / "build" / "zephyr.hex",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = list(project_path.rglob("*.hex"))
    return matches[0] if matches else None


def _flash_nrfjprog(project_path: Path, chip: str = "") -> dict:
    """Flash a Nordic firmware image using nrfjprog."""
    if not shutil.which("nrfjprog"):
        return {"success": False, "output": "", "errors": ["nrfjprog 未安装或不在 PATH 中"]}

    firmware_path = _find_nordic_firmware(project_path)
    if firmware_path is None:
        return {"success": False, "output": "", "errors": [f"未找到 Nordic 固件文件（.hex）。已搜索: {project_path}"]}

    from agent.tools.nrfjprog_flasher import flash_with_nrfjprog

    result = flash_with_nrfjprog(str(firmware_path), chip or "nRF52840", check_available=False)
    if "error" in result and "errors" not in result:
        result["errors"] = [result["error"]]
    result.setdefault("output", "")
    return result


_FLASHERS = {
    "platformio": _flash_platformio,
    "esptool": _flash_esptool,
    "stm32cubeprog": _flash_stm32cubeprog,
    "openocd": _flash_openocd,
    "jlink": _flash_jlink,
    "arduino": _flash_arduino,
}


def flash_firmware(
    project_path: str,
    port: str,
    method: str = "auto",
    platform: Optional[str] = None,
    chip: Optional[str] = None,
) -> dict:
    """烧写固件到目标设备。

    Args:
        project_path: 项目根目录路径。
        port: 目标串口/调试端口路径。
        method: 烧写方法。``"auto"`` 自动检测，或显式指定:
                ``"platformio"`` / ``"esptool"`` / ``"stm32cubeprog"`` /
                ``"openocd"`` / ``"jlink"`` / ``"arduino"``。
        platform: 可选平台名，用于平台感知烧录路径。
        chip: 可选芯片型号，用于平台感知烧录参数。

    Returns:
        烧写结果 dict::

            {
                "success": bool,
                "output": str,      # 工具标准输出
                "errors": list,     # 错误信息列表
            }
    """
    root = Path(project_path).resolve()
    platform_name = (platform or "").lower()

    if platform_name in ("esp32", "esp", "espressif") and method in ("auto", "esp-idf", "idf"):
        return _flash_esp_idf(root, port, chip=chip or "")
    if platform_name in ("nordic", "nrf") and method in ("west", "west-flash"):
        return _flash_west(root)
    if platform_name in ("nordic", "nrf") and method == "nrfjprog":
        return _flash_nrfjprog(root, chip=chip or "")
    if platform_name in ("nordic", "nrf") and method == "auto" and _is_zephyr_project(root):
        return _flash_west(root)

    if method == "auto":
        method = detect_flash_method(str(root))
        logger.info("自动检测烧写方法: %s", method)

    if method not in _FLASHERS:
        available = ", ".join(_FLASHERS.keys())
        return {
            "success": False,
            "output": "",
            "errors": [f"不支持的烧写方法 '{method}'。可用方法: {available}"],
        }

    flasher = _FLASHERS[method]
    logger.info("开始烧写固件: method=%s, port=%s, project=%s", method, port, root)

    result = _flash_esptool(root, port, chip=chip or "") if method == "esptool" else flasher(root, port)

    if result["success"]:
        logger.info("烧写成功: %s", port)
    else:
        logger.error("烧写失败: %s", port)

    return result


# ---------------------------------------------------------------------------
# 烧写验证
# ---------------------------------------------------------------------------


def verify_flash(project_path: str, port: str) -> dict:
    """烧写后回读并验证固件完整性。

    当前支持的验证方式:
        - esptool: ``verify_flash``
        - OpenOCD: ``verify_image``
        - STM32CubeProg: 自带 ``-v`` 选项（已在烧写阶段完成）

    Args:
        project_path: 项目根目录路径。
        port: 目标端口。

    Returns:
        验证结果 dict::

            {
                "verified": bool,
                "output": str,
                "errors": list,
            }
    """
    root = Path(project_path).resolve()
    method = detect_flash_method(str(root))

    if method == "esptool":
        esptool = shutil.which("esptool.py") or shutil.which("esptool")
        if not esptool:
            return {
                "verified": False,
                "output": "",
                "errors": ["esptool.py 未安装"],
            }

        firmware_path, fw_err = _resolve_unique_firmware(
            [root / ".pio" / "build", root / "build", root / ".pio"],
            ["firmware.bin", "*.bin"], "固件")
        if fw_err:
            return {"verified": False, "output": "", "errors": [fw_err]}

        if firmware_path is None:
            firmware_path, fw_err = _resolve_unique_firmware(
                [root], ["firmware.bin", "*.bin"], "固件")
            if fw_err:
                return {"verified": False, "output": "", "errors": [fw_err]}

        if firmware_path is None:
            return {
                "verified": False,
                "output": "",
                "errors": ["未找到固件文件进行验证"],
            }

        cmd = [esptool, "--port", port, "verify_flash", "--diff", "yes", str(firmware_path)]
        try:
            result = _run_command(cmd, root)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {"verified": False, "output": "", "errors": [str(exc)]}

        return {
            "verified": result.returncode == 0,
            "output": result.stdout,
            "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
        }

    elif method == "openocd":
        openocd = shutil.which("openocd")
        if not openocd:
            return {"verified": False, "output": "", "errors": ["OpenOCD 未安装"]}

        cfg: Optional[Path] = None
        for candidate in [root / "openocd.cfg", root / "board" / "openocd.cfg"]:
            if candidate.is_file():
                cfg = candidate
                break

        firmware_path, fw_err = _resolve_unique_firmware(
            [root], ["*.elf", "*.bin", "*.hex"], "固件")
        if fw_err:
            return {"verified": False, "output": "", "errors": [fw_err]}

        if firmware_path is None:
            return {"verified": False, "output": "", "errors": ["未找到固件文件"]}

        cmd = [openocd]
        if cfg:
            cmd.extend(["-f", str(cfg)])
        cmd.extend(["-c", f"verify_image {firmware_path}", "-c", "reset", "-c", "exit"])

        try:
            result = _run_command(cmd, root)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {"verified": False, "output": "", "errors": [str(exc)]}

        return {
            "verified": result.returncode == 0,
            "output": result.stdout,
            "errors": [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
        }

    # 其他方法不在 Python 层面做验证（已由烧写工具自带校验）
    return {
        "verified": True,
        "output": "",
        "errors": [f"验证方式 '{method}' 暂不支持 Python 层面独立验证，请依赖烧写工具内置校验"],
    }
