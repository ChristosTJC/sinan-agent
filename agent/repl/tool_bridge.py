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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

from agent.llm.client import ToolCall

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


def execute_all_tool_calls(
    tool_calls: list[ToolCall],
    registry: Any,
    status_callback: Optional[Any] = None,
    approval_callback: Optional[Callable[[str, dict], bool]] = None,
) -> list[dict]:
    """批量执行工具调用并返回 tool result 消息列表。

    支持并行执行和危险工具审批。

    Args:
        tool_calls: LLM 返回的工具调用列表。
        registry: ToolRegistry 实例。
        status_callback: 可选的状态回调 ``callback(tool_name, status)``。
        approval_callback: 可选的审批回调 ``callback(tool_name, args) -> bool``。
            返回 True 表示批准，False 表示拒绝。
            为 None 时自动批准所有工具。

    Returns:
        tool result 消息列表。
    """
    if not tool_calls:
        return []

    # 分离危险工具和安全工具
    dangerous_calls: list[ToolCall] = []
    safe_calls: list[ToolCall] = []

    for tc in tool_calls:
        if registry.is_dangerous(tc.name):
            dangerous_calls.append(tc)
        else:
            safe_calls.append(tc)

    messages: list[dict] = []

    # 危险工具：逐个审批 + 串行执行
    for tc in dangerous_calls:
        approved = True
        if approval_callback:
            approved = approval_callback(tc.name, tc.arguments)

        if not approved:
            if status_callback:
                status_callback(tc.name, "rejected")
            result_str = json.dumps({
                "success": False,
                "error": f"用户拒绝了危险工具 {tc.name} 的执行",
            }, ensure_ascii=False, indent=2)
            messages.append(build_tool_result_message(tc.id, result_str))
            continue

        # 批准后执行
        if status_callback:
            status_callback(tc.name, "calling")
        result = execute_tool_call(tc, registry)
        result_str = format_tool_result(result, tc.name)
        if status_callback:
            status_callback(tc.name, "done")
        messages.append(build_tool_result_message(tc.id, result_str))

    # 安全工具：并行执行
    if safe_calls:
        if len(safe_calls) == 1:
            # 单个工具直接执行
            tc = safe_calls[0]
            if status_callback:
                status_callback(tc.name, "calling")
            result = execute_tool_call(tc, registry)
            result_str = format_tool_result(result, tc.name)
            if status_callback:
                status_callback(tc.name, "done")
            messages.append(build_tool_result_message(tc.id, result_str))
        else:
            # 多个工具并行执行
            # 先触发所有工具的 "calling" 状态显示
            for tc in safe_calls:
                if status_callback:
                    status_callback(tc.name, "calling")

            results: dict[str, tuple[ToolCall, dict]] = {}
            with ThreadPoolExecutor(max_workers=min(len(safe_calls), 4)) as executor:
                future_to_tc = {
                    executor.submit(execute_tool_call, tc, registry): tc
                    for tc in safe_calls
                }
                for future in as_completed(future_to_tc):
                    tc = future_to_tc[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"success": False, "error": f"执行异常: {exc}"}
                    results[tc.id] = (tc, result)

            # 按原始顺序生成结果消息
            for tc in safe_calls:
                if tc.id in results:
                    _, result = results[tc.id]
                    result_str = format_tool_result(result, tc.name)
                    if status_callback:
                        status_callback(tc.name, "done")
                    messages.append(build_tool_result_message(tc.id, result_str))

    return messages
