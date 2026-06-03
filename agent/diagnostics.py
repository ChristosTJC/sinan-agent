"""CLI diagnostics, demo smoke checks, and redacted support reports."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from agent import __version__

_SENSITIVE_KEYWORDS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "passwd",
    "secret",
    "token",
)

_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{4,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{4,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{4,}"),
)

_REPORT_ENV_PREFIXES = (
    "SINAN",
    "OPENAI",
    "ANTHROPIC",
    "PYTHON",
    "VIRTUAL_ENV",
    "CONDA",
    "PIO",
    "ARDUINO",
    "ZEPHYR",
    "PATH",
)

_OPTIONAL_EXTERNAL_TOOLS = (
    ("PlatformIO", ("pio", "platformio")),
    ("pyOCD", ("pyocd",)),
    ("esptool", ("esptool.py", "esptool")),
    ("OpenOCD", ("openocd",)),
    ("STM32CubeProgrammer", ("STM32_Programmer_CLI",)),
    ("nrfjprog", ("nrfjprog",)),
    ("CMake", ("cmake",)),
    ("Make", ("make",)),
    ("Arduino CLI", ("arduino-cli",)),
)


def redact_text(text: str) -> str:
    """Redact common token values from free-form diagnostics text."""
    redacted = text
    for pattern in _SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    redacted = re.sub(
        r"(?i)((?:api[_-]?key|authorization|credential|password|passwd|secret|token)\s*[:=]\s*)\S+",
        r"\1[REDACTED]",
        redacted,
    )
    return redacted


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _is_sensitive_env_key(key: str) -> bool:
    normalized = key.lower()
    return any(word in normalized for word in _SENSITIVE_KEYWORDS)


def _env_snapshot() -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for key in sorted(os.environ):
        if not key.startswith(_REPORT_ENV_PREFIXES):
            continue
        value = os.environ[key]
        snapshot[key] = "[REDACTED]" if _is_sensitive_env_key(key) else redact_text(value)
    return snapshot


def _count_files(path: Path, patterns: tuple[str, ...]) -> int:
    if not path.exists():
        return 0
    count = 0
    for pattern in patterns:
        count += sum(1 for item in path.rglob(pattern) if item.is_file())
    return count


def _external_tool_status() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for label, candidates in _OPTIONAL_EXTERNAL_TOOLS:
        found = None
        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                break
        tools.append({
            "name": label,
            "available": found is not None,
            "path": found or "",
            "candidates": list(candidates),
        })
    return tools


def _detect_build_system(project_path: Path) -> str | None:
    if not project_path.is_dir():
        return None
    if (project_path / "platformio.ini").is_file():
        return "platformio"
    if (project_path / "CMakeLists.txt").is_file():
        return "cmake"
    if (project_path / "Makefile").is_file():
        return "make"
    if any(project_path.glob("*.ino")):
        return "arduino"
    return None


def _tool_registry_status(scan_hardware: bool = False, sinan_home: Path | None = None) -> dict[str, Any]:
    status: dict[str, Any] = {
        "available": False,
        "tool_count": 0,
        "tool_names": [],
        "hardware_scan": None,
        "error": None,
    }
    try:
        from agent.tools import get_registry

        registry = get_registry()

        if sinan_home is not None:
            from agent.memory.core_memory import MemoryStore
            from agent.memory.knowledge_base import KnowledgeBase
            from agent.memory.session_db import SessionDB

            project_kb_dir = Path(__file__).resolve().parent.parent / "knowledge"
            user_kb_dir = sinan_home / "knowledge"
            store = MemoryStore()
            store.load_from_disk(sinan_home / "memories")
            kb = KnowledgeBase(kb_dir=project_kb_dir, user_kb_dir=user_kb_dir)
            db = SessionDB(sinan_home / "sessions")
            registry.set_memory_context(store, kb, db, sinan_home)

        tools = registry.list_tools()
        names = sorted(t.get("name", "") for t in tools if t.get("name"))
        status.update({
            "available": True,
            "tool_count": len(names),
            "tool_names": names,
        })
        if scan_hardware:
            status["hardware_scan"] = {
                "serial": registry.call_tool("scan_serial", {}),
                "usb": registry.call_tool("scan_usb", {}),
            }
    except Exception as exc:  # pragma: no cover - defensive diagnostics path
        status["error"] = str(exc)
    return status


def collect_demo_status(sinan_home: Path, project_path: Path) -> dict[str, Any]:
    """Collect a no-hardware smoke status for the 60-second demo command."""
    root = _repo_root()
    knowledge_count = _count_files(root / "knowledge", ("*.yaml", "*.yml", "*.md", "*.json"))
    board_count = _count_files(root / "board_knowledge" / "boards", ("*.json",))
    skill_count = _count_files(root / "skills", ("SKILL.md",))
    registry = _tool_registry_status(scan_hardware=False, sinan_home=sinan_home)
    build_system = _detect_build_system(project_path)

    dirs = {
        name: sinan_home / name
        for name in ("memories", "sessions", "knowledge", "skills")
    }
    checks = [
        {
            "name": "runtime_dirs",
            "ok": all(path.is_dir() for path in dirs.values()),
            "message": f"SINAN_HOME={sinan_home}",
        },
        {
            "name": "knowledge",
            "ok": knowledge_count > 0,
            "message": f"{knowledge_count} packaged knowledge files",
        },
        {
            "name": "boards",
            "ok": board_count > 0,
            "message": f"{board_count} board profiles",
        },
        {
            "name": "skills",
            "ok": skill_count > 0,
            "message": f"{skill_count} packaged skills",
        },
        {
            "name": "tools",
            "ok": registry["available"] and registry["tool_count"] > 0,
            "message": f"{registry['tool_count']} registered tools",
        },
    ]

    return {
        "kind": "demo",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "version": __version__,
        "sinan_home": str(sinan_home),
        "project_path": str(project_path),
        "build_system": build_system,
        "counts": {
            "knowledge": knowledge_count,
            "boards": board_count,
            "skills": skill_count,
        },
        "registry": registry,
        "checks": checks,
        "success": all(check["ok"] for check in checks),
    }


def collect_doctor_status(
    sinan_home: Path,
    project_path: Path,
    scan_hardware: bool = False,
) -> dict[str, Any]:
    """Collect environment diagnostics without hardware side effects by default."""
    demo = collect_demo_status(sinan_home, project_path)
    status = {
        "kind": "doctor",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "version": __version__,
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "sinan_home": str(sinan_home),
        "project_path": str(project_path),
        "build_system": demo["build_system"],
        "checks": demo["checks"],
        "counts": demo["counts"],
        "registry": _tool_registry_status(scan_hardware=scan_hardware, sinan_home=sinan_home),
        "external_tools": _external_tool_status(),
        "environment": _env_snapshot(),
    }
    status["success"] = all(check["ok"] for check in status["checks"])
    return status


def render_demo(status: dict[str, Any]) -> str:
    lines = [
        "司南 demo - no-hardware smoke test",
        f"version: {status['version']}",
        f"SINAN_HOME: {status['sinan_home']}",
        f"project: {status['project_path']}",
        f"build_system: {status.get('build_system') or 'not detected'}",
        "",
        "checks:",
    ]
    for check in status["checks"]:
        marker = "OK" if check["ok"] else "FAIL"
        lines.append(f"  [{marker}] {check['name']}: {check['message']}")
    return "\n".join(lines) + "\n"


def render_doctor(status: dict[str, Any]) -> str:
    lines = [
        "司南 doctor - environment diagnostics",
        f"Python: {status['python']['version']} ({status['python']['executable']})",
        f"Platform: {status['python']['platform']}",
        f"SINAN_HOME: {status['sinan_home']}",
        f"Project: {status['project_path']}",
        f"Build system: {status.get('build_system') or 'not detected'}",
        "",
        "core checks:",
    ]
    for check in status["checks"]:
        marker = "OK" if check["ok"] else "FAIL"
        lines.append(f"  [{marker}] {check['name']}: {check['message']}")

    lines.extend(["", "optional tools:"])
    for tool in status["external_tools"]:
        marker = "OK" if tool["available"] else "MISS"
        path = tool["path"] or ", ".join(tool["candidates"])
        lines.append(f"  [{marker}] {tool['name']}: {path}")

    hardware_scan = status.get("registry", {}).get("hardware_scan")
    if hardware_scan is not None:
        lines.extend(["", "hardware scan:"])
        serial = hardware_scan.get("serial", {})
        usb = hardware_scan.get("usb", {})
        lines.append(f"  serial: {serial.get('result', serial.get('error', 'unknown'))}")
        lines.append(f"  usb: {usb.get('result', usb.get('error', 'unknown'))}")

    return "\n".join(lines) + "\n"


def default_report_path(sinan_home: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return sinan_home / "reports" / f"sinan-report-{stamp}.md"


def render_report(status: dict[str, Any]) -> str:
    sections = [
        "# Sinan Diagnostic Report",
        "",
        f"- generated_at: {status['timestamp']}",
        f"- version: {status['version']}",
        f"- sinan_home: {status['sinan_home']}",
        f"- project_path: {status['project_path']}",
        f"- build_system: {status.get('build_system') or 'not detected'}",
        "",
        "## Doctor",
        "",
        render_doctor(status).strip(),
        "",
        "## Environment",
        "",
        "```json",
        json.dumps(status.get("environment", {}), indent=2, ensure_ascii=False),
        "```",
        "",
        "## Raw Status",
        "",
        "```json",
        json.dumps(status, indent=2, ensure_ascii=False, default=str),
        "```",
        "",
    ]
    return redact_text("\n".join(sections))


def write_report(status: dict[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(status), encoding="utf-8")
    return output
