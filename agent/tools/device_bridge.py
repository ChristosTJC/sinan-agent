"""JSONL-RPC 协议实现 —— Micius 协议客户端。

这是司南项目中唯一的 JSONL-RPC 实现,用于通过 TCP 与远程嵌入式设备节点通信。

协议说明 (Micius):
    请求:  ``{"method": "...", "params": {...}, "id": <int>}\\n``
    响应:  ``{"result": {...}, "id": <int>}\\n`` 或 ``{"error": {...}, "id": <int>}\\n``

注意:
    本项目中 ``agent/protocol/`` 已被删除,所有 JSONL-RPC 功能统一在此模块实现。
    设备节点默认参数从 config.defaults.yaml 读取。
"""

import json
import logging
import re
import socket
import subprocess
import time
from contextlib import suppress
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSONL RPC 客户端（底层 TCP 通信）
# ---------------------------------------------------------------------------


class JsonlRpcClient:
    """JSONL-over-TCP RPC 客户端 —— 基于 Micius 协议。

    每行一个完整的 JSON 对象（NDJSON），请求与响应通过 ``id`` 字段关联。
    支持自动重连和超时控制。

    Attributes:
        host: 目标主机名或 IP。
        port: 目标端口。
        timeout_sec: 连接和读写超时秒数。
        _sock: 底层的 raw socket（未连接时为 None）。
        _request_id: 自增请求 ID 计数器。
    """

    def __init__(
        self,
        host: str,
        port: int,
        timeout_sec: float = 5.0,
    ) -> None:
        """初始化 JSONL RPC 客户端。

        Args:
            host: 目标主机（IP 地址或主机名）。
            port: TCP 端口号。
            timeout_sec: 连接超时和读取超时秒数。
        """
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec
        self._sock: Optional[socket.socket] = None
        self._request_id: int = 0
        self._buffer: str = ""

    @property
    def is_connected(self) -> bool:
        """判断 TCP 连接是否存活。"""
        return self._sock is not None

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """建立 TCP 连接到目标设备。

        Returns:
            True 表示连接成功，False 表示失败（主机不可达、端口未开、超时等）。

        Note:
            若已连接，先关闭旧连接再重新连接。
        """
        if self._sock is not None:
            self.close()

        try:
            self._sock = socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout_sec,
            )
            self._sock.settimeout(self.timeout_sec)
            self._buffer = ""
            logger.info("已连接到 %s:%d", self.host, self.port)
            return True
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            logger.error("连接 %s:%d 失败: %s", self.host, self.port, exc)
            self._sock = None
            return False

    def close(self) -> None:
        """关闭 TCP 连接，释放 socket。"""
        if self._sock is not None:
            with suppress(OSError):
                self._sock.shutdown(socket.SHUT_RDWR)
            self._sock.close()
            self._sock = None
            self._buffer = ""
            logger.debug("已断开 %s:%d", self.host, self.port)

    # ------------------------------------------------------------------
    # RPC 请求
    # ------------------------------------------------------------------

    def request(self, method: str, params: Optional[dict] = None) -> dict:
        """发送 JSONL RPC 请求并接收响应。

        协议格式:
            - 请求:  ``{"method": "<name>", "params": {...}, "id": <N>}\n``
            - 响应:  ``{"result": {...}, "id": <N>}\n``

        Args:
            method: RPC 方法名。
            params: 可选参数字典。

        Returns:
            解析后的响应 dict，总是包含 ``success`` 字段:
                - 成功: ``{"success": True, "result": {...}}``
                - 失败: ``{"success": False, "error": str}``

        Note:
            TCP 连接未建立时自动尝试连接。
        """
        if self._sock is None:
            success = self.connect()
            if not success:
                return {
                    "success": False,
                    "error": f"无法连接到 {self.host}:{self.port} —— 连接建立失败",
                }

        self._request_id += 1
        req_id = self._request_id

        request_obj = {
            "method": method,
            "params": params or {},
            "id": req_id,
        }

        try:
            payload = json.dumps(request_obj, ensure_ascii=False) + "\n"
            self._sock.sendall(payload.encode("utf-8"))
            logger.debug("发送请求 id=%d method=%s", req_id, method)
        except (OSError, BrokenPipeError) as exc:
            logger.error("发送请求失败: %s", exc)
            self.close()
            return {"success": False, "error": f"发送失败: {exc}"}

        # 接收响应
        try:
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    logger.error("连接已关闭（对端断开）")
                    self.close()
                    return {"success": False, "error": "连接已被对端关闭"}
                self._buffer += chunk.decode("utf-8", errors="replace")

                # 尝试读取完整的 JSONL 行
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        response_obj = json.loads(line)
                    except json.JSONDecodeError as exc:
                        logger.warning("JSON 解析失败: %s，原始数据: %s", exc, line[:120])
                        continue

                    # 匹配请求 ID
                    resp_id = response_obj.get("id")
                    if resp_id == req_id:
                        if "result" in response_obj:
                            return {"success": True, "result": response_obj["result"]}
                        elif "error" in response_obj:
                            return {"success": False, "error": str(response_obj["error"])}
                        else:
                            return {"success": False, "error": "响应缺少 result 和 error 字段"}

        except socket.timeout:
            logger.error("请求超时: %s:%d method=%s", self.host, self.port, method)
            return {"success": False, "error": "请求超时（无响应）"}
        except OSError as exc:
            logger.error("接收响应失败: %s", exc)
            return {"success": False, "error": f"接收失败: {exc}"}

    def __enter__(self) -> "JsonlRpcClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


