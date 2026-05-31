"""
Sinán 嵌入式 Agent —— 硬件工具层。

提供嵌入式开发全流程所需的底层硬件交互能力：
- 串口/USB 扫描与板卡识别
- 串口监控与数据采集
- 固件编译（PlatformIO/CMake/Make/Arduino）
- 固件烧写（esptool/STM32CubeProg/OpenOCD/J-Link）
- 设备桥接（JSONL-over-TCP Micius 协议）
- 传感器数据读取与统计

工具注册中心 ``ToolRegistry`` 负责发现和管理所有工具，
将工具函数包装为统一的调用入口，供 Agent 调度使用。
"""

import inspect
import logging
import re
from typing import Any, Callable, Optional
from enum import Enum


class DangerLevel(str, Enum):
    """工具危险等级"""
    SAFE = "safe"       # 只读，无副作用
    LOW = "low"         # 可逆操作
    MEDIUM = "medium"   # 需确认的写操作
    HIGH = "high"       # 不可逆操作（擦除、格式化）


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Docstring 解析辅助函数
# ---------------------------------------------------------------------------


def _extract_description(fn: Callable) -> str:
    """从函数的 docstring 提取第一行作为描述。"""
    doc = inspect.getdoc(fn)
    if not doc:
        return ""
    return doc.splitlines()[0].strip()


def _parse_params_from_docstring(fn: Callable) -> dict:
    """从函数的 docstring 解析参数 schema。

    支持 Google 风格 Args 段::

        Args:
            port (str): 串口端口路径 [required]
            baudrate (int): 波特率 (默认 115200)
            duration_sec (float): 监控时长秒数
    """
    doc = inspect.getdoc(fn)
    if not doc:
        return {}

    # 提取 Args 段
    args_match = re.search(
        r"Args:\s*\n((?:\s+\w.*\n?)+)",
        doc,
        re.MULTILINE,
    )
    if not args_match:
        return {}

    params: dict = {}
    _TYPE_MAP = {
        "str": "string", "int": "integer", "float": "number",
        "bool": "boolean", "dict": "object", "list": "array",
    }

    for m in re.finditer(
        r"(\w+)\s*\(([^)]+)\)\s*:\s*(.+)",
        args_match.group(1),
    ):
        name = m.group(1)
        py_type = m.group(2).strip().split(",")[0]  # 取第一个类型
        desc = m.group(3).strip()
        required = "[required]" in desc
        desc = desc.replace("[required]", "").strip()

        params[name] = {
            "type": _TYPE_MAP.get(py_type, "string"),
            "description": desc,
            "required": required,
        }

    return params


import time as _time
import json as _json
from datetime import datetime as _datetime
from pathlib import Path as _Path
import threading as _threading


class AuditLogger:
    """结构化审计日志记录器 —— 记录每次工具调用的完整上下文。

    Attributes:
        _log_path: 审计日志文件路径
        _lock: 线程安全锁
    """
    def __init__(self, log_dir: str = ""):
        self._log_dir = _Path(log_dir) if log_dir else _Path.home() / ".sinan" / "audit"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = _threading.Lock()

    def log_tool_call(self, tool_name: str, danger_level: str, arguments: dict,
                      result: dict, duration_ms: float, success: bool):
        """记录一次工具调用。"""
        entry = {
            "timestamp": _datetime.now().isoformat(),
            "tool": tool_name,
            "danger_level": danger_level,
            "arguments": {k: v for k, v in arguments.items() if k != "data"},
            "success": success,
            "duration_ms": round(duration_ms, 2),
            "result_summary": str(result.get("error", "ok"))[:200] if not success else "ok"
        }
        log_file = self._log_dir / f"audit-{_datetime.now().strftime('%Y%m%d')}.jsonl"
        with self._lock:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(_json.dumps(entry, ensure_ascii=False) + "\n")

    def query(self, tool_name: str = None, date: str = None, limit: int = 100) -> list[dict]:
        """查询审计日志。"""
        results = []
        pattern = f"audit-{date}.jsonl" if date else "audit-*.jsonl"
        for log_file in sorted(self._log_dir.glob(pattern), reverse=True):
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    entry = _json.loads(line.strip())
                    if tool_name and entry.get("tool") != tool_name:
                        continue
                    results.append(entry)
                    if len(results) >= limit:
                        return results
        return results


