"""编排任务工具 — task_create/list/get/update/stop/output。"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from agent.orchestration.task_types import (
    TaskStateBase,
    OrchestrationTaskType,
    OrchestrationTaskStatus,
    generate_task_id,
    is_terminal_status,
)
from agent.orchestration.task_output import TaskOutput


def _tasks_dir() -> Path:
    p = Path.home() / ".sinan" / "tasks"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _task_file(task_id: str) -> Path:
    return _tasks_dir() / f"{task_id}.json"


def _save(task: TaskStateBase) -> None:
    d = {
        "id": task.id, "type": task.type.value, "status": task.status.value,
        "description": task.description, "owner": task.owner,
        "start_time": task.start_time, "end_time": task.end_time,
        "output_file": task.output_file, "allowed_tools": task.allowed_tools,
        "metadata": task.metadata,
    }
    _task_file(task.id).write_text(json.dumps(d, indent=2, ensure_ascii=False))


def _load(task_id: str) -> Optional[TaskStateBase]:
    f = _task_file(task_id)
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    return TaskStateBase(
        id=d["id"], type=OrchestrationTaskType(d["type"]),
        status=OrchestrationTaskStatus(d["status"]),
        description=d.get("description", ""), owner=d.get("owner", ""),
        start_time=d.get("start_time", time.time()),
        end_time=d.get("end_time"),
        output_file=d.get("output_file", ""),
        allowed_tools=d.get("allowed_tools", []),
        metadata=d.get("metadata", {}),
    )


_STATE_MACHINE = {
    OrchestrationTaskStatus.PENDING: {OrchestrationTaskStatus.IN_PROGRESS, OrchestrationTaskStatus.KILLED},
    OrchestrationTaskStatus.IN_PROGRESS: {
        OrchestrationTaskStatus.COMPLETED, OrchestrationTaskStatus.FAILED, OrchestrationTaskStatus.KILLED,
    },
}


def _is_valid_transition(current: OrchestrationTaskStatus, target: OrchestrationTaskStatus) -> bool:
    if target == OrchestrationTaskStatus.COMPLETED and current != OrchestrationTaskStatus.IN_PROGRESS:
        return False
    allowed = _STATE_MACHINE.get(current, set())
    return target in allowed


# ── task_create ────────────────────────────────────────────

def task_create(arguments: dict) -> dict:
    """创建编排任务。"""
    if isinstance(arguments, str):
        return {"success": False, "error": "arguments 需为字典"}

    agent_type = arguments.get("agent_type") or arguments.get("type", "local_agent")
    try:
        tt = OrchestrationTaskType(agent_type)
    except ValueError:
        return {"success": False, "error": f"未知 agent_type: {agent_type}"}

    task = TaskStateBase(
        id=generate_task_id(tt),
        type=tt,
        status=OrchestrationTaskStatus.PENDING,
        description=arguments.get("description", ""),
        owner=arguments.get("owner", ""),
        allowed_tools=arguments.get("allowed_tools", []),
        metadata=arguments.get("metadata", {}),
    )
    _save(task)
    return {"success": True, "task_id": task.id, "status": task.status.value}


# ── task_list ──────────────────────────────────────────────

def task_list(arguments: dict) -> dict:
    """列出所有任务。"""
    status_filter = arguments.get("status") if isinstance(arguments, dict) else None
    tasks = []
    for f in sorted(_tasks_dir().glob("*.json")):
        try:
            t = _load(f.stem)
            if t:
                if status_filter and t.status.value != status_filter:
                    continue
                tasks.append({"task_id": t.id, "type": t.type.value, "status": t.status.value,
                              "description": t.description, "owner": t.owner})
        except Exception:
            continue
    return {"success": True, "tasks": tasks, "count": len(tasks)}


# ── task_get ───────────────────────────────────────────────

def task_get(arguments: dict) -> dict:
    """获取任务详情。"""
    task_id = arguments.get("task_id", "")
    task = _load(task_id)
    if not task:
        return {"success": False, "error": f"任务不存在: {task_id}"}
    return {
        "success": True, "task_id": task.id, "type": task.type.value,
        "status": task.status.value, "description": task.description,
        "owner": task.owner, "allowed_tools": task.allowed_tools,
        "start_time": task.start_time, "end_time": task.end_time,
        "output_file": task.output_file, "metadata": task.metadata,
    }


# ── task_update ────────────────────────────────────────────

def task_update(arguments: dict) -> dict:
    """更新任务状态。"""
    task_id = arguments.get("task_id", "")
    task = _load(task_id)
    if not task:
        return {"success": False, "error": f"任务不存在: {task_id}"}

    new_status = arguments.get("status")
    if new_status:
        try:
            ts = OrchestrationTaskStatus(new_status)
        except ValueError:
            return {"success": False, "error": f"无效状态: {new_status}"}
        if not _is_valid_transition(task.status, ts):
            return {"success": False, "error": f"非法状态转换: {task.status.value} -> {ts.value}"}
        task.status = ts
        if is_terminal_status(ts):
            task.end_time = time.time()

    if "owner" in arguments:
        task.owner = arguments["owner"]
    if "metadata" in arguments:
        task.metadata.update(arguments["metadata"])

    _save(task)
    return {"success": True, "task_id": task.id, "status": task.status.value}


# ── task_stop ──────────────────────────────────────────────

def task_stop(arguments: dict) -> dict:
    """停止任务。"""
    task_id = arguments.get("task_id", "")
    force = arguments.get("force", False)
    task = _load(task_id)
    if not task:
        return {"success": False, "error": f"任务不存在: {task_id}"}

    if task.status not in (OrchestrationTaskStatus.PENDING, OrchestrationTaskStatus.IN_PROGRESS):
        return {"success": False, "error": f"任务不在可停止状态: {task.status.value}"}

    # HIGH 危险等级只允许 graceful cancel
    if task.type == OrchestrationTaskType.HARDWARE_OP and not force:
        if task.status == OrchestrationTaskStatus.IN_PROGRESS:
            return {
                "success": False,
                "error": "硬件操作任务正在进行中，不支持强制停止。请使用 force=true 或等待任务完成。",
                "hint": "graceful_only",
            }

    task.status = OrchestrationTaskStatus.KILLED
    task.end_time = time.time()
    _save(task)
    return {"success": True, "task_id": task.id, "status": task.status.value}


# ── task_output ────────────────────────────────────────────

def task_output(arguments: dict) -> dict:
    """获取任务输出。"""
    task_id = arguments.get("task_id", "")
    max_bytes = arguments.get("max_bytes", 100_000)
    task = _load(task_id)
    if not task:
        return {"success": False, "error": f"任务不存在: {task_id}"}

    out = TaskOutput(task_id)
    content = out.get_output(max_bytes=max_bytes)
    return {"success": True, "task_id": task_id, "output": content, "bytes": len(content)}