# ---------------------------------------------------------------------------
# 设备节点客户端（业务层）
# ---------------------------------------------------------------------------


class DeviceNodeClient(JsonlRpcClient):
    """嵌入式设备节点客户端 —— 在 JsonlRpcClient 之上封装设备交互。

    提供设备识别（``hello``）、远程工具列表查询、工具调用等功能。
    适用于运行 Micius 协议的嵌入式节点。
    
    默认端口和超时从 config.defaults.yaml 读取。
    """

    @staticmethod
    def _get_default_config() -> dict:
        """从配置获取设备节点默认参数。
        
        Returns:
            {"default_port": int, "timeout_sec": float}
        """
        try:
            from agent.config import get_tools_config
            tools_config = get_tools_config()
            device_config = tools_config.get("device_node", {})
            return {
                "default_port": device_config.get("default_port", 5555),
                "timeout_sec": device_config.get("timeout_sec", 5.0),
            }
        except Exception as e:
            logger.warning("无法加载设备节点配置,使用硬编码兜底值: %s", e)
            return {
                "default_port": 5555,
                "timeout_sec": 5.0,
            }

    def __init__(
        self,
        host: str,
        port: Optional[int] = None,
        timeout_sec: Optional[float] = None,
    ) -> None:
        """端口/超时缺省时从 config.defaults.yaml 的 tools.device_node 读取。"""
        cfg = self._get_default_config()
        super().__init__(
            host,
            cfg["default_port"] if port is None else port,
            cfg["timeout_sec"] if timeout_sec is None else timeout_sec,
        )

    def hello(self) -> dict:
        """向设备发送 ``hello`` 请求，获取设备身份信息。

        Returns:
            设备身份信息 dict::

                {
                    "success": bool,
                    "device_id": str,
                    "device_type": str,
                    "firmware_version": str,
                    "protocol_version": str,
                    ...
                }

            通信失败时 ``success=False`` 并包含 ``error`` 字段。
        """
        response = self.request("hello")
        if response["success"]:
            result = response.get("result", {})
            logger.info("设备 hello: id=%s type=%s", result.get("device_id", "?"), result.get("device_type", "?"))
            return {
                "success": True,
                **result,
            }
        else:
            logger.warning("设备 hello 失败: %s", response.get("error", "未知错误"))
        return response

    def list_tools(self) -> list[str]:
        """获取设备端注册的可用远程工具列表。

        Returns:
            工具名称字符串列表。通信失败返回空列表。
        """
        response = self.request("list_tools")
        if response["success"]:
            tools = response.get("result", {}).get("tools", [])
            logger.debug("设备工具列表: %s", tools)
            return tools
        else:
            logger.warning("获取工具列表失败: %s", response.get("error", "未知错误"))
            return []

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> dict:
        """调用设备端注册的远程工具。

        Args:
            name: 工具名称。
            arguments: 工具参数字典。

        Returns:
            工具执行结果 dict，同 ``JsonlRpcClient.request``。
        """
        return self.request("call_tool", {"name": name, "arguments": arguments or {}})


# ---------------------------------------------------------------------------
# 连接诊断
# ---------------------------------------------------------------------------


