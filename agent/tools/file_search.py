"""
文件搜索工具 — 参考 Claude Code GrepTool + GlobTool。

提供：
- grep: 正则内容搜索（基于 ripgrep，降级到 Python 实现）
- glob: 文件名模式匹配
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from agent.tools.path_rules import validate_search_root


# ── Grep ──────────────────────────────────────────────────────────────────

# grep 结果上限
_MAX_GREP_RESULTS = 250
_MAX_GREP_OUTPUT_CHARS = 30_000


def grep(
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    output_mode: str = "files_with_matches",
    head_limit: int = 50,
    offset: int = 0,
    ignore_case: bool = False,
    context_lines: int = 0,
) -> dict[str, Any]:
    """在文件中搜索正则模式。

    Args:
        pattern (str): 正则表达式模式 [required]
        path (str): 搜索目录路径（默认当前工作目录）
        glob (str): 文件过滤 glob 模式，如 "*.py"
        output_mode (str): 输出模式 — "content"（含匹配行）/ "files_with_matches"（仅文件名）/ "count"（匹配计数）
        head_limit (int): 最大返回结果数（默认 50）
        offset (int): 跳过前 N 条结果
        ignore_case (bool): 是否忽略大小写（默认 False）
        context_lines (int): 上下文行数（仅在 content 模式下生效）

    Returns:
        dict，包含 matches/files/truncated/error。
    """
    # ToolRegistry.call_tool() 传入完整 arguments dict
    if isinstance(pattern, dict):
        args = pattern
        pattern = args.get("pattern", "")
        path = args.get("path", path)
        glob = args.get("glob", glob)
        output_mode = args.get("output_mode", output_mode)
        head_limit = args.get("head_limit", head_limit)
        offset = args.get("offset", offset)
        ignore_case = args.get("ignore_case", ignore_case)
        context_lines = args.get("context_lines", context_lines)

    search_path = Path(os.path.expanduser(path)) if path else Path.cwd()

    allowed, reason = validate_search_root(str(search_path))
    if not allowed:
        return {"ok": False, "error": reason}

    if not search_path.exists():
        return {"ok": False, "error": f"目录不存在: {search_path}"}

    # 优先使用 ripgrep
    try:
        return _grep_ripgrep(
            pattern=pattern,
            search_path=search_path,
            file_glob=glob,
            output_mode=output_mode,
            head_limit=head_limit,
            offset=offset,
            ignore_case=ignore_case,
            context_lines=context_lines,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    # 降级到 Python 实现
    return _grep_python(
        pattern=pattern,
        search_path=search_path,
        file_glob=glob,
        output_mode=output_mode,
        head_limit=head_limit,
        offset=offset,
        ignore_case=ignore_case,
        context_lines=context_lines,
    )


def _grep_ripgrep(
    pattern: str,
    search_path: Path,
    file_glob: str | None,
    output_mode: str,
    head_limit: int,
    offset: int,
    ignore_case: bool,
    context_lines: int,
) -> dict[str, Any]:
    """使用 ripgrep 执行搜索。"""
    cmd = ["rg", "--line-number", "--no-heading", "--color=never"]

    if ignore_case:
        cmd.append("--ignore-case")

    if output_mode == "files_with_matches":
        cmd.append("--files-with-matches")
    elif output_mode == "count":
        cmd.append("--count")

    if context_lines > 0 and output_mode == "content":
        cmd.extend(["-C", str(context_lines)])

    if file_glob:
        cmd.extend(["--glob", file_glob])

    cmd.extend(["--", pattern, str(search_path)])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout.strip()
    if result.returncode not in (0, 1):  # rg: 0=match, 1=no match
        return {"ok": False, "error": result.stderr.strip() or "ripgrep 执行失败"}

    if not output:
        return {"ok": True, "matches": [], "files": [], "count": 0}

    lines = output.split("\n")
    total_hits = len(lines)

    # 应用 offset + head_limit
    if offset and output_mode != "count":
        lines = lines[offset:]

    truncated = len(lines) > head_limit
    if len(lines) > head_limit:
        lines = lines[:head_limit]

    # 截断输出
    result_text = "\n".join(lines)
    if len(result_text) > _MAX_GREP_OUTPUT_CHARS:
        result_text = result_text[:_MAX_GREP_OUTPUT_CHARS]
        result_text += f"\n... (输出已截断至 {_MAX_GREP_OUTPUT_CHARS} 字符)"
        truncated = True

    if output_mode == "files_with_matches":
        return {
            "ok": True,
            "files": lines,
            "count": len(lines),
            "total_hits": total_hits,
            "truncated": truncated,
        }
    elif output_mode == "count":
        counts = {}
        for line in lines:
            if ":" in line:
                fpath, count_str = line.rsplit(":", 1)
                counts[fpath] = int(count_str)
        return {"ok": True, "counts": counts, "files": list(counts.keys()), "truncated": truncated}
    else:
        files = set()
        for line in lines:
            if ":" in line:
                files.add(line.split(":", 1)[0])
        return {
            "ok": True,
            "matches": lines,
            "files": sorted(files),
            "count": len(lines),
            "total_hits": total_hits,
            "truncated": truncated,
        }


def _grep_python(
    pattern: str,
    search_path: Path,
    file_glob: str | None,
    output_mode: str,
    head_limit: int,
    offset: int,
    ignore_case: bool,
    context_lines: int,
) -> dict[str, Any]:
    """Python 降级实现的正则搜索。"""
    try:
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return {"ok": False, "error": f"无效的正则表达式: {exc}"}

    matches: list[str] = []
    matched_files: set[str] = set()
    file_counts: dict[str, int] = {}

    for file_path in _walk_files(search_path, file_glob):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except (IOError, PermissionError):
            continue

        if output_mode == "files_with_matches":
            if regex.search(content):
                matched_files.add(str(file_path))
        elif output_mode == "count":
            cnt = len(regex.findall(content))
            if cnt > 0:
                file_counts[str(file_path)] = cnt
        else:
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if regex.search(line):
                    line_num = i + 1
                    if context_lines > 0:
                        ctx_start = max(0, i - context_lines)
                        ctx_end = min(len(lines), i + context_lines + 1)
                        ctx_lines = []
                        for j in range(ctx_start, ctx_end):
                            prefix = ">" if j == i else " "
                            ctx_lines.append(f"{prefix}{str(file_path)}:{j + 1}:{lines[j]}")
                        matches.append("\n".join(ctx_lines))
                    else:
                        matches.append(f"{file_path}:{line_num}:{line}")

    if output_mode == "files_with_matches":
        files_list = sorted(matched_files)
        truncated = len(files_list) > head_limit
        return {
            "ok": True,
            "files": files_list[:head_limit],
            "count": len(files_list[:head_limit]),
            "total_matches": len(files_list),
            "truncated": truncated,
        }
    elif output_mode == "count":
        items = list(file_counts.items())
        truncated = len(items) > head_limit
        return {
            "ok": True,
            "counts": dict(items[:head_limit]),
            "truncated": truncated,
        }
    else:
        total = len(matches)
        if offset:
            matches = matches[offset:]
        truncated = len(matches) > head_limit
        result_matches = matches[:head_limit]
        files = set()
        for m in result_matches:
            if ":" in m:
                files.add(m.split(":", 1)[0])
        # 截断输出
        result_text = "\n".join(result_matches)
        if len(result_text) > _MAX_GREP_OUTPUT_CHARS:
            result_text = result_text[:_MAX_GREP_OUTPUT_CHARS] + "\n... (截断)"
        return {
            "ok": True,
            "matches": result_text.split("\n") if result_text else [],
            "files": sorted(files),
            "count": len(result_matches),
            "total_matches": total,
            "truncated": truncated,
        }


# ── Glob ──────────────────────────────────────────────────────────────────

_MAX_GLOB_RESULTS = 200


def glob(pattern: str, path: str | None = None) -> dict[str, Any]:
    """文件名 glob 模式匹配。

    Args:
        pattern (str): glob 模式，如 "**/*.py" [required]
        path (str): 搜索根目录（默认当前工作目录）

    Returns:
        dict，包含 filenames/count/truncated。
    """
    # ToolRegistry.call_tool() 传入完整 arguments dict
    if isinstance(pattern, dict):
        args = pattern
        pattern = args.get("pattern", "")
        path = args.get("path", path)

    search_path = Path(os.path.expanduser(path)) if path else Path.cwd()

    allowed, reason = validate_search_root(str(search_path))
    if not allowed:
        return {"ok": False, "error": reason}

    if not search_path.exists():
        return {"ok": False, "error": f"目录不存在: {search_path}"}

    results = []
    count = 0
    truncated = False

    for match in search_path.glob(pattern):
        count += 1
        if len(results) < _MAX_GLOB_RESULTS:
            rel_path = (
                str(match.relative_to(search_path))
                if match.is_relative_to(search_path)
                else str(match)
            )
            entry = rel_path
            if match.is_dir():
                entry += "/"
            # 按修改时间排序
            results.append({
                "path": entry,
                "size": match.stat().st_size if match.is_file() else None,
                "is_dir": match.is_dir(),
            })

    if count > _MAX_GLOB_RESULTS:
        truncated = True

    # 按修改时间降序
    results.sort(key=lambda r: r.get("size") or 0, reverse=True)

    return {
        "ok": True,
        "filenames": [r["path"] for r in results],
        "entries": results[:100],  # 详细 entry 最多 100 条
        "count": len(results),
        "total_found": count,
        "truncated": truncated,
    }


# ── 辅助 ──────────────────────────────────────────────────────────────────

_EXCLUDED_DIRS = {".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv", ".tox"}
_EXCLUDED_PREFIXES = (".",)


def _walk_files(root: Path, file_glob: str | None) -> list[Path]:
    """遍历文件树，返回匹配的文件列表。"""
    files = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        # 排除隐藏/构建目录
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS and not d.startswith(_EXCLUDED_PREFIXES)]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            if file_glob and not fnmatch.fnmatch(fname, file_glob):
                continue
            files.append(fpath)
    return files
