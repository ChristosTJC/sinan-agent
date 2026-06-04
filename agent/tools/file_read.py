"""
文件读取工具 — 参考 Claude Code FileReadTool。

支持文本、图片（通过文件扩展名检测）、目录列表。
特性：
- 绝对路径强制（防相对路径安全问题）
- 偏移量/行数限制（offset + limit）
- 二进制文件检测与拒绝
- 图片检测（返回为可渲染格式）
- 目录列表
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.tools.path_rules import validate_path

# 可读的文本文件扩展名（二进制文件会被拒绝）
_TEXT_EXTENSIONS = {
    ".py", ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".js", ".ts",
    ".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss", ".less", ".html", ".xml",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".md", ".rst", ".txt", ".tex", ".bib", ".csv", ".log",
    ".cmake", ".mk", ".make", ".sh", ".bash", ".zsh", ".fish",
    ".dockerfile", ".gitignore", ".editorconfig", ".env",
    ".pyx", ".pxd", ".proto", ".sql", ".graphql",
    ".svg", ".mermaid", ".mmd",
}

# 图片扩展名（可返回为可渲染格式）
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff"}

# 二进制扩展名（显式拒绝）
_BINARY_EXTENSIONS = {
    ".o", ".a", ".so", ".dll", ".dylib", ".exe", ".bin", ".elf",
    ".zip", ".tar", ".gz", ".xz", ".bz2", ".7z", ".rar",
    ".class", ".pyc", ".pyo", ".wasm",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv",
    ".ttf", ".otf", ".woff", ".woff2",
}

# 图片最大读取大小 (10MB)
_MAX_IMAGE_SIZE = 10 * 1024 * 1024


def read_file(
    file_path: str,
    offset: int = 0,
    limit: int = 2000,
) -> dict[str, Any]:
    if isinstance(file_path, dict):
        args = file_path
        file_path = args.get("file_path", "")
        offset = args.get("offset", offset)
        limit = args.get("limit", limit)

    path = _resolve_path(file_path)
    if not path:
        fname = file_path if isinstance(file_path, str) else str(file_path)
        return {"type": "error", "error": f"路径不存在: {fname}", "success": False}

    # 目录
    if path.is_dir():
        return _read_directory(path)

    # 图片
    suffix = path.suffix.lower()
    if suffix in _IMAGE_EXTENSIONS:
        return _read_image(path)

    # 显式二进制
    if suffix in _BINARY_EXTENSIONS:
        return {"type": "error", "error": f"二进制文件不支持文本读取: {file_path}", "success": False}

    # 未知扩展名 — 检测是否为文本
    if suffix not in _TEXT_EXTENSIONS:
        try:
            with open(path, "rb") as f:
                chunk = f.read(1024)
            if b"\x00" in chunk:
                return {"type": "error", "error": f"检测到二进制内容，拒绝读取: {file_path}", "success": False}
        except IOError:
            pass

    # 文本文件读取
    return _read_text(path, offset, limit)


def _resolve_path(file_path: str) -> Path | None:
    """解析并验证路径（绝对路径 + 敏感路径校验）。"""
    # ToolRegistry.call_tool() 传入的是完整 arguments dict，提取 file_path 键
    if isinstance(file_path, dict):
        file_path = file_path.get("file_path", "")
        if not file_path:
            return None

    # 敏感路径校验（硬阻止 + 软阻止）
    allowed, _reason = validate_path(file_path, mode="read")
    if not allowed:
        return None

    path = Path(os.path.expanduser(file_path))
    if not path.is_absolute():
        return None
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return None
    if not resolved.exists():
        return None
    return resolved


def _read_text(path: Path, offset: int, limit: int) -> dict[str, Any]:
    """读取文本文件。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except IOError as exc:
        return {"type": "error", "error": f"读取失败: {exc}", "success": False}

    total_lines = len(lines)

    # offset 为 1-based 行号
    start_idx = max(0, offset - 1) if offset > 0 else 0

    end_idx = min(start_idx + limit, total_lines)
    selected = lines[start_idx:end_idx]
    content = "".join(selected)

    return {
        "type": "text",
        "content": content,
        "line_count": len(selected),
        "total_lines": total_lines,
        "file_path": str(path),
        "offset": start_idx + 1 if offset > 0 else 1,
        "limit": limit,
        "truncated": end_idx < total_lines,
    }


def _read_image(path: Path) -> dict[str, Any]:
    """读取图片文件（返回 base64 路径供渲染）。"""
    try:
        fsize = path.stat().st_size
    except OSError:
        return {"type": "error", "error": f"无法获取文件信息: {path}", "success": False}

    if fsize > _MAX_IMAGE_SIZE:
        return {"type": "error", "error": f"图片过大 ({fsize} bytes > {_MAX_IMAGE_SIZE})，拒绝读取", "success": False}

    return {
        "type": "image",
        "file_path": str(path),
        "mime_type": _get_mime_type(path.suffix.lower()),
        "size_bytes": fsize,
        "note": "图片已作为附件返回，可被 GUI 渲染",
    }


def _read_directory(path: Path) -> dict[str, Any]:
    """列出目录内容。"""
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return {"type": "error", "error": f"无权限读取目录: {path}", "success": False}

    result = []
    for entry in entries:
        result.append({
            "name": entry.name + ("/" if entry.is_dir() else ""),
            "size": entry.stat().st_size if entry.is_file() else None,
        })

    return {
        "type": "directory",
        "file_path": str(path),
        "entries": result,
        "count": len(result),
    }


def _get_mime_type(suffix: str) -> str:
    """根据扩展名返回 MIME 类型。"""
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
        ".tiff": "image/tiff",
        ".svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")