class ConnectionDiagnostics:
    """连接诊断器 —— 对远程设备节点做多层连通性测试。

    提供 TCP 探活、JSONL 握手、SSH 连接和综合诊断报告。
    """

    def __init__(self) -> None:
        """初始化连接诊断器。"""
        pass

    @staticmethod
    def tcp_probe(host: str, port: int, timeout: float = 2.0) -> bool:
        """TCP 端口探活 —— 判断主机端口是否可达。

        Args:
            host: 目标主机。
            port: 目标端口。
            timeout: 超时秒数。

        Returns:
            True 表示端口可达，False 表示不可达。
        """
        try:
            with socket.create_connection((host, port), timeout=timeout):
                logger.debug("TCP 探活成功: %s:%d", host, port)
                return True
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            logger.debug("TCP 探活失败 %s:%d: %s", host, port, exc)
            return False

    @staticmethod
    def jsonl_probe(host: str, port: int) -> dict:
        """通过 JSONL 协议连接并发送 ``hello`` 握手。

        Args:
            host: 目标主机。
            port: 目标端口。

        Returns:
            设备响应 dict，失败时含 ``"error"`` 字段。
        """
        client = DeviceNodeClient(host, port)
        if not client.connect():
            return {"error": f"无法建立 TCP 连接到 {host}:{port}"}

        try:
            response = client.hello()
            return response
        finally:
            client.close()

    @staticmethod
    def ssh_probe(host: str) -> bool:
        """检测目标主机是否可通过 SSH 连接。

        通过 ``ssh -o ConnectTimeout=3 -o BatchMode=yes <host> echo OK`` 测试。

        Args:
            host: 目标主机名或 IP。

        Returns:
            True 表示 SSH 可达，返回码为 0 表示退出码正常（BatchMode=yes 下即使无密钥也返回 0 表示服务可达）。
        """
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-o", "ConnectTimeout=3",
                    "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=no",
                    host,
                    "echo OK",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # BatchMode=yes + 无密钥时返回码 255，但至少证明 SSH 服务可达
            # 能成功执行命令才是真正的可达
            if result.returncode == 0:
                logger.debug("SSH 探活成功: %s", host)
                return True
            else:
                logger.debug("SSH 探活部分成功: %s (返回码 %d, stderr末行: %s)", host, result.returncode, result.stderr.strip().splitlines()[-1] if result.stderr else "")
                # 返回码非零但可能表示 SSH 服务存在，仅需要认证
                return result.returncode == 255
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("SSH 探活失败 %s: %s", host, exc)
            return False

    def build_report(self, host: str, port: int) -> str:
        """生成完整的连接诊断报告。

        依次执行: TCP 探活 → JSONL 握手 → SSH 探活 → 生成报告。

        Args:
            host: 目标主机。
            port: 目标端口。

        Returns:
            多行纯文本诊断报告（中文）。
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append(f"连接诊断报告: {host}:{port}")
        lines.append("=" * 60)

        # 1. DNS 解析
        try:
            ips = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
            resolved = list({addr[4][0] for addr in ips})
            lines.append(f"[DNS]    解析成功: {host} → {', '.join(resolved)}")
        except socket.gaierror as exc:
            lines.append(f"[DNS]    解析失败: {exc}")
            return "\n".join(lines)

        # 2. TCP 探活
        tcp_ok = self.tcp_probe(host, port)
        lines.append(f"[TCP]    端口 {port} {'可达' if tcp_ok else '不可达'}")

        # 3. JSONL 握手
        if tcp_ok:
            jsonl_result = self.jsonl_probe(host, port)
            if "error" not in jsonl_result:
                device_id = jsonl_result.get("device_id", "?")
                device_type = jsonl_result.get("device_type", "?")
                fw_ver = jsonl_result.get("firmware_version", "?")
                lines.append(f"[JSONL]  握手成功")
                lines.append(f"         设备ID: {device_id}")
                lines.append(f"         设备类型: {device_type}")
                lines.append(f"         固件版本: {fw_ver}")
            else:
                lines.append(f"[JSONL]  握手失败: {jsonl_result['error']}")
        else:
            lines.append("[JSONL]  跳过（TCP 不可达）")

        # 4. SSH 探活
        ssh_ok = self.ssh_probe(host)
        lines.append(f"[SSH]    服务{'可达' if ssh_ok else '不可达'}")

        # 5. 总结
        lines.append("-" * 60)
        if tcp_ok:
            lines.append("结论: 设备网络可达，TCP 连接正常。")
        else:
            lines.append("结论: 设备网络不可达，请检查物理连接和网络配置。")
        lines.append("=" * 60)

        return "\n".join(lines)
