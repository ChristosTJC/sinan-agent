"""
司南工具桥接层 —— 将 ToolRegistry 工具转换为 LLM function calling 格式。

负责:
1. 将 ToolRegistry 的 schema 转换为 OpenAI function calling 格式
2. 解析 LLM 返回的 tool_call 并调用 ToolRegistry
3. 将工具结果格式化回传给 LLM
4. 危险工具审批门控
5. 并行工具执行
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

from agent.llm.client import ToolCall
from agent.tools import DangerLevel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema 转换
# ---------------------------------------------------------------------------


def tools_to_openai_format(tools: list[dict]) -> list[dict]:
    """将 ToolRegistry 工具 schema 转换为 OpenAI function calling 格式。

    ToolRegistry schema:
        {"name": "...", "description": "...", "parameters": {"type": "object", "properties": {...}}}

    OpenAI function calling:
        {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
    """
    openai_tools: list[dict] = []
    for tool in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return openai_tools


# ---------------------------------------------------------------------------
# 工具调用执行
# ---------------------------------------------------------------------------


def execute_tool_call(
    tool_call: ToolCall,
    registry: Any,  # ToolRegistry
) -> dict[str, Any]:
    """执行单个工具调用并返回结果。

    Args:
        tool_call: LLM 返回的工具调用请求。
        registry: ToolRegistry 实例。

    Returns:
        包含调用结果的字典，始终有 ``success`` 字段。
    """
    name = tool_call.name
    args = tool_call.arguments

    logger.info("执行工具调用: %s(%s)", name, json.dumps(args, ensure_ascii=False)[:200])

    result = registry.call_tool(name, args)

    logger.info(
        "工具调用完成: %s -> success=%s",
        name,
        result.get("success", "unknown"),
    )

    return result


def _execute_tool_call_with_approval(
    tool_call: ToolCall,
    registry: Any,
    approval: Optional[Callable[[str, dict, DangerLevel], bool]] = None,
) -> tuple[dict[str, Any], bool]:
    """执行危险工具调用，把外层审批（含 danger_level）接入 registry 门控。

    Returns:
        (result, rejected)。rejected=True 表示审批被拒、未真正执行。
    """
    prev_callback = getattr(registry, "_confirm_callback", None)
    prev_danger_confirm = getattr(registry, "_danger_confirm", True)
    rejected = {"value": False}

    def _confirm(tool_name: str, level: str, arguments: dict) -> bool:
        if approval is None:
            rejected["value"] = True
            return False
        try:
            ok = approval(tool_name, arguments, DangerLevel(level))
        except ValueError:
            ok = approval(tool_name, arguments, DangerLevel.HIGH)
        if not ok:
            rejected["value"] = True
        return ok

    try:
        if hasattr(registry, "set_confirm_callback"):
            registry.set_confirm_callback(_confirm)
        if hasattr(registry, "set_danger_confirm"):
            registry.set_danger_confirm(True)
        result = execute_tool_call(tool_call, registry)
        return result, rejected["value"]
    finally:
        if hasattr(registry, "set_confirm_callback"):
            registry.set_confirm_callback(prev_callback)
        if hasattr(registry, "set_danger_confirm"):
            registry.set_danger_confirm(prev_danger_confirm)


def format_tool_result(result: dict[str, Any], tool_name: str = "") -> str:
    """将工具调用结果格式化为字符串供 LLM 阅读。

    按工具类型定制格式化策略，避免一刀切截断。

    Args:
        result: 工具调用返回的字典。
        tool_name: 工具名称，用于定制格式化。

    Returns:
        JSON 格式的字符串。
    """
    # 串口数据：保留完整行结构
    if tool_name in ("serial_monitor", "read_sensor"):
        return _format_serial_result(result)

    # 设备列表：结构化展示
    if tool_name in ("scan_usb", "scan_serial"):
        return _format_device_list(result)

    # 默认：智能截断
    return _format_default(result)


def _format_serial_result(result: dict[str, Any]) -> str:
    """格式化串口数据结果，保留完整行结构。"""
    formatted = {}
    for k, v in result.items():
        if k == "data" and isinstance(v, str):
            # 串口数据保留完整，仅限制总行数
            lines = v.splitlines()
            if len(lines) > 200:
                formatted[k] = "\n".join(lines[:200])
                formatted["_truncated"] = f"共 {len(lines)} 行，仅显示前 200 行"
            else:
                formatted[k] = v
        elif k == "lines" and isinstance(v, list):
            if len(v) > 200:
                formatted[k] = v[:200]
                formatted[f"{k}_truncated"] = f"共 {len(v)} 条，仅显示前 200 条"
            else:
                formatted[k] = v
        elif isinstance(v, str) and len(v) > 4000:
            formatted[k] = v[:4000] + "... (已截断)"
        else:
            formatted[k] = v
    return json.dumps(formatted, ensure_ascii=False, indent=2)


def _format_device_list(result: dict[str, Any]) -> str:
    """格式化设备列表，结构化展示不截断。"""
    formatted = {}
    for k, v in result.items():
        if isinstance(v, list):
            # 设备列表完整展示
            formatted[k] = v
            formatted[f"{k}_count"] = len(v)
        elif isinstance(v, str) and len(v) > 4000:
            formatted[k] = v[:4000] + "... (已截断)"
        else:
            formatted[k] = v
    return json.dumps(formatted, ensure_ascii=False, indent=2)


def _format_default(result: dict[str, Any]) -> str:
    """默认格式化，智能截断。"""
    truncated = {}
    for k, v in result.items():
        if isinstance(v, str) and len(v) > 2000:
            truncated[k] = v[:2000] + "... (已截断)"
        elif isinstance(v, list) and len(v) > 50:
            truncated[k] = v[:50]
            truncated[f"{k}_truncated"] = f"共 {len(v)} 条，仅显示前 50 条"
        else:
            truncated[k] = v
    return json.dumps(truncated, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 消息构造辅助
# ---------------------------------------------------------------------------


def build_tool_call_message(
    assistant_content: str,
    tool_calls: list[ToolCall],
) -> dict:
    """构造带 tool_calls 的 assistant 消息。

    Returns:
        OpenAI 格式的 assistant 消息。
    """
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": assistant_content or None,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in tool_calls
        ],
    }
    return msg


def build_tool_result_message(
    tool_call_id: str,
    result: str,
) -> dict:
    """构造 tool result 消息。

    Args:
        tool_call_id: 工具调用 ID。
        result: 工具调用结果字符串。

    Returns:
        OpenAI 格式的 tool 消息。
    """
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": result,
    }


# ---------------------------------------------------------------------------
# 批量执行
# ---------------------------------------------------------------------------


def _danger_level_str(registry: Any, name: str) -> str:
    if hasattr(registry, "get_danger_level"):
        level = registry.get_danger_level(name)
        return level.value if isinstance(level, DangerLevel) else str(level)
    return DangerLevel.HIGH.value if registry.is_dangerous(name) else DangerLevel.SAFE.value


def execute_all_tool_calls(
    tool_calls: list[ToolCall],
    registry: Any,
    status_callback: Optional[Any] = None,
    approval: Optional[Callable[[str, dict, DangerLevel], bool]] = None,
) -> tuple[list[dict], list[dict]]:
    """批量执行工具调用，返回 (tool result 消息列表, 结构化 execution records)。

    危险工具逐个审批 + 串行；安全工具并行。records 供上层（AgentSession）发事件。
    """
    if not tool_calls:
        return [], []

    dangerous_calls: list[ToolCall] = []
    safe_calls: list[ToolCall] = []
    for tc in tool_calls:
        (dangerous_calls if registry.is_dangerous(tc.name) else safe_calls).append(tc)

    messages: list[dict] = []
    records: dict[str, dict] = {}

    # 危险工具：逐个审批 + 串行
    for tc in dangerous_calls:
        if status_callback:
            status_callback(tc.name, "calling")
        start = time.monotonic()
        result, rejected = _execute_tool_call_with_approval(tc, registry, approval)
        duration_ms = (time.monotonic() - start) * 1000
        result_str = format_tool_result(result, tc.name)
        if status_callback:
            status_callback(tc.name, "rejected" if rejected else "done")
        messages.append(build_tool_result_message(tc.id, result_str))
        records[tc.id] = {
            "name": tc.name,
            "success": bool(result.get("success")),
            "duration_ms": duration_ms,
            "danger_level": _danger_level_str(registry, tc.name),
            "rejected": rejected,
            "error": "" if result.get("success") else str(result.get("error", "")),
        }

    # 安全工具：并行
    if safe_calls:
        for tc in safe_calls:
            if status_callback:
                status_callback(tc.name, "calling")
        timings: dict[str, float] = {}
        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=min(len(safe_calls), 4)) as executor:
            future_to_tc = {}
            for tc in safe_calls:
                timings[tc.id] = time.monotonic()
                future_to_tc[executor.submit(execute_tool_call, tc, registry)] = tc
            for future in as_completed(future_to_tc):
                tc = future_to_tc[future]
                try:
                    results[tc.id] = future.result()
                except Exception as exc:  # noqa: BLE001 - 工具执行边界，错误回灌 LLM
                    results[tc.id] = {"success": False, "error": f"执行异常: {exc}"}
        for tc in safe_calls:
            result = results[tc.id]
            duration_ms = (time.monotonic() - timings[tc.id]) * 1000
            result_str = format_tool_result(result, tc.name)
            if status_callback:
                status_callback(tc.name, "done")
            messages.append(build_tool_result_message(tc.id, result_str))
            records[tc.id] = {
                "name": tc.name,
                "success": bool(result.get("success")),
                "duration_ms": duration_ms,
                "danger_level": _danger_level_str(registry, tc.name),
                "rejected": False,
                "error": "" if result.get("success") else str(result.get("error", "")),
            }

    ordered = [tc.id for tc in tool_calls]
    return messages, [records[i] for i in ordered if i in records]
