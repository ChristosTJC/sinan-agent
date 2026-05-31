"""
文件编辑工具 — 参考 Claude Code FileEditTool。

精确字符串替换（old_string → new_string），支持 replace_all。
特性：
- 绝对路径强制
- old_string 精确匹配（一处匹配或 replace_all 明确时替换全部）
- 多处匹配且非 replace_all → 拒绝
- 文件必须已存在
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, Any]:
    """精确字符串替换编辑文件。

    Args:
        file_path (str): 文件绝对路径 [required]
        old_string (str): 要替换的原文本（必须精确匹配文件中的内容） [required]
        new_string (str): 替换后的新文本 [required]
        replace_all (bool): 是否替换所有匹配出现（默认 False，仅替换第一处）

    Returns:
        dict，包含 success/replacements/error。
    """
    path = Path(os.path.expanduser(file_path))
    if not path.is_absolute():
        return {"success": False, "error": "必须提供绝对路径", "file_path": file_path}

    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        return {"success": False, "error": f"路径解析失败: {exc}", "file_path": file_path}

    if not resolved.is_file():
        return {"success": False, "error": f"文件不存在: {str(resolved)}", "file_path": str(resolved)}

    if old_string == new_string:
        return {"success": False, "error": "old_string 和 new_string 相同，无需编辑", "file_path": str(resolved)}

    # 读取原文件
    try:
        original = resolved.read_text(encoding="utf-8")
    except IOError as exc:
        return {"success": False, "error": f"读取文件失败: {exc}", "file_path": str(resolved)}

    if old_string not in original:
        return {
            "success": False,
            "error": "old_string 在文件中未找到匹配",
            "file_path": str(resolved),
            "hint": "请使用 Read 工具重新读取文件确认内容",
        }

    count = original.count(old_string)
    if count > 1 and not replace_all:
        return {
            "success": False,
            "error": f"old_string 在文件中出现了 {count} 次，请设置 replace_all=true 或提供更多上下文使其唯一",
            "file_path": str(resolved),
            "match_count": count,
        }

    # 执行替换
    if replace_all:
        edited = original.replace(old_string, new_string)
        replacements = count
    else:
        edited = original.replace(old_string, new_string, 1)
        replacements = 1

    # 写入
    try:
        resolved.write_text(edited, encoding="utf-8")
    except IOError as exc:
        return {"success": False, "error": f"写入失败: {exc}", "file_path": str(resolved)}

    return {
        "success": True,
        "file_path": str(resolved),
        "replacements": replacements,
        "bytes_before": len(original.encode("utf-8")),
        "bytes_after": len(edited.encode("utf-8")),
    }
