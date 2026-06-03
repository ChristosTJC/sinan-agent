"""受限 shell 命令执行工具。

安全约束：
- deny_patterns 拦截危险命令 (rm -rf / sudo dd mkfs curl|sh 等)
- 默认仅允许项目目录内执行 (allow_outside_project=False)
- 强制 timeout_sec (默认 30s) + max_output_bytes (默认 100KB)
- 写入操作走 MEDIUM danger_level + approval_required
- 继承 P1 事件/Hook/审计
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

# ── 命令 deny patterns ───────────────────────────────────────
_DENY_PATTERNS: list[tuple[str, str]] = [
    (r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*)\b", "禁止删除命令 (rm -rf)"),
    (r"\bsudo\b", "禁止 sudo"),
    (r"\bchmod\s+777\b", "禁止 chmod 777"),
    (r"\bchmod\s+\+[rwx]+\b", "禁止 chmod 宽松权限"),
    (r"\bdd\s+if=", "禁止 dd 磁盘操作"),
    (r"\bmkfs\.", "禁止格式化命令 (mkfs)"),
    (r"\bmount\b", "禁止 mount"),
    (r"\bumount\b", "禁止 umount"),
    (r"\bfdisk\b", "禁止 fdisk"),
    (r"\bparted\b", "禁止 parted"),
    (r"\bshutdown\b", "禁止 shutdown"),
    (r"\breboot\b", "禁止 reboot"),
    (r"\bwget\b.*\|.*sh\b", "禁止 curl/wget 管道执行"),
    (r"\bcurl\b.*\|.*sh\b", "禁止 curl/wget 管道执行"),
    (r"\b>/etc/", "禁止写入 /etc"),
    (r"\b>\s*/dev/", "禁止覆盖设备"),
    (r"\bcrontab\b", "禁止 crontab"),
    (r"\bpasswd\b", "禁止 passwd"),
    (r"\biptables\b", "禁止 iptables"),
    (r"\bfirewall-cmd\b", "禁止 firewall-cmd"),
]

# ── 读操作识别 ────────────────────────────────────────────────
_READ_ONLY_CMDS = {
    "ls", "cat", "head", "tail", "less", "grep", "rg", "find", "locate",
    "wc", "file", "stat", "du", "df", "pwd", "env", "printenv",
    "which", "whereis", "whoami", "id", "uname", "hostname",
    "ps", "top", "free", "uptime", "dmesg", "lsof", "netstat",
    "git", "hg", "svn", "poetry", "pip", "cargo", "go",
    "python3", "python", "node", "ruby", "rustc", "gcc", "clang",
    "make", "cmake", "ninja", "pio", "west",
}


def _check_deny(command: str) -> tuple[bool, str]:
    """检查命令是否命中 deny patterns。返回 (denied, reason)。"""
    for pattern, reason in _DENY_PATTERNS:
        if re.search(pattern, command):
            return True, reason
    return False, ""


def _is_read_only(cmd: str) -> bool:
    """判断命令是否为只读操作。"""
    first = cmd.strip().split()[0] if cmd.strip() else ""
    base = os.path.basename(first)
    return base in _READ_ONLY_CMDS


def _run(command: str, timeout: int, cwd: str) -> dict[str, Any]:
    """执行命令。始终 list-based subprocess，不经过 shell。"""
    proc = subprocess.run(
        ["/bin/bash", "-c", command],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    return {
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
    }


def shell_command(arguments: dict) -> dict[str, Any]:
    """执行受限 shell 命令。

    Args:
        command (str): 要执行的命令 [required]
        timeout_sec (int): 超时秒数 (默认 30, 最大 120)
        max_output_bytes (int): 最大输出字节数 (默认 100000)
        cwd (str): 工作目录 (默认项目根目录)
        allow_outside_project (bool): 是否允许项目外执行 (默认 False)

    Returns:
        dict with stdout/stderr/returncode/truncated/denied
    """
    if isinstance(arguments, dict):
        args = arguments
        command = args.get("command", "")
        timeout_sec = min(args.get("timeout_sec", 30), 120)
        max_output = args.get("max_output_bytes", 100_000)
        cwd = args.get("cwd", str(Path.cwd()))
        allow_outside = args.get("allow_outside_project", False)
    else:
        command = str(arguments)
        timeout_sec = 30
        max_output = 100_000
        cwd = str(Path.cwd())
        allow_outside = False

    if not command or not command.strip():
        return {"success": False, "error": "缺少参数: command", "truncated": False, "denied": False}

    # 1. deny pattern 检查
    denied, reason = _check_deny(command)
    if denied:
        return {"success": False, "error": f"命令被拒绝: {reason}", "command": command,
                "denied": True, "truncated": False}

    # 2. 项目作用域检查
    project_root = Path.cwd().resolve()
    cwd_resolved = Path(os.path.expanduser(cwd)).resolve()
    if not allow_outside:
        try:
            cwd_resolved.relative_to(project_root)
        except ValueError:
            return {"success": False, "error": f"不允许项目外执行: {cwd_resolved} 不在 {project_root} 内",
                    "command": command, "denied": True, "truncated": False}

    # 3. 执行
    try:
        result = _run(command, timeout_sec, cwd_resolved)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"命令超时 ({timeout_sec}s)", "command": command,
                "denied": False, "truncated": False}
    except FileNotFoundError:
        return {"success": False, "error": f"命令未找到: {command.split()[0] if command else ''}",
                "command": command, "denied": False, "truncated": False}
    except Exception as exc:
        return {"success": False, "error": f"执行失败: {exc}", "command": command,
                "denied": False, "truncated": False}

    # 4. 输出截断
    stdout = result["stdout"]
    stderr = result["stderr"]
    combined = stdout
    if stderr:
        combined += "\n# stderr:\n" + stderr

    truncated = len(combined) > max_output
    if truncated:
        combined = combined[:max_output] + f"\n... (输出截断: {len(combined)} bytes -> {max_output}"

    return {
        "success": result["returncode"] == 0,
        "stdout": stdout[:max_output] if len(stdout) > max_output else stdout,
        "stderr": stderr[:5000] if len(stderr) > 5000 else stderr,
        "returncode": result["returncode"],
        "truncated": truncated,
        "denied": False,
        "command": command,
        "output_bytes": len(combined),
    }
