"""
文件写入工具 — 参考 Claude Code FileWriteTool。

特性：
- 绝对路径强制
- 自动创建父目录
- 内容字符串写入
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.tools.path_rules import validate_path


def write_file(
    file_path: str = "",
    content: str = "",
) -> dict[str, Any]:
    """写入内容到文件（创建或覆盖）。

    Args:
        file_path (str): 文件绝对路径 [required]
        content (str): 要写入的内容 [required]

    Returns:
        dict，包含 success/file_path/bytes_written。
    """
    # ToolRegistry.call_tool() 传入完整 arguments dict
    if isinstance(file_path, dict):
        args = file_path
        file_path = args.get("file_path", "")
        content = args.get("content", "")

    allowed, reason = validate_path(file_path, mode="write")
    if not allowed:
        return {"success": False, "error": reason, "file_path": file_path}

    path = Path(os.path.expanduser(file_path))
    if not path.is_absolute():
        return {"success": False, "error": "必须提供绝对路径", "file_path": file_path}

    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        return {"success": False, "error": f"路径解析失败: {exc}", "file_path": file_path}

    # 创建父目录
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as exc:
        return {"success": False, "error": f"无法创建父目录: {exc}", "file_path": str(resolved)}

    existed = resolved.exists()

    # 写入
    try:
        resolved.write_text(content, encoding="utf-8")
    except IOError as exc:
        return {"success": False, "error": f"写入失败: {exc}", "file_path": str(resolved)}

    return {
        "success": True,
        "type": "update" if existed else "create",
        "file_path": str(resolved),
        "bytes_written": len(content.encode("utf-8")),
    }
