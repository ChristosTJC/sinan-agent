"""
固件构建器 —— 自动检测构建系统并编译固件。

支持的构建系统:
- PlatformIO (``platformio.ini``)
- CMake (``CMakeLists.txt``)
- Make (``Makefile``)
- Arduino CLI (``*.ino``)

提供编译、错误解析、工具链信息检测等功能。
"""

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 错误行模式（GCC/Clang 风格）
# ---------------------------------------------------------------------------

_ERROR_PATTERN = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s+(?P<level>error|warning|note):\s+(?P<message>.*)$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 构建系统检测
# ---------------------------------------------------------------------------


def detect_build_system(project_path: str) -> Optional[str]:
    """检测项目使用的构建系统。

    检测顺序:
        1. ``platformio.ini`` → ``"platformio"``
        2. ``CMakeLists.txt`` → ``"cmake"``
        3. ``Makefile`` → ``"make"``
        4. ``*.ino``（Arduino 草图文件）→ ``"arduino"``

    Args:
        project_path: 项目根目录路径。

    Returns:
        构建系统标识字符串，无法识别时返回 None。
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        logger.warning("项目路径不存在: %s", root)
        return None

    # PlatformIO
    if (root / "platformio.ini").is_file():
        logger.debug("检测到 PlatformIO 项目: %s", root)
        return "platformio"

    # CMake
    if (root / "CMakeLists.txt").is_file():
        logger.debug("检测到 CMake 项目: %s", root)
        return "cmake"

    # Make
    if (root / "Makefile").is_file():
        logger.debug("检测到 Make 项目: %s", root)
        return "make"

    # Arduino (.ino 文件)
    ino_files = list(root.glob("*.ino"))
    if ino_files:
        logger.debug("检测到 Arduino 项目: %s（%d 个 .ino 文件）", root, len(ino_files))
        return "arduino"

    logger.warning("未检测到已知构建系统: %s", root)
    return None


def _detect_arduino_fqbn(project_path: Path) -> str:
    """从项目配置中检测 Arduino 板型 FQBN。

    检测顺序:
        1. 环境变量 ``ARDUINO_FQBN``
        2. ``platformio.ini`` 中的 ``board`` 字段映射
        3. ``arduino-cli board list`` 已连接设备
        4. 默认 ``arduino:avr:uno``

    Returns:
        FQBN 字符串，如 ``arduino:avr:uno`` 或 ``esp32:esp32:esp32``。
    """
    # 环境变量
    env_fqbn = os.environ.get("ARDUINO_FQBN", "")
    if env_fqbn:
        return env_fqbn

    # PlatformIO board → Arduino FQBN 映射
    pio_to_fqbn = {
        "uno": "arduino:avr:uno",
        "mega": "arduino:avr:mega:cpu=atmega2560",
        "mega2560": "arduino:avr:mega:cpu=atmega2560",
        "nano": "arduino:avr:nano",
        "nano328": "arduino:avr:nano",
        "due": "arduino:sam:arduino_due_x",
        "leonardo": "arduino:avr:leonardo",
        "micro": "arduino:avr:micro",
        "esp32": "esp32:esp32:esp32",
        "esp32s3": "esp32:esp32:esp32s3",
        "esp32c3": "esp32:esp32:esp32c3",
        "esp32s2": "esp32:esp32:esp32s2",
        "esp8266": "esp8266:esp8266:nodemcuv2",
        "teensy40": "teensy:avr:teensy40",
        "teensy41": "teensy:avr:teensy41",
    }

    pio_ini = project_path / "platformio.ini"
    if pio_ini.is_file():
        content = pio_ini.read_text(errors="replace")
        for line in content.splitlines():
            line = line.strip()
            if "board =" in line.lower():
                board = line.split("=", 1)[1].strip()
                for key, val in pio_to_fqbn.items():
                    if key in board.lower():
                        return val

    # arduino-cli board list（需已连接设备）
    try:
        result = subprocess.run(
            ["arduino-cli", "board", "list", "--format", "json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            for board in data.get("boards", []):
                if board.get("fqbn"):
                    return board["fqbn"]
    except Exception:
        pass

    return "arduino:avr:uno"


# ---------------------------------------------------------------------------
# 编译
# ---------------------------------------------------------------------------


def _run_command(cmd: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    """运行子进程并捕获输出。

    Args:
        cmd: 命令列表。
        cwd: 工作目录。
        timeout: 超时秒数。

    Returns:
        CompletedProcess 对象。
    """
    logger.debug("执行: %s (cwd=%s)", " ".join(cmd), cwd)
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error("命令超时: %s", " ".join(cmd))
        raise
    except FileNotFoundError:
        logger.error("命令未找到: %s", cmd[0])
        raise


def _build_platformio(project_path: Path, env: Optional[str] = None) -> dict:
    """PlatformIO 构建。

    Args:
        project_path: 项目路径。
        env: 可选的目标环境名。

    Returns:
        ``{success, output, errors, warnings}``。
    """
    if not shutil.which("pio"):
        return {
            "success": False,
            "output": "",
            "errors": ["PlatformIO CLI ('pio') 未安装或不在 PATH 中。请执行: pip install platformio"],
            "warnings": [],
        }

    cmd = ["pio", "run", "-d", str(project_path)]
    if env:
        cmd.extend(["-e", env])

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {
            "success": False,
            "output": "",
            "errors": [str(exc)],
            "warnings": [],
        }

    parsed = parse_errors(result.stdout + "\n" + result.stderr)
    errors = [e for e in parsed if e["level"] == "error"]
    warnings_list = [w for w in parsed if w["level"] == "warning"]

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": errors if errors else [result.stderr.strip()] if result.stderr.strip() else [],
        "warnings": warnings_list,
    }


def _build_cmake(
    project_path: Path,
    target: Optional[str] = None,
    definitions: Optional[dict[str, str]] = None,
    force: bool = False,
) -> dict:
    """CMake 构建。

    优先查找 ``build/`` 目录，若不存在则尝试创建。

    Args:
        project_path: 项目路径。
        target: 可选的目标名。
        definitions: 可选的 CMake -D 定义。
        force: 是否强制重新构建（等价于 ``cmake --build ... --clean-first``）。

    Returns:
        ``{success, output, errors, warnings}``。
    """
    if not shutil.which("cmake"):
        return {
            "success": False,
            "output": "",
            "errors": ["CMake 未安装或不在 PATH 中"],
            "warnings": [],
        }

    build_dir = project_path / "build"
    if not build_dir.is_dir():
        # 尝试自动配置
        logger.info("build/ 目录不存在，尝试 cmake -B build")
        try:
            configure_cmd = ["cmake", "-B", "build", "-S", "."]
            if definitions:
                for key, value in definitions.items():
                    configure_cmd.append(f"-D{key}={value}")
            result = _run_command(configure_cmd, project_path)
            if result.returncode != 0:
                return {
                    "success": False,
                    "output": result.stdout,
                    "errors": [result.stderr.strip()],
                    "warnings": [],
                }
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {
                "success": False,
                "output": "",
                "errors": [str(exc)],
                "warnings": [],
            }

    cmd = ["cmake", "--build", str(build_dir)]
    if force:
        cmd.append("--clean-first")
    if target:
        cmd.extend(["--target", target])

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {
            "success": False,
            "output": "",
            "errors": [str(exc)],
            "warnings": [],
        }

    parsed = parse_errors(result.stdout + "\n" + result.stderr)
    errors = [e for e in parsed if e["level"] == "error"]
    warnings_list = [w for w in parsed if w["level"] == "warning"]

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": errors if errors else [result.stderr.strip()] if result.stderr.strip() else [],
        "warnings": warnings_list,
    }


def _build_make(project_path: Path, target: Optional[str] = None, force: bool = False) -> dict:
    """Make 构建。

    Args:
        project_path: 项目路径。
        target: 可选的目标名。
        force: 是否强制重新构建（传递 ``-B`` 标志）。

    Returns:
        ``{success, output, errors, warnings}``。
    """
    if not shutil.which("make"):
        return {
            "success": False,
            "output": "",
            "errors": ["make 未安装或不在 PATH 中"],
            "warnings": [],
        }

    cmd = ["make", "-C", str(project_path)]
    if target:
        cmd.append(target)

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {
            "success": False,
            "output": "",
            "errors": [str(exc)],
            "warnings": [],
        }

    parsed = parse_errors(result.stdout + "\n" + result.stderr)
    errors = [e for e in parsed if e["level"] == "error"]
    warnings_list = [w for w in parsed if w["level"] == "warning"]

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": errors if errors else [result.stderr.strip()] if result.stderr.strip() else [],
        "warnings": warnings_list,
    }


def _build_arduino(project_path: Path, target: Optional[str] = None, fqbn: str = "") -> dict:
    """Arduino CLI 编译。

    Args:
        project_path: 项目路径（含 .ino 文件）。
        target: 未使用（保持接口一致）。
        fqbn: 全限定板名（如 ``esp32:esp32:esp32``），为空时自动检测。

    Returns:
        ``{success, output, errors, warnings}``。
    """
    if not shutil.which("arduino-cli"):
        return {
            "success": False,
            "output": "",
            "errors": ["arduino-cli 未安装或不在 PATH 中。请参见: https://arduino.github.io/arduino-cli/"],
            "warnings": [],
        }

    if not fqbn:
        fqbn = _detect_arduino_fqbn(project_path)

    # 找到 .ino 文件
    ino_files = list(project_path.glob("*.ino"))
    if not ino_files:
        return {
            "success": False,
            "output": "",
            "errors": ["未找到 .ino 文件"],
            "warnings": [],
        }

    cmd = ["arduino-cli", "compile", "--fqbn", fqbn, str(project_path)]

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {
            "success": False,
            "output": "",
            "errors": [str(exc)],
            "warnings": [],
        }

    parsed = parse_errors(result.stdout + "\n" + result.stderr)
    errors = [e for e in parsed if e["level"] == "error"]
    warnings_list = [w for w in parsed if w["level"] == "warning"]

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": errors if errors else [result.stderr.strip()] if result.stderr.strip() else [],
        "warnings": warnings_list,
    }


def _detect_esp_idf_target(project_path: Path) -> str:
    """Infer ESP-IDF target from sdkconfig or PlatformIO board metadata."""
    sdkconfig = project_path / "sdkconfig"
    if sdkconfig.is_file():
        content = sdkconfig.read_text(errors="replace")
        for line in content.splitlines():
            if "CONFIG_IDF_TARGET=" in line:
                return line.split("=", 1)[1].strip().strip('"')

    pio_ini = project_path / "platformio.ini"
    if pio_ini.is_file():
        content = pio_ini.read_text(errors="replace")
        chip_map = {
            "esp32s3": "esp32s3",
            "esp32-s3": "esp32s3",
            "esp32c3": "esp32c3",
            "esp32-c3": "esp32c3",
            "esp32s2": "esp32s2",
            "esp32-s2": "esp32s2",
        }
        for line in content.splitlines():
            if "board =" not in line.lower():
                continue
            board = line.split("=", 1)[1].strip().lower()
            for key, target in chip_map.items():
                if key in board:
                    return target

    return "esp32"


def _build_esp_idf(project_path: Path, chip: Optional[str] = None) -> dict:
    """ESP-IDF build via idf.py."""
    if not shutil.which("idf.py"):
        return {
            "success": False,
            "output": "",
            "errors": ["ESP-IDF idf.py 未安装或未进入 ESP-IDF 环境"],
            "warnings": [],
        }

    from agent.platforms.esp32 import ESP32Platform

    target = ESP32Platform().idf_target(chip or _detect_esp_idf_target(project_path))
    output_parts: list[str] = []

    try:
        set_target = _run_command(["idf.py", "set-target", target], project_path)
        output_parts.append(set_target.stdout)
        if set_target.returncode != 0:
            return {
                "success": False,
                "output": "\n".join(output_parts),
                "errors": [set_target.stderr.strip()] if set_target.stderr.strip() else [],
                "warnings": [],
            }

        build = _run_command(["idf.py", "build"], project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {
            "success": False,
            "output": "\n".join(output_parts),
            "errors": [str(exc)],
            "warnings": [],
        }

    output_parts.append(build.stdout)
    parsed = parse_errors(build.stdout + "\n" + build.stderr)
    errors = [e for e in parsed if e["level"] == "error"]
    warnings_list = [w for w in parsed if w["level"] == "warning"]

    return {
        "success": build.returncode == 0,
        "output": "\n".join(output_parts),
        "errors": errors if errors else [build.stderr.strip()] if build.stderr.strip() and build.returncode != 0 else [],
        "warnings": warnings_list,
    }


def _is_zephyr_project(project_path: Path) -> bool:
    cmake_lists = project_path / "CMakeLists.txt"
    if not cmake_lists.is_file():
        return False
    content = cmake_lists.read_text(errors="replace")
    return "Zephyr" in content or "ZEPHYR_BASE" in content


def _build_west(project_path: Path, chip: Optional[str] = None) -> dict:
    """Zephyr/NCS build via west."""
    if not shutil.which("west"):
        return {
            "success": False,
            "output": "",
            "errors": ["west 未安装或未进入 Zephyr/nRF Connect SDK 环境"],
            "warnings": [],
        }

    from agent.platforms.nordic import NordicPlatform

    board = NordicPlatform()._variant_to_board(chip or "nRF52840")
    cmd = ["west", "build", "-b", board, str(project_path)]

    try:
        result = _run_command(cmd, project_path)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {
            "success": False,
            "output": "",
            "errors": [str(exc)],
            "warnings": [],
        }

    parsed = parse_errors(result.stdout + "\n" + result.stderr)
    errors = [e for e in parsed if e["level"] == "error"]
    warnings_list = [w for w in parsed if w["level"] == "warning"]

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "errors": errors if errors else [result.stderr.strip()] if result.stderr.strip() and result.returncode != 0 else [],
        "warnings": warnings_list,
    }


_BUILDERS = {
    "platformio": _build_platformio,
    "cmake": _build_cmake,
    "make": _build_make,
    "arduino": _build_arduino,
}


def build_firmware(
    project_path: str,
    target: Optional[str] = None,
    env: Optional[str] = None,
    platform: Optional[str] = None,
    chip: Optional[str] = None,
    force: bool = False,
) -> dict:
    """编译固件项目。

    自动检测构建系统并调用对应的工具链。
    所有子进程均有 300 秒超时保护。

    Args:
        project_path: 项目根目录路径。
        target: 可选的目标名（cmake/make 构建目标）。
        env: 可选的 PlatformIO 环境名。
        platform: 可选的目标平台名，用于补充平台特定构建参数。
        chip: 可选的目标芯片型号，用于补充平台特定构建参数。
        force: 是否强制重新构建（cmake 传递 ``--clean-first``）。

    Returns:
        编译结果 dict::

            {
                "success": bool,
                "output": str,      # 标准输出
                "errors": list,     # 错误信息列表（字符串或解析后的 dict）
                "warnings": list,   # 警告信息列表（解析后的 dict）
            }
    """
    root = Path(project_path).resolve()
    build_system = detect_build_system(str(root))

    if build_system is None:
        return {
            "success": False,
            "output": "",
            "errors": [f"未检测到已知构建系统。请确保项目路径正确: {root}"],
            "warnings": [],
        }

    logger.info("构建系统: %s，项目: %s", build_system, root)

    platform_name = (platform or "").lower()
    if platform_name in ("esp32", "esp", "espressif") and build_system == "cmake":
        return _build_esp_idf(root, chip=chip)
    if platform_name in ("nordic", "nrf") and build_system == "cmake" and _is_zephyr_project(root):
        return _build_west(root, chip=chip)

    builder = _BUILDERS[build_system]

    # PlatformIO 的 env 通过关键字参数传递
    if build_system == "platformio":
        return builder(root, env=env)
    elif build_system == "cmake":
        definitions: dict[str, str] = {}
        if chip:
            definitions["CHIP"] = chip
        if platform_name in ("stm32", "st"):
            from agent.platforms.stm32 import STM32Platform
            definitions.update(STM32Platform().get_cmake_definitions(chip or ""))
        if platform and chip and platform.lower() in ("nordic", "nrf"):
            from agent.platforms.nordic import NordicPlatform
            definitions["BOARD"] = NordicPlatform()._variant_to_board(chip)
        return builder(root, target=target, definitions=definitions or None, force=force)
    elif build_system == "make":
        return builder(root, target=target, force=force)
    else:
        return builder(root, target=target)


# ---------------------------------------------------------------------------
# 错误解析
# ---------------------------------------------------------------------------


def parse_errors(output: str) -> list[dict]:
    """从编译器输出中提取错误和警告行。

    支持 GCC/Clang 风格的 ``file:line:col: level: message`` 格式。

    Args:
        output: 编译器输出文本。

    Returns:
        解析后的诊断信息列表::

            [
                {
                    "file": str,
                    "line": int,
                    "column": int,
                    "level": str,      # "error" / "warning" / "note"
                    "message": str,
                },
                ...
            ]
    """
    errors: list[dict] = []
    for line in output.splitlines():
        m = _ERROR_PATTERN.match(line.strip())
        if m:
            errors.append({
                "file": m.group("file"),
                "line": int(m.group("line")),
                "column": int(m.group("col")),
                "level": m.group("level").lower(),
                "message": m.group("message"),
            })
    return errors


# ---------------------------------------------------------------------------
# 编译标志提取
# ---------------------------------------------------------------------------


def get_build_flags(project_path: str) -> list[str]:
    """从项目中提取编译标志。

    支持从以下来源提取:
        - ``platformio.ini`` 中的 ``build_flags``
        - ``CMakeLists.txt`` 中的 ``target_compile_options``

    Args:
        project_path: 项目根目录路径。

    Returns:
        编译标志字符串列表。
    """
    root = Path(project_path).resolve()
    flags: list[str] = []

    # PlatformIO: 解析 platformio.ini
    pio_ini = root / "platformio.ini"
    if pio_ini.is_file():
        try:
            content = pio_ini.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("build_flags"):
                    # 提取 = 后的内容
                    parts = stripped.split("=", 1)
                    if len(parts) == 2:
                        value = parts[1].strip()
                        # 可能有多行风格，简单处理
                        flags.extend([f.strip() for f in value.split() if f.strip()])
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("读取 platformio.ini 失败: %s", exc)

    # CMake: 在 CMakeLists.txt 中搜索编译选项
    cmake_lists = root / "CMakeLists.txt"
    if cmake_lists.is_file():
        try:
            content = cmake_lists.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if "target_compile_options" in stripped or "add_compile_options" in stripped:
                    # 简单提取引号中的内容
                    matches = re.findall(r'["\']([^"\']+)["\']', stripped)
                    flags.extend(matches)
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("读取 CMakeLists.txt 失败: %s", exc)

    return flags


# ---------------------------------------------------------------------------
# 工具链信息
# ---------------------------------------------------------------------------


def _run_and_capture(cmd: list[str], timeout: int = 10) -> Optional[str]:
    """运行命令并捕获第一行输出。"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("命令 %s 不可用: %s", cmd[0], exc)
    return None