# ---------------------------------------------------------------------------
# 工具注册中心
# ---------------------------------------------------------------------------


class ToolRegistry:
    """工具注册中心 —— 发现和管理所有硬件工具。

    每个工具是一个可调用对象，通过 ``name`` 唯一标识。
    工具注册后可通过 ``call_tool`` 统一调用，Agent 无需
    感知每个工具的具体模块来源。

    Attributes:
        _tools: 已注册工具的字典 ``{name: handler}``。
        _schemas: 工具 schema 缓存。
    """

    def __init__(self) -> None:
        """初始化工具注册中心。"""
        self._tools: dict[str, Callable] = {}
        self._meta: dict[str, dict] = {}       # {name: {description, parameters}}
        self._dangerous: set[str] = set()       # 危险工具集合 (已弃用，保留向后兼容)
        self._danger_levels: dict[str, DangerLevel] = {}
        self._timeouts: dict[str, float] = {}
        self._audit = AuditLogger()
        self._schemas: Optional[list[dict]] = None
        self._memory_tools_registered: bool = False

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        handler: Optional[Callable] = None,
        *,
        func: Optional[Callable] = None,
        description: str = "",
        parameters: Optional[dict] = None,
        dangerous: bool = False,
        danger_level: DangerLevel = DangerLevel.SAFE,
        timeout_sec: float = 30.0,
        **_: Any,
    ) -> None:
        """注册一个工具。

        Args:
            name: 工具唯一名称。
            handler: 工具对应的可调用对象。
            description: 工具描述 (可从 docstring 自动提取)。
            parameters: 参数 schema dict。为 None 时尝试从 docstring 解析。
            dangerous: 是否为危险工具 (已弃用，请改用 danger_level)。
            danger_level: 工具危险等级。
            timeout_sec: 工具执行超时时间 (秒)。
        """
        if handler is None:
            handler = func
        if handler is None:
            raise ValueError("缺少工具处理函数")
        if name in self._tools:
            raise ValueError(f"工具 '{name}' 已经注册，请勿重复注册")
        self._tools[name] = handler
        # 自动提取描述
        if not description:
            description = _extract_description(handler)
        # 自动解析参数
        if parameters is None:
            parameters = _parse_params_from_docstring(handler)
        self._meta[name] = {"description": description, "parameters": parameters}
        # 已弃用: 保留 _dangerous 集合向后兼容
        if dangerous:
            self._dangerous.add(name)
        self._danger_levels[name] = danger_level
        self._timeouts[name] = timeout_sec
        self._schemas = None
        logger.debug("工具已注册: %s (danger_level=%s, timeout=%.1fs)", name, danger_level.value, timeout_sec)

    def register_all(self, tools: dict[str, Callable]) -> None:
        """批量注册工具。

        Args:
            tools: ``{name: handler}`` 映射字典。
        """
        for name, handler in tools.items():
            self.register(name, handler)

    def unregister(self, name: str) -> None:
        """取消注册一个工具。"""
        if name in self._tools:
            del self._tools[name]
            self._meta.pop(name, None)
            self._schemas = None
            logger.debug("工具已注销: %s", name)

    def is_dangerous(self, name: str) -> bool:
        """检查工具是否为危险工具（需要用户确认）。

        Args:
            name: 工具名称。

        Returns:
            True 表示危险工具。
        """
        # 已弃用: 保留 _dangerous 集合向后兼容，新代码应使用 get_danger_level()
        if name in self._dangerous:
            return True
        return self._danger_levels.get(name, DangerLevel.SAFE) != DangerLevel.SAFE

    def get_danger_level(self, name: str) -> DangerLevel:
        """获取工具的 DangerLevel 等级。

        Args:
            name: 工具名称。

        Returns:
            DangerLevel 枚举值。
        """
        return self._danger_levels.get(name, DangerLevel.SAFE)

    # ------------------------------------------------------------------
    # 发现
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """自动发现并注册所有内置硬件工具。

        包括以下 10 个工具::

            scan_usb         - 扫描 USB 设备
            scan_serial      - 扫描串口端口
            serial_monitor   - 监控串口输出
            serial_write     - 向串口写数据
            build_firmware   - 编译固件
            flash_firmware   - 烧写固件
            device_probe     - 探测设备节点
            device_call      - 调用设备端工具
            read_sensor      - 读取传感器数据
            capture_camera   - 捕获相机图像

        每个工具的注册是惰性的 —— 只有首次 discover() 时才导入
        对应的模块，避免所有依赖同时加载。
        """
        if self._tools:
            logger.info("工具已注册，跳过自动发现（当前已注册 %d 个工具）", len(self._tools))
            return

        # ── scan_usb ──
        try:
            from agent.tools.serial_scanner import scan_usb_devices

            self.register("scan_usb", scan_usb_devices, description="扫描 USB 设备")
        except ImportError as exc:
            logger.warning("工具 scan_usb 不可用: %s", exc)

        # ── scan_serial ──
        try:
            from agent.tools.serial_scanner import scan_serial_ports

            self.register("scan_serial", scan_serial_ports, description="扫描串口端口")
        except ImportError as exc:
            logger.warning("工具 scan_serial 不可用: %s", exc)

        # ── serial_monitor ──
        try:
            from agent.tools.serial_monitor import SerialMonitor

            def _serial_monitor_handler(arguments: dict) -> dict:
                """后台调用 SerialMonitor.monitor()"""
                port = arguments.get("port", "")
                baudrate = arguments.get("baudrate", 115200)
                duration = float(arguments.get("duration_sec", 5.0))
                if not port:
                    return {"success": False, "error": "缺少参数: port"}

                try:
                    monitor = SerialMonitor(port=port, baudrate=baudrate)
                    if not monitor.open():
                        return {"success": False, "error": f"无法打开串口 {port}"}

                    lines = monitor.monitor(duration_sec=duration)
                    monitor.close()
                    return {
                        "success": True,
                        "port": port,
                        "lines": lines,
                        "line_count": len(lines),
                        "data": "\n".join(lines),
                    }
                except Exception as exc:
                    return {"success": False, "error": f"串口监控异常: {exc}"}

            self.register(
                "serial_monitor", _serial_monitor_handler,
                description="监控串口输出",
                parameters={
                    "port": {"type": "string", "description": "串口端口路径", "required": True},
                    "baudrate": {"type": "integer", "description": "波特率 (默认 115200)", "required": False},
                    "duration_sec": {"type": "number", "description": "监控时长秒数 (默认 5.0)", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 serial_monitor 不可用: %s", exc)

        # ── serial_write ──
        try:
            from agent.tools.serial_monitor import SerialMonitor

            def _serial_write_handler(arguments: dict) -> dict:
                """向串口写入数据"""
                port = arguments.get("port", "")
                baudrate = arguments.get("baudrate", 115200)
                data = arguments.get("data", "")
                if not port:
                    return {"success": False, "error": "缺少参数: port"}
                if not data:
                    return {"success": False, "error": "缺少参数: data"}

                try:
                    monitor = SerialMonitor(port=port, baudrate=baudrate)
                    if not monitor.open():
                        return {"success": False, "error": f"无法打开串口 {port}"}

                    if arguments.get("command_mode", False):
                        written = monitor.write_command(data)
                    else:
                        written = monitor.write(data.encode("utf-8"))

                    monitor.close()
                    return {"success": True, "port": port, "bytes_written": written}
                except Exception as exc:
                    return {"success": False, "error": f"串口写入异常: {exc}"}

            self.register(
                "serial_write", _serial_write_handler,
                description="向串口写入数据",
                danger_level=DangerLevel.HIGH, timeout_sec=10.0,
                parameters={
                    "port": {"type": "string", "description": "串口端口路径", "required": True},
                    "baudrate": {"type": "integer", "description": "波特率 (默认 115200)", "required": False},
                    "data": {"type": "string", "description": "要写入的数据", "required": True},
                    "command_mode": {"type": "boolean", "description": "是否追加换行符作为命令发送", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 serial_write 不可用: %s", exc)

        # ── build_firmware ──
        try:
            from agent.tools.firmware_builder import build_firmware as _build_fw

            def _build_firmware_handler(arguments: dict) -> dict:
                project_path = arguments.get("project_path", ".")
                target = arguments.get("target")
                env = arguments.get("env")
                return _build_fw(project_path=project_path, target=target, env=env)

            self.register(
                "build_firmware", _build_firmware_handler,
                description="编译固件",
                danger_level=DangerLevel.MEDIUM, timeout_sec=300.0,
                parameters={
                    "project_path": {"type": "string", "description": "固件项目根目录路径", "required": True},
                    "target": {"type": "string", "description": "编译目标名 (cmake/make)", "required": False},
                    "env": {"type": "string", "description": "PlatformIO 环境名", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 build_firmware 不可用: %s", exc)

        # ── flash_firmware ──
        try:
            from agent.tools.firmware_flasher import flash_firmware as _flash_fw

            def _flash_firmware_handler(arguments: dict) -> dict:
                project_path = arguments.get("project_path", ".")
                port = arguments.get("port", "")
                method = arguments.get("method", "auto")
                if not port:
                    return {"success": False, "error": "缺少参数: port"}
                return _flash_fw(project_path=project_path, port=port, method=method)

            self.register(
                "flash_firmware", _flash_firmware_handler,
                description="烧写固件到设备",
                danger_level=DangerLevel.HIGH, timeout_sec=120.0,
                parameters={
                    "project_path": {"type": "string", "description": "固件项目根目录路径", "required": True},
                    "port": {"type": "string", "description": "目标串口/调试端口路径", "required": True},
                    "method": {"type": "string", "description": "烧写方法 (auto/platformio/esptool/stm32cubeprog/openocd/jlink/arduino)", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 flash_firmware 不可用: %s", exc)

        # ── device_probe ──
        try:
            from agent.tools.device_bridge import ConnectionDiagnostics

            def _device_probe_handler(arguments: dict) -> dict:
                host = arguments.get("host", "")
                port = int(arguments.get("port", 5555))
                if not host:
                    return {"success": False, "error": "缺少参数: host"}

                diag = ConnectionDiagnostics()
                report = diag.build_report(host, port)
                tcp_ok = diag.tcp_probe(host, port)
                return {
                    "success": tcp_ok,
                    "host": host,
                    "port": port,
                    "tcp_reachable": tcp_ok,
                    "report": report,
                }

            self.register(
                "device_probe", _device_probe_handler,
                description="探测设备节点连通性",
                parameters={
                    "host": {"type": "string", "description": "设备 IP 或主机名", "required": True},
                    "port": {"type": "integer", "description": "设备端口 (默认 5555)", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 device_probe 不可用: %s", exc)

        # ── device_call ──
        try:
            from agent.tools.device_bridge import DeviceNodeClient

            def _device_call_handler(arguments: dict) -> dict:
                host = arguments.get("host", "")
                port = int(arguments.get("port", 5555))
                method = arguments.get("method", "")
                params = arguments.get("params", {})
                if not host:
                    return {"success": False, "error": "缺少参数: host"}
                if not method:
                    return {"success": False, "error": "缺少参数: method"}

                client = DeviceNodeClient(host=host, port=port)
                try:
                    return client.request(method, params)
                finally:
                    client.close()

            self.register(
                "device_call", _device_call_handler,
                description="调用设备端远程工具",
                danger_level=DangerLevel.HIGH, timeout_sec=30.0,
                parameters={
                    "host": {"type": "string", "description": "设备 IP 或主机名", "required": True},
                    "port": {"type": "integer", "description": "设备端口 (默认 5555)", "required": False},
                    "method": {"type": "string", "description": "远程 RPC 方法名", "required": True},
                    "params": {"type": "object", "description": "方法参数字典", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 device_call 不可用: %s", exc)

        # ── read_sensor ──
        try:
            from agent.tools.sensor_reader import SensorReader

            def _read_sensor_handler(arguments: dict) -> dict:
                port = arguments.get("port", "")
                baudrate = arguments.get("baudrate", 115200)
                count = int(arguments.get("count", 10))
                interval = float(arguments.get("interval_sec", 0.1))
                export_csv = arguments.get("export_csv", "")
                if not port:
                    return {"success": False, "error": "缺少参数: port"}

                reader = SensorReader(port=port, baudrate=baudrate)
                try:
                    if not reader.open():
                        return {"success": False, "error": f"无法打开串口 {port}"}

                    samples = reader.collect_samples(count=count, interval_sec=interval)
                    stats = SensorReader.summary(samples) if samples else {}

                    if export_csv:
                        SensorReader.export_csv(samples, export_csv)

                    return {
                        "success": True,
                        "port": port,
                        "sample_count": len(samples),
                        "samples": samples,
                        "summary": stats,
                    }
                finally:
                    reader.close()

            self.register(
                "read_sensor", _read_sensor_handler,
                description="读取传感器数据",
                parameters={
                    "port": {"type": "string", "description": "传感器串口端口路径", "required": True},
                    "baudrate": {"type": "integer", "description": "波特率 (默认 115200)", "required": False},
                    "count": {"type": "integer", "description": "采集样本数 (默认 10)", "required": False},
                    "interval_sec": {"type": "number", "description": "采样间隔秒数 (默认 0.1)", "required": False},
                    "export_csv": {"type": "string", "description": "导出 CSV 文件路径 (可选)", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 read_sensor 不可用: %s", exc)

        # ── capture_camera ──
        def _capture_camera_handler(arguments: dict) -> dict:
            """捕获相机图像（骨架实现，需要 cv2 支持）。"""
            try:
                import cv2
            except ImportError:
                return {
                    "success": False,
                    "error": "OpenCV (cv2) 未安装，无法捕获相机图像。请执行: pip install opencv-python",
                }

            device_id = int(arguments.get("device_id", 0))
            width = int(arguments.get("width", 640))
            height = int(arguments.get("height", 480))
            save_path = arguments.get("save_path", "")

            try:
                cap = cv2.VideoCapture(device_id)
                if not cap.isOpened():
                    return {"success": False, "error": f"无法打开相机设备 {device_id}"}

                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

                ret, frame = cap.read()
                cap.release()

                if not ret:
                    return {"success": False, "error": "无法从相机读取图像帧"}

                result = {
                    "success": True,
                    "device_id": device_id,
                    "width": frame.shape[1],
                    "height": frame.shape[0],
                    "channels": frame.shape[2] if len(frame.shape) == 3 else 1,
                }

                if save_path:
                    cv2.imwrite(save_path, frame)
                    result["saved_to"] = save_path

                return result
            except Exception as exc:
                return {"success": False, "error": f"相机捕获异常: {exc}"}

        self.register(
            "capture_camera", _capture_camera_handler,
            description="捕获相机图像",
            parameters={
                "device_id": {"type": "integer", "description": "相机设备 ID (默认 0)", "required": False},
                "width": {"type": "integer", "description": "图像宽度 (默认 640)", "required": False},
                "height": {"type": "integer", "description": "图像高度 (默认 480)", "required": False},
                "save_path": {"type": "string", "description": "保存路径 (可选，不填则不保存)", "required": False},
            },
        )

        # ── read_file ──
        try:
            from agent.tools.file_read import read_file as _read_file_fn

            self.register(
                "read_file", _read_file_fn,
                description="读取文件内容（文本/图片/目录）",
                parameters={
                    "file_path": {"type": "string", "description": "文件绝对路径 [required]", "required": True},
                    "offset": {"type": "integer", "description": "起始行号 (1-based，默认 0)", "required": False},
                    "limit": {"type": "integer", "description": "最大读取行数 (默认 2000)", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 read_file 不可用: %s", exc)

        # ── write_file ──
        try:
            from agent.tools.file_write import write_file as _write_file_fn

            self.register(
                "write_file", _write_file_fn,
                description="写入内容到文件（创建或覆盖）",
                danger_level=DangerLevel.MEDIUM,
                parameters={
                    "file_path": {"type": "string", "description": "文件绝对路径 [required]", "required": True},
                    "content": {"type": "string", "description": "要写入的内容 [required]", "required": True},
                },
            )
        except ImportError as exc:
            logger.warning("工具 write_file 不可用: %s", exc)

        # ── edit_file ──
        try:
            from agent.tools.file_edit import edit_file as _edit_file_fn

            self.register(
                "edit_file", _edit_file_fn,
                description="精确字符串替换编辑文件（old_string → new_string）",
                danger_level=DangerLevel.MEDIUM,
                parameters={
                    "file_path": {"type": "string", "description": "文件绝对路径 [required]", "required": True},
                    "old_string": {"type": "string", "description": "要替换的原文本（必须精确匹配） [required]", "required": True},
                    "new_string": {"type": "string", "description": "替换后的新文本 [required]", "required": True},
                    "replace_all": {"type": "boolean", "description": "是否替换所有匹配 (默认 False)", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 edit_file 不可用: %s", exc)

        # ── grep ──
        try:
            from agent.tools.file_search import grep as _grep_fn

            self.register(
                "grep", _grep_fn,
                description="正则搜索文件内容（优先 ripgrep，降级 Python）",
                parameters={
                    "pattern": {"type": "string", "description": "正则表达式模式 [required]", "required": True},
                    "path": {"type": "string", "description": "搜索目录路径（默认当前目录）", "required": False},
                    "glob": {"type": "string", "description": "文件过滤模式，如 *.py", "required": False},
                    "output_mode": {"type": "string", "description": "输出模式: content / files_with_matches / count", "required": False},
                    "head_limit": {"type": "integer", "description": "最大返回结果数 (默认 50)", "required": False},
                    "offset": {"type": "integer", "description": "跳过前 N 条结果", "required": False},
                    "ignore_case": {"type": "boolean", "description": "忽略大小写 (默认 False)", "required": False},
                    "context_lines": {"type": "integer", "description": "上下文行数 (仅 content 模式)", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 grep 不可用: %s", exc)

        # ── glob ──
        try:
            from agent.tools.file_search import glob as _glob_fn

            self.register(
                "glob", _glob_fn,
                description="文件名 glob 模式匹配，如 **/*.py",
                parameters={
                    "pattern": {"type": "string", "description": "glob 模式，如 **/*.py [required]", "required": True},
                    "path": {"type": "string", "description": "搜索根目录（默认当前目录）", "required": False},
                },
            )
        except ImportError as exc:
            logger.warning("工具 glob 不可用: %s", exc)

        logger.info("工具发现完成，已注册 %d 个工具", len(self._tools))

    # ------------------------------------------------------------------
    # 记忆子系统绑定
    # ------------------------------------------------------------------

    def set_memory_context(
        self,
        memory_store,
        knowledge_base,
        session_db,
        sinan_home: Optional[Any] = None,
    ) -> None:
        """绑定记忆子系统，注册记忆工具。

        由 REPL / CLI 在初始化子系统后调用，使 LLM 可以通过工具
        主动写入核心记忆、知识库和查询会话历史。

        Args:
            memory_store:   MemoryStore 实例（L1 核心记忆）。
            knowledge_base: KnowledgeBase 实例（L3 知识库）。
            session_db:     SessionDB 实例（L2 会话数据库）。
            sinan_home:     司南数据目录，默认 ~/.sinan/。
        """
        if sinan_home is None:
            from pathlib import Path
            sinan_home = Path.home() / ".sinan"

        if self._memory_tools_registered:
            logger.debug("记忆工具已注册，跳过重复注册")
            return

        from agent.tools.memory_tools import register_memory_tools

        register_memory_tools(
            self, memory_store, knowledge_base, session_db, sinan_home
        )
        self._memory_tools_registered = True

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict]:
        """返回所有已注册工具的 schema 列表。

        schema 从注册时的元数据 (description + parameters) 自动生成,
        不再依赖硬编码字典。

        Returns:
            工具 schema 列表，可供 LLM function-calling 使用。
        """
        if self._schemas is not None:
            return self._schemas

        if not self._tools:
            self.discover()

        schemas: list[dict] = []
        for name in sorted(self._tools.keys()):
            meta = self._meta.get(name, {})
            desc = meta.get("description", name)
            params = meta.get("parameters", {})

            schema: dict[str, Any] = {"name": name, "description": desc}
            if params:
                schema["parameters"] = {
                    "type": "object",
                    "properties": {
                        k: {kk: vv for kk, vv in v.items() if kk != "required"}
                        for k, v in params.items()
                    },
                    "required": [k for k, v in params.items() if v.get("required", False)],
                }
            else:
                schema["parameters"] = {"type": "object", "properties": {}}
            schemas.append(schema)

        self._schemas = schemas
        return schemas

    def get_audit_logs(self, tool_name: str = None, date: str = None, limit: int = 100) -> list[dict]:
        """查询审计日志。

        Args:
            tool_name: 按工具名过滤 (可选)。
            date: 按日期过滤，格式 YYYYMMDD (可选)。
            limit: 最大返回条目数 (默认 100)。

        Returns:
            审计日志条目列表。
        """
        return self._audit.query(tool_name=tool_name, date=date, limit=limit)

    # ------------------------------------------------------------------
    # 调用
    # ------------------------------------------------------------------

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> dict:
        """调用一个已注册的工具并返回结果。

        自动确保工具已被发现（首次调用时触发 ``discover()``）。

        Args:
            name: 工具名称。
            arguments: 工具参数字典。

        Returns:
            工具执行结果 dict，始终包含 ``success`` 字段:
                - 成功: ``{"success": True, ...}``
                - 工具不存在: ``{"success": False, "error": "..."}``
                - 执行异常: ``{"success": False, "error": "..."}``

        Raises:
            不会抛出异常 —— 所有错误均包装在返回值中。
        """
        if not self._tools:
            self.discover()

        if arguments is None:
            arguments = {}

        handler = self._tools.get(name)
        if handler is None:
            available = ", ".join(sorted(self._tools.keys()))
            result = {
                "success": False,
                "error": f"工具 '{name}' 不存在。可用工具: {available}",
            }
            self._audit.log_tool_call(name, DangerLevel.SAFE.value, arguments, result, 0.0, False)
            return result

        danger_level = self.get_danger_level(name)
        if danger_level == DangerLevel.HIGH:
            logger.warning("调用 HIGH 危险等级工具: %s", name)

        start_time = _time.time()
        try:
            result = handler(arguments)
            # 确保返回值是 dict
            if not isinstance(result, dict):
                result = {"success": True, "result": result}
            elif "success" not in result:
                result["success"] = True
            return result
        except Exception as exc:
            logger.exception("工具调用异常 '%s': %s", name, exc)
            result = {"success": False, "error": f"工具执行异常: {exc}"}
            return result
        finally:
            duration_ms = (_time.time() - start_time) * 1000.0
            success = result.get("success", False)
            self._audit.log_tool_call(name, danger_level.value, arguments, result, duration_ms, success)
            timeout = self._timeouts.get(name)
            if timeout and duration_ms > timeout * 1000:
                logger.warning("工具 '%s' 执行超时: %.0fms (限制 %.0fs)", name, duration_ms, timeout)


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """获取全局工具注册中心单例。

    线程不安全 —— 适用于单线程 Agent 调度场景。

    Returns:
        ToolRegistry 单例。
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _registry.discover()
    return _registry


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

__all__ = [
    "ToolRegistry",
    "get_registry",
    "DangerLevel",
    "AuditLogger",
    "_extract_description",
    "_parse_params_from_docstring",
]
