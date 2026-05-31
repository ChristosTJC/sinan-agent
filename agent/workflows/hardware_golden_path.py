"""
硬件黄金路径工作流 —— 端到端自动化流水线。

将板卡检测 → 固件编译 → 固件烧写 → 串口验证串联为一条完整的
自动化流水线，单次调用即可完成从源码到目标设备运行的完整闭环。

典型用法::

    from agent.workflows import HardwareGoldenPath

    path = HardwareGoldenPath()
    result = path.run("/path/to/firmware/project")
    print(result["success"])        # True/False
    print(result["total_duration_ms"])

干运行模式仅检测板卡和构建工具可用性，不实际执行编译/烧写::

    dry = path.run_dry("/path/to/firmware/project")
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

from agent.tools import get_registry
from agent.tools.serial_scanner import identify_board, get_device_info

# ---------------------------------------------------------------------------
# 引导成功模式 —— 用于验证固件启动
# ---------------------------------------------------------------------------

_BOOT_PATTERNS = [
    "Boot",
    "Ready",
    "OK",
    "init done",
    "initialized",
    "startup complete",
    "system ready",
    "firmware started",
]


class HardwareGoldenPath:
    """硬件黄金路径 —— 从源码到目标设备的全自动流水线。

    串联四个阶段的硬件工作流:
        1. **板卡检测** —— 扫描串口/USB 端口并识别目标设备
        2. **固件编译** —— 检测构建系统并编译项目
        3. **固件烧写** —— 将编译产物烧录到目标设备
        4. **串口验证** —— 监控串口输出确认固件启动

    每个阶段独立计时，任一阶段失败即终止后续阶段。
    支持干运行模式（仅检测不执行），适合 CI/管线预检。

    Attributes:
        _reg: 工具注册中心实例，用于调用底层硬件工具。
    """

    def __init__(self, registry: Optional[Any] = None) -> None:
        """初始化硬件黄金路径。

        Args:
            registry: 可选的 ToolRegistry 实例。为 None 时自动从
                      ``agent.tools.get_registry()`` 获取全局单例。
        """
        if registry is None:
            registry = get_registry()
        self._reg = registry

    # ------------------------------------------------------------------
    # 阶段 1: 板卡检测
    # ------------------------------------------------------------------

    def detect_board(self) -> dict:
        """检测并识别连接的嵌入式板卡。

        流程:
            1. 通过 ``scan_serial`` 工具扫描所有可用串口
            2. 对每个端口调用 ``identify_board`` 尝试识别板卡型号
            3. 通过 ``scan_usb`` 工具获取 USB VID/PID 信息

        Returns:
            板卡检测结果::

                {
                    "success": bool,
                    "board_type": str | None,     # 识别到的板卡型号
                    "ports": list[str],           # 可用端口列表
                    "vid_pid": list[dict] | None, # USB 设备信息
                    "error": str | None,          # 失败原因
                }
        """
        result: dict[str, Any] = {
            "success": False,
            "board_type": None,
            "ports": [],
            "vid_pid": None,
            "error": None,
        }

        # 步骤 1: 扫描串口
        scan_resp = self._reg.call_tool("scan_serial", {})
        if not scan_resp.get("success", False):
            result["error"] = scan_resp.get("error", "串口扫描失败")
            return result

        ports_raw = scan_resp.get("result", [])
        port_paths = [p.get("port", p.get("device", "")) for p in ports_raw if p]
        port_paths = [p for p in port_paths if p]
        result["ports"] = port_paths

        if not port_paths:
            result["error"] = "未检测到任何串口设备"
            return result

        # 步骤 2: 对每个端口尝试板卡识别
        board_type = None
        for port in port_paths:
            try:
                board = identify_board(port)
                if board:
                    board_type = board
                    break
            except Exception:
                continue
        result["board_type"] = board_type

        # 步骤 3: 扫描 USB 获取 VID/PID 信息
        usb_resp = self._reg.call_tool("scan_usb", {})
        if usb_resp.get("success", False):
            vid_pid_info = usb_resp.get("result", [])
            if vid_pid_info:
                # 丰富每条设备的芯片系列信息
                enriched = []
                for dev in vid_pid_info:
                    vid = dev.get("vid", "")
                    pid = dev.get("pid", "")
                    if vid and pid:
                        info = get_device_info(vid, pid)
                        if info:
                            dev["device_name"] = info.get("device", "")
                            dev["family"] = info.get("family", "")
                            dev["vendor_name"] = info.get("vendor", "")
                    enriched.append(dev)
                result["vid_pid"] = enriched

        result["success"] = True
        return result

    # ------------------------------------------------------------------
    # 阶段 2: 固件编译
    # ------------------------------------------------------------------

    def build_firmware(self, project_path: str) -> dict:
        """编译固件项目。

        Args:
            project_path: 固件项目根目录路径。

        Returns:
            编译结果 dict，直接透传 ``build_firmware`` 工具的输出::

                {
                    "success": bool,
                    "output": str,
                    "errors": list,
                    "warnings": list,
                }
        """
        return self._reg.call_tool("build_firmware", {
            "project_path": project_path,
        })

    # ------------------------------------------------------------------
    # 阶段 3: 固件烧写
    # ------------------------------------------------------------------

    def flash_firmware(
        self,
        project_path: str,
        port: str,
        method: str = "auto",
    ) -> dict:
        """将编译产物烧写到目标设备。

        Args:
            project_path: 固件项目根目录路径。
            port: 目标串口/调试端口路径（如 ``/dev/ttyUSB0``）。
            method: 烧写方法。默认 ``"auto"`` 自动检测，也可显式指定
                    ``"platformio"`` / ``"esptool"`` / ``"stm32cubeprog"`` /
                    ``"openocd"`` / ``"jlink"`` / ``"arduino"``。

        Returns:
            烧写结果 dict，直接透传 ``flash_firmware`` 工具的输出::

                {
                    "success": bool,
                    "output": str,
                    "errors": list,
                }
        """
        if not port:
            return {
                "success": False,
                "output": "",
                "errors": ["缺少必要参数: port"],
            }
        return self._reg.call_tool("flash_firmware", {
            "project_path": project_path,
            "port": port,
            "method": method,
        })

    # ------------------------------------------------------------------
    # 阶段 4: 串口验证
    # ------------------------------------------------------------------

    def verify_firmware(
        self,
        port: str,
        baudrate: int = 115200,
        timeout_sec: float = 10.0,
    ) -> dict:
        """烧写后监控串口输出，确认固件启动。

        打开串口监听指定时长，检查输出中是否包含已知的引导成功模式
        （如 ``"Boot"``、``"Ready"``、``"OK"``、``"init done"`` 等）。

        Args:
            port: 串口端口路径。
            baudrate: 波特率，默认 115200。
            timeout_sec: 监控持续时长（秒），默认 10.0。

        Returns:
            验证结果::

                {
                    "success": bool,
                    "boot_detected": bool,       # 是否检测到引导成功信号
                    "output_lines": list[str],   # 串口输出行列表
                    "pattern_matched": str | None, # 匹配到的引导模式
                }
        """
        result: dict[str, Any] = {
            "success": False,
            "boot_detected": False,
            "output_lines": [],
            "pattern_matched": None,
        }

        if not port:
            result["error"] = "缺少必要参数: port"
            return result

        # 调用串口监控工具
        monitor_resp = self._reg.call_tool("serial_monitor", {
            "port": port,
            "baudrate": baudrate,
            "duration_sec": timeout_sec,
        })

        if not monitor_resp.get("success", False):
            result["error"] = monitor_resp.get("error", "串口监控失败")
            return result

        lines = monitor_resp.get("lines", [])
        result["output_lines"] = lines

        # 扫描引导成功模式
        combined = "\n".join(lines)
        for pattern in _BOOT_PATTERNS:
            if pattern.lower() in combined.lower():
                result["boot_detected"] = True
                result["pattern_matched"] = pattern
                break

        result["success"] = True
        return result

    # ------------------------------------------------------------------
    # 完整流水线
    # ------------------------------------------------------------------

    def run(
        self,
        project_path: str,
        baudrate: int = 115200,
    ) -> dict:
        """执行完整的黄金路径流水线: 检测 → 编译 → 烧写 → 验证。

        每个阶段独立计时，任一阶段失败即终止后续阶段:
        - 板卡检测失败 → 不执行编译
        - 编译失败 → 不执行烧写
        - 烧写失败 → 不执行验证

        Args:
            project_path: 固件项目根目录路径。
            baudrate: 串口波特率，默认 115200。

        Returns:
            完整流水线结果::

                {
                    "success": bool,
                    "phases": [
                        {"phase": "detect",  "status": "ok"|"fail", "result": dict, "duration_ms": float},
                        {"phase": "build",   "status": "ok"|"fail", "result": dict, "duration_ms": float},
                        {"phase": "flash",   "status": "ok"|"fail", "result": dict, "duration_ms": float},
                        {"phase": "verify",  "status": "ok"|"fail", "result": dict, "duration_ms": float},
                    ],
                    "board_info": dict,          # 板卡检测结果
                    "flash_result": dict,        # 烧写结果
                    "boot_detected": bool,       # 是否检测到引导成功
                    "total_duration_ms": float,  # 总耗时（毫秒）
                    "error": str | None,         # 失败阶段描述
                }
        """
        t_start = time.monotonic()
        phases: list[dict] = []
        board_info: dict = {}
        flash_result: dict = {}
        boot_detected = False
        flash_port = ""

        # ── 阶段 1: 板卡检测 ──
        t0 = time.monotonic()
        board_info = self.detect_board()
        phase_detect = {
            "phase": "detect",
            "status": "ok" if board_info.get("success") else "fail",
            "result": board_info,
            "duration_ms": round((time.monotonic() - t0) * 1000, 2),
        }
        phases.append(phase_detect)

        if not board_info.get("success"):
            return {
                "success": False,
                "phases": phases,
                "board_info": board_info,
                "flash_result": {},
                "boot_detected": False,
                "total_duration_ms": round((time.monotonic() - t_start) * 1000, 2),
                "error": f"板卡检测失败: {board_info.get('error', '未知错误')}",
            }

        # ── 阶段 2: 固件编译 ──
        t0 = time.monotonic()
        build_result = self.build_firmware(project_path)
        phase_build = {
            "phase": "build",
            "status": "ok" if build_result.get("success") else "fail",
            "result": build_result,
            "duration_ms": round((time.monotonic() - t0) * 1000, 2),
        }
        phases.append(phase_build)

        if not build_result.get("success"):
            return {
                "success": False,
                "phases": phases,
                "board_info": board_info,
                "flash_result": {},
                "boot_detected": False,
                "total_duration_ms": round((time.monotonic() - t_start) * 1000, 2),
                "error": "固件编译失败",
            }

        # ── 阶段 3: 固件烧写 ──
        ports = board_info.get("ports", [])
        if not ports:
            return {
                "success": False,
                "phases": phases,
                "board_info": board_info,
                "flash_result": {},
                "boot_detected": False,
                "total_duration_ms": round((time.monotonic() - t_start) * 1000, 2),
                "error": "未检测到可用端口，无法烧写",
            }
        flash_port = ports[0]

        t0 = time.monotonic()
        flash_result = self.flash_firmware(project_path, port=flash_port)
        phase_flash = {
            "phase": "flash",
            "status": "ok" if flash_result.get("success") else "fail",
            "result": flash_result,
            "duration_ms": round((time.monotonic() - t0) * 1000, 2),
        }
        phases.append(phase_flash)

        if not flash_result.get("success"):
            return {
                "success": False,
                "phases": phases,
                "board_info": board_info,
                "flash_result": flash_result,
                "boot_detected": False,
                "total_duration_ms": round((time.monotonic() - t_start) * 1000, 2),
                "error": "固件烧写失败",
            }

        # ── 阶段 4: 串口验证 ──
        t0 = time.monotonic()
        verify_result = self.verify_firmware(port=flash_port, baudrate=baudrate)
        boot_detected = verify_result.get("boot_detected", False)
        phase_verify = {
            "phase": "verify",
            "status": "ok" if verify_result.get("success") else "fail",
            "result": verify_result,
            "duration_ms": round((time.monotonic() - t0) * 1000, 2),
        }
        phases.append(phase_verify)

        return {
            "success": True,
            "phases": phases,
            "board_info": board_info,
            "flash_result": flash_result,
            "boot_detected": boot_detected,
            "total_duration_ms": round((time.monotonic() - t_start) * 1000, 2),
            "error": None,
        }

    # ------------------------------------------------------------------
    # 干运行
    # ------------------------------------------------------------------

    def run_dry(self, project_path: str) -> dict:
        """干运行模式 —— 仅检测板卡和构建工具可用性，不实际执行编译/烧写。

        适用于 CI/管线预检场景：在真正执行前快速验证硬件环境是否就绪。

        Args:
            project_path: 固件项目根目录路径。

        Returns:
            干运行结果::

                {
                    "success": bool,
                    "board_detected": bool,       # 是否检测到板卡
                    "board_type": str | None,     # 识别到的板卡型号
                    "ports": list[str],           # 可用端口列表
                    "build_tools_available": bool, # 构建工具是否可用
                    "error": str | None,
                }
        """
        result: dict[str, Any] = {
            "success": False,
            "board_detected": False,
            "board_type": None,
            "ports": [],
            "build_tools_available": False,
            "error": None,
        }

        # 检测板卡
        board_info = self.detect_board()
        result["board_detected"] = board_info.get("success", False)
        result["board_type"] = board_info.get("board_type")
        result["ports"] = board_info.get("ports", [])

        if not board_info.get("success"):
            result["error"] = board_info.get("error", "板卡检测失败")
            return result

        # 检测构建工具可用性（通过 build_firmware 工具的存在性验证，
        # 不实际执行编译）
        try:
            from agent.tools.firmware_builder import detect_build_system
            build_sys = detect_build_system(project_path)
            result["build_tools_available"] = build_sys is not None
            if not result["build_tools_available"]:
                result["error"] = f"未在项目路径检测到已知构建系统: {project_path}"
        except ImportError:
            result["build_tools_available"] = False
            result["error"] = "firmware_builder 模块不可用"

        result["success"] = result["board_detected"] and result["build_tools_available"]
        return result
