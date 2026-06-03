"""
路径安全规则引擎。

提供：
- validate_path(): 文件工具入口统一路径校验
- validate_search_root(): grep/glob 搜索起点校验
- HARD_DENY_PATTERNS: 不可覆盖的敏感路径名单
- SOFT_DENY_PATTERNS: 默认阻止但可配置放宽的路径
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Optional

# ── 硬阻止名单 — 不可被配置覆盖 ──────────────────────────────
HARD_DENY_PATTERNS = [
    # SSH 密钥
    "**/.ssh/id_*",
    "**/.ssh/*_key",
    "**/.ssh/*_key.pub",
    "**/.ssh/authorized_keys",
    "**/.ssh/known_hosts",
    # 云凭据
    "**/.aws/credentials",
    "**/.aws/config",
    "**/.config/gcloud/*credentials*",
    "**/.azure/*.pem",
    "**/.azure/accessTokens.json",
    # GPG
    "**/.gnupg/private*",
    "**/.gnupg/secring*",
    # Docker
    "**/.docker/config.json",
    # K8s
    "**/.kube/config",
    # 系统敏感文件
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/sudoers.d/*",
    "/etc/crontab",
    "/etc/cron.d/*",
    "/proc/*",
    "/sys/*",
    # 司南自身数据
    "**/.sinan/audit/*",
]

# ── 软阻止名单 — 可通过 allow_soft=True 放宽 ──────────────────
SOFT_DENY_PATTERNS = [
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/*.crt",
    "**/*.pfx",
    "**/*.p12",
    "**/*password*",
    "**/*secret*",
    "**/*credential*",
    "**/*token*",
    "**/.git-credentials",
]

# ── 搜索/遍历禁止起点 ───────────────────────────────────────
FORBIDDEN_SEARCH_ROOTS = [
    "/",
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/root",
    "/var/log",
    "/var/run",
]


def _is_sensitive(resolved_path_str: str, *, allow_soft: bool = False) -> bool:
    """检查路径是否命中敏感名单。

    硬阻止名单始终生效；软阻止名单仅在 ``allow_soft=True`` 时放行。

    Args:
        resolved_path_str: 已 resolve 的绝对路径字符串。
        allow_soft: 为 True 时跳过软阻止检查。

    Returns:
        True 表示命中阻止名单。
    """
    # 硬阻止优先级最高
    for pat in HARD_DENY_PATTERNS:
        if fnmatch.fnmatch(resolved_path_str, pat):
            return True

    if allow_soft:
        return False

    # 软阻止
    for pat in SOFT_DENY_PATTERNS:
        if fnmatch.fnmatch(resolved_path_str, pat):
            return True

    return False


def validate_path(
    file_path: str,
    *,
    workspace: Optional[str] = None,
    mode: str = "read",
    allow_soft: bool = False,
) -> tuple[bool, str]:
    """统一文件路径校验。

    返回 (allowed, reason) 元组。allowed=True 时 reason 为空。

    校验规则（按优先级）：
    1. 必须为绝对路径
    2. 路径解析不失败
    3. 命中 HARD_DENY_PATTERNS → 拒绝（不可覆盖）
    4. 命中 SOFT_DENY_PATTERNS（allow_soft=False 时）→ 拒绝
    5. 指定 workspace 时，目标必须在 workspace 子树内

    Args:
        file_path: 用户提供的路径（可含 ~）。
        workspace: 工作区根目录，None 时不限制作用域。
        mode: "read" 或 "write"（仅影响错误消息语义，校验逻辑不变）。
        allow_soft: True 时跳过软阻止检查。

    Returns:
        (allowed: bool, reason: str)
    """
    # 规则 1：必须绝对路径
    path = Path(os.path.expanduser(file_path))
    if not path.is_absolute():
        return False, "必须提供绝对路径"

    # 规则 2：路径解析
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        return False, f"路径解析失败: {exc}"

    resolved_str = str(resolved)

    # 规则 3：硬阻止
    for pat in HARD_DENY_PATTERNS:
        if fnmatch.fnmatch(resolved_str, pat):
            return False, f"拒绝访问敏感路径 ({pat}): {file_path}"

    # 规则 4：软阻止
    if not allow_soft:
        for pat in SOFT_DENY_PATTERNS:
            if fnmatch.fnmatch(resolved_str, pat):
                return False, f"拒绝访问敏感路径 ({pat}): {file_path}"

    # 规则 5：作用域限制
    if workspace is not None:
        ws = Path(os.path.expanduser(workspace)).resolve()
        try:
            resolved.relative_to(ws)
        except ValueError:
            return False, f"路径不在工作区内: {resolved_str} (workspace: {ws})"

    return True, ""


def validate_search_root(search_path: str) -> tuple[bool, str]:
    """校验 grep/glob 的搜索起点是否安全。

    拒绝系统目录，拒绝过于宽泛的根目录搜索。

    Args:
        search_path: 用户提供的搜索目录。

    Returns:
        (allowed: bool, reason: str)
    """
    path = Path(os.path.expanduser(search_path))
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        return False, f"路径解析失败: {exc}"

    resolved_str = str(resolved)

    for forbidden in FORBIDDEN_SEARCH_ROOTS:
        if resolved_str == forbidden or resolved_str.startswith(forbidden + "/"):
            return False, f"禁止搜索系统目录: {resolved_str} (禁止: {forbidden})"

    # 也检查硬阻止名单
    if _is_sensitive(resolved_str):
        return False, f"禁止搜索敏感路径: {resolved_str}"

    return True, ""
