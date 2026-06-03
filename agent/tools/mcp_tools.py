"""MCP 工具适配器 — 将 MCP server 的工具暴露给 LLM。

注册以下工具：
- mcp_server_connect: 连接 MCP server (stdio)
- mcp_server_disconnect: 断开连接
- mcp_tools_list: 列出 server 的工具
- mcp_tool_call: 调用工具 (或通过自动注册的 mcp__server__tool)
- mcp_resources_list: 列出资源
- mcp_resource_read: 读取资源
"""
from __future__ import annotations

import re
from typing import Any

from agent.tools.mcp_client import get_mcp_manager


def _sanitize_segment(value: str) -> str:
    import re
    sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    if not sanitized:
        return "tool"
    if not sanitized[0].isalpha():
        sanitized = "mcp_" + sanitized
    return sanitized


def _normalize_mcp_schema(input_schema: dict) -> dict:
    """将 MCP JSON Schema 转换为 ToolRegistry 参数格式。"""
    if not input_schema:
        return {}
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])
    result = {}
    for key, prop in properties.items():
        entry = dict(prop)
        entry["required"] = key in required
        result[key] = entry
    return result


def _register_server_tools(registry: Any, server_name: str) -> int:
    from agent.tools import DangerLevel
    """将 MCP server 的工具自动注册为 mcp__server__tool。"""
    mgr = get_mcp_manager()
    result = mgr.list_tools(server_name)
    if not result.get("success"):
        return 0

    tools = result.get("tools", [])
    count = 0
    for tool_info in tools:
        tool_name = tool_info.get("name", "")
        safe_server = _sanitize_segment(server_name)
        safe_tool = _sanitize_segment(tool_name)
        full_name = f"mcp__{safe_server}__{safe_tool}"

        if full_name in [t["name"] for t in registry.list_tools()]:
            continue

        registry.register(
            full_name,
            _make_mcp_tool_handler(server_name, tool_name),
            description=f"[MCP] {tool_info.get('description', tool_name)}",
            danger_level=DangerLevel.MEDIUM,
            timeout_sec=30,
            parameters=_normalize_mcp_schema(
                tool_info.get("inputSchema", {})),
        )
        count += 1
    return count


def _make_mcp_tool_handler(server_name: str, tool_name: str):
    """创建闭包处理器。"""

    def handler(arguments: dict) -> dict:
        mgr = get_mcp_manager()
        if not mgr.is_connected(server_name):
            return {"success": False,
                    "error": f"MCP server '{server_name}' 未连接"}
        return mgr.call_tool(server_name, tool_name, arguments)

    return handler


# ── mcp_server_connect ──────────────────────────────────────

def mcp_server_connect(arguments: dict) -> dict:
    """连接 MCP server (stdio 子进程)。

    Args:
        server_name (str): 服务器名称 [required]
        command (list[str]): 启动命令 [required]
        env (dict): 环境变量 (可选, 会被脱敏)

    Returns:
        连接结果, 含 capabilities。
    """
    server_name = arguments.get("server_name", "")
    command = arguments.get("command", [])
    env = arguments.get("env", {})

    if not server_name or not command:
        return {"success": False,
                "error": "缺少参数: server_name 和 command"}

    mgr = get_mcp_manager()
    result = mgr.connect(server_name, command, env)

    if result.get("success"):
        try:
            from agent.tools import get_registry
            registry = get_registry()
            count = _register_server_tools(registry, server_name)
            result["tools_registered"] = count
        except Exception:
            result["tools_registered"] = 0

    return result


# ── mcp_server_disconnect ───────────────────────────────────

def mcp_server_disconnect(arguments: dict) -> dict:
    """断开 MCP server 连接。"""
    server_name = arguments.get("server_name", "")
    if not server_name:
        return {"success": False, "error": "缺少参数: server_name"}
    mgr = get_mcp_manager()
    return mgr.disconnect(server_name)


# ── mcp_tools_list ──────────────────────────────────────────

def mcp_tools_list(arguments: dict) -> dict:
    """列出 MCP server 的工具。"""
    server_name = arguments.get("server_name", "")
    if not server_name:
        return {"success": False, "error": "缺少参数: server_name"}
    mgr = get_mcp_manager()
    return mgr.list_tools(server_name)


# ── mcp_tool_call ───────────────────────────────────────────

def mcp_tool_call(arguments: dict) -> dict:
    """调用 MCP server 的工具。"""
    server_name = arguments.get("server_name", "")
    tool_name = arguments.get("tool_name", "")
    tool_args = arguments.get("arguments", {})

    if not server_name or not tool_name:
        return {"success": False,
                "error": "缺少参数: server_name 和 tool_name"}

    mgr = get_mcp_manager()
    return mgr.call_tool(server_name, tool_name, tool_args)


# ── mcp_resources_list ──────────────────────────────────────

def mcp_resources_list(arguments: dict) -> dict:
    """列出 MCP server 的资源。"""
    server_name = arguments.get("server_name", "")
    if not server_name:
        return {"success": False, "error": "缺少参数: server_name"}
    mgr = get_mcp_manager()
    return mgr.list_resources(server_name)


# ── mcp_resource_read ───────────────────────────────────────

def mcp_resource_read(arguments: dict) -> dict:
    """读取 MCP server 的资源。"""
    server_name = arguments.get("server_name", "")
    uri = arguments.get("uri", "")

    if not server_name or not uri:
        return {"success": False,
                "error": "缺少参数: server_name 和 uri"}

    mgr = get_mcp_manager()
    return mgr.read_resource(server_name, uri)
