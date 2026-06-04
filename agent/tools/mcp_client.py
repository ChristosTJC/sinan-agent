"""MCP stdio JSON-RPC 客户端管理器。

管理 MCP 服务器子进程，通过 stdin/stdout JSON-RPC 通信。
支持: initialize → tools/list / tools/call / resources/list / resources/read。
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0


@dataclass
class McpConnection:
    server_name: str
    command: list[str]
    env: dict[str, str]
    process: Optional[subprocess.Popen] = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    connected: bool = False
    error: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)


class McpClientManager:
    def __init__(self):
        self._connections: dict[str, McpConnection] = {}
        self._request_counter: int = 0

    # ── 连接管理 ────────────────────────────────────────────

    def connect(self, server_name: str, command: list[str],
                env: Optional[dict[str, str]] = None) -> dict[str, Any]:
        """启动 MCP server 子进程并完成 initialize 握手。"""
        if server_name in self._connections and self._connections[server_name].connected:
            return {"success": False, "error": f"服务器 '{server_name}' 已连接"}

        conn = McpConnection(
            server_name=server_name,
            command=command,
            env=env or {},
        )
        self._connections[server_name] = conn

        try:
            import os
            full_env = {**os.environ, **conn.env}
            conn.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=full_env,
                cwd=str(Path.cwd()),
            )
        except FileNotFoundError:
            conn.error = f"命令未找到: {command[0]}"
            self._connections.pop(server_name, None)
            return {"success": False, "error": conn.error}
        except Exception as exc:
            conn.error = str(exc)
            self._connections.pop(server_name, None)
            return {"success": False, "error": f"启动失败: {exc}"}

        # Initialize 握手
        try:
            init_result = self._send_request(server_name, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "clientInfo": {"name": "sinan-embedded-agent", "version": "0.1"},
            })
            conn.capabilities = init_result.get("capabilities", {})
            self._send_notification(server_name, "notifications/initialized", {})
            conn.connected = True
            return {"success": True, "server_name": server_name,
                    "capabilities": conn.capabilities}
        except Exception as exc:
            conn.error = str(exc)
            self._cleanup_process(server_name)
            return {"success": False, "error": f"Initialize 失败: {exc}"}

    def disconnect(self, server_name: str) -> dict[str, Any]:
        """断开 MCP server。"""
        if server_name not in self._connections:
            return {"success": False, "error": f"服务器 '{server_name}' 未连接"}
        self._cleanup_process(server_name)
        return {"success": True}

    def is_connected(self, server_name: str) -> bool:
        conn = self._connections.get(server_name)
        if not conn:
            return False
        if conn.process and conn.process.poll() is not None:
            conn.connected = False
        return conn.connected

    def list_servers(self) -> list[str]:
        return list(self._connections.keys())

    # ── 工具操作 ────────────────────────────────────────────

    def list_tools(self, server_name: str) -> dict[str, Any]:
        conn = self._ensure_connected(server_name)
        if not conn:
            return {"success": False, "error": f"服务器 '{server_name}' 未连接"}
        try:
            result = self._send_request(server_name, "tools/list", {})
            return {"success": True, "tools": result.get("tools", [])}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def call_tool(self, server_name: str, tool_name: str,
                  arguments: dict[str, Any]) -> dict[str, Any]:
        conn = self._ensure_connected(server_name)
        if not conn:
            return {"success": False, "error": f"服务器 '{server_name}' 未连接"}
        try:
            result = self._send_request(server_name, "tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })
            content = result.get("content", [])
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return {"success": True, "tool_name": tool_name,
                    "server_name": server_name, "content": content,
                    "text": "\n".join(text_parts)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── 资源操作 ────────────────────────────────────────────

    def list_resources(self, server_name: str) -> dict[str, Any]:
        conn = self._ensure_connected(server_name)
        if not conn:
            return {"success": False, "error": f"服务器 '{server_name}' 未连接"}
        try:
            result = self._send_request(server_name, "resources/list", {})
            return {"success": True, "resources": result.get("resources", [])}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def read_resource(self, server_name: str, uri: str) -> dict[str, Any]:
        conn = self._ensure_connected(server_name)
        if not conn:
            return {"success": False, "error": f"服务器 '{server_name}' 未连接"}
        try:
            result = self._send_request(server_name, "resources/read", {"uri": uri})
            contents = result.get("contents", [])
            text_parts = [c.get("text", "") for c in contents if c.get("type") != "resource"]
            return {"success": True, "uri": uri, "contents": contents,
                    "text": "\n".join(text_parts)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── 内部 ────────────────────────────────────────────────

    def _ensure_connected(self, server_name: str) -> Optional[McpConnection]:
        conn = self._connections.get(server_name)
        if not conn or not conn.connected:
            return None
        if conn.process and conn.process.poll() is not None:
            conn.connected = False
            conn.error = f"进程已退出 (code={conn.process.returncode})"
            return None
        return conn

    def _send_request(self, server_name: str, method: str,
                      params: dict[str, Any]) -> dict[str, Any]:
        conn = self._connections[server_name]
        with conn._lock:
            self._request_counter += 1
            req_id = self._request_counter
            req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            line = json.dumps(req, ensure_ascii=False) + "\n"
            try:
                conn.process.stdin.write(line)
                conn.process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                conn.connected = False
                conn.error = f"写入失败: {exc}"
                raise ConnectionError(f"MCP server '{server_name}' 连接已断开") from exc

            return self._read_response(conn, req_id)

    def _send_notification(self, server_name: str, method: str,
                           params: dict[str, Any]) -> None:
        conn = self._connections[server_name]
        with conn._lock:
            notif = {"jsonrpc": "2.0", "method": method, "params": params}
            try:
                conn.process.stdin.write(json.dumps(notif, ensure_ascii=False) + "\n")
                conn.process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def _read_response(self, conn: McpConnection,
                       expected_id: int) -> dict[str, Any]:
        deadline = time.time() + _TIMEOUT
        while time.time() < deadline:
            if conn.process.poll() is not None:
                conn.connected = False
                raise ConnectionError(
                    f"MCP server '{conn.server_name}' 进程已退出 "
                    f"(code={conn.process.returncode})")

            line = conn.process.stdout.readline()
            if not line:
                continue
            try:
                msg = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if msg.get("method"):  # 通知
                continue
            if msg.get("id") == expected_id:
                if "error" in msg:
                    err = msg["error"]
                    raise RuntimeError(f"MCP error [{err.get('code')}]: {err.get('message')}")
                return msg.get("result", {})
        raise TimeoutError(f"MCP request timeout ({_TIMEOUT}s): {conn.server_name}")

    def _cleanup_process(self, server_name: str) -> None:
        conn = self._connections.pop(server_name, None)
        if not conn:
            return
        conn.connected = False
        if conn.process:
            with suppress(Exception):
                conn.process.stdin.close()
            try:
                conn.process.terminate()
                conn.process.wait(timeout=3)
            except Exception:
                with suppress(Exception):
                    conn.process.kill()

    def shutdown_all(self) -> None:
        for name in list(self._connections.keys()):
            self._cleanup_process(name)


_mcp_manager: Optional[McpClientManager] = None


def get_mcp_manager() -> McpClientManager:
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = McpClientManager()
    return _mcp_manager