def get_toolchain_info(project_path: str) -> dict:
    """检测项目的工具链信息。

    检测项: 编译器（gcc/clang/g++）、版本、目标架构等。

    Args:
        project_path: 项目根目录路径。

    Returns:
        工具链信息 dict::

            {
                "toolchain": str,           # 编译器系列名称，如 "arm-none-eabi-gcc"
                "compiler": str,            # 编译器可执行文件名
                "compiler_version": str,    # 版本字符串
                "target_arch": str,         # 目标架构（arm/cortex-m4/riscv32/xtensa 等）
                "has_debug": bool,          # 是否含调试信息
            }
    """
    root = Path(project_path).resolve()
    result: dict = {
        "toolchain": "",
        "compiler": "",
        "compiler_version": "",
        "target_arch": "",
        "has_debug": False,
    }

    # 先尝试从 PlatformIO 配置中获取工具链信息
    pio_ini = root / "platformio.ini"
    if pio_ini.is_file():
        try:
            content = pio_ini.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("platform"):
                    parts = stripped.split("=", 1)
                    if len(parts) == 2:
                        platform_val = parts[1].strip()
                        if "espressif" in platform_val:
                            result["target_arch"] = "xtensa"
                        elif "ststm32" in platform_val or "atmelsam" in platform_val or "nordicnrf" in platform_val:
                            result["target_arch"] = "cortex-m"
                if stripped.startswith("board"):
                    parts = stripped.split("=", 1)
                    if len(parts) == 2:
                        result["toolchain"] = parts[1].strip()
                if stripped.startswith("build_type") and "debug" in stripped.lower():
                    result["has_debug"] = True
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("读取 platformio.ini 失败: %s", exc)

    # 检测 GCC 工具链
    # 按优先级查找嵌入式工具链
    cross_compilers = [
        "arm-none-eabi-gcc",
        "arm-linux-gnueabihf-gcc",
        "riscv64-unknown-elf-gcc",
        "riscv32-unknown-elf-gcc",
        "xtensa-esp32-elf-gcc",
        "xtensa-lx106-elf-gcc",
        "avr-gcc",
    ]

    for compiler in cross_compilers:
        if shutil.which(compiler):
            result["compiler"] = compiler
            result["toolchain"] = compiler.split("-")[0] if not result["toolchain"] else result["toolchain"]
            version = _run_and_capture([compiler, "--version"])
            if version:
                result["compiler_version"] = version
            break

    # 回退到本地 GCC
    if not result["compiler"]:
        for cc in ("gcc", "g++", "clang"):
            if shutil.which(cc):
                result["compiler"] = cc
                version = _run_and_capture([cc, "--version"])
                if version:
                    result["compiler_version"] = version
                break

    # 检测目标架构（通过 CMake）
    cmake_lists = root / "CMakeLists.txt"
    if cmake_lists.is_file() and not result["target_arch"]:
        try:
            content = cmake_lists.read_text(encoding="utf-8")
            arch_patterns = [
                (r"CMAKE_SYSTEM_PROCESSOR\s+(\w+)", 1),
                (r"ARM|CORTEX-M(\d)", 0),
                (r"ESP32", 0),
                (r"STM32", 0),
                (r"RISCV|riscv", 0),
            ]
            for pattern, group in arch_patterns:
                m = re.search(pattern, content, re.IGNORECASE)
                if m:
                    result["target_arch"] = m.group(0) if group == 0 else m.group(group)
                    break
        except (OSError, UnicodeDecodeError):
            pass

    return result
