"""Visible Sinan agent run loop with trace artifact persistence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from agent.orchestrator import AgentOrchestrator
from agent.tools import DangerLevel

PHASE_ORDER = ("understand", "retrieve", "plan", "execute", "verify", "consolidate")

_PHASE_LABELS = {
    "understand": "理解目标",
    "retrieve": "检索上下文",
    "plan": "生成计划",
    "execute": "执行工具",
    "verify": "验证结果",
    "consolidate": "沉淀记录",
}

_RUN_SYSTEM_PROMPT = (
    "你是司南，嵌入式系统开发智能体。根据用户目标自主调用工具完成任务："
    "扫描设备、编译/烧录固件、监听串口、诊断日志等。"
    "每步说明你的判断，工具失败时分析原因并调整，完成后给出简洁结论。"
)


class RunTraceWriter:
    """Writes a single run's task metadata, plan, trace, report, and structured events."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.run_dir / "trace.jsonl"
        self.event_path = self.run_dir / "event.jsonl"

    def append_event(self, event: dict[str, Any]) -> None:
        event = dict(event)
        event.setdefault("timestamp", _now())
        with self.trace_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def write_sinan_event(self, event) -> None:
        """Write a SinanEvent dataclass as structured JSONL."""
        from dataclasses import asdict
        from agent.orchestration.events import sanitize_event_payload
        d = sanitize_event_payload(asdict(event))
        with self.event_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")

    def write_task(self, task: dict[str, Any]) -> None:
        (self.run_dir / "task.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def write_plan(self, plan: list[dict[str, Any]]) -> None:
        lines = ["# Sinan Run Plan", ""]
        if not plan:
            lines.append("(no steps)")
        for step in plan:
            sid = step.get("step_id", "?")
            action = step.get("action", "")
            tool = step.get("tool") or "none"
            expected = step.get("expected_outcome", "")
            lines.extend([
                f"## Step {sid}: {action}",
                "",
                f"- tool: `{tool}`",
                f"- expected: {expected}",
                "",
            ])
        (self.run_dir / "plan.md").write_text("\n".join(lines), encoding="utf-8")

    def write_report(self, result: dict[str, Any]) -> None:
        phases = result.get("phases", {})
        lines = [
            "# Sinan Run Report",
            "",
            f"- run_id: {result.get('run_id', '')}",
            f"- success: {result.get('success', False)}",
            f"- result: {result.get('result', '')}",
            "",
            "## Phases",
            "",
        ]
        for phase in PHASE_ORDER:
            data = phases.get(phase)
            if data is None:
                continue
            lines.append(f"### {_PHASE_LABELS[phase]}")
            lines.append("")
            if phase == "plan" and isinstance(data, list):
                lines.append(f"{len(data)} step(s)")
            elif isinstance(data, dict):
                summary = data.get("summary") or data.get("intent") or data.get("written")
                if summary is not None:
                    lines.append(str(summary))
                if phase == "execute":
                    lines.append("")
                    for step in data.get("steps", []):
                        lines.append(
                            f"- step {step.get('step_id')}: {step.get('tool') or 'none'} "
                            f"=> {step.get('status')} ({step.get('error') or 'ok'})"
                        )
            lines.append("")
        (self.run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


class SinanRunController:
    """Runs a visible six-phase agent loop and persists trace artifacts."""

    def __init__(
        self,
        *,
        sinan_home: Path,
        project_path: Path,
        registry: Any = None,
        memory_store: Any = None,
        session_db: Any = None,
        knowledge_base: Any = None,
        llm_client: Any = None,
        event_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        confirm_dangerous: bool = False,
        output_dir: Optional[Path] = None,
        run_id: Optional[str] = None,
    ) -> None:
        self.sinan_home = Path(sinan_home)
        self.project_path = Path(project_path)
        self.registry = registry if registry is not None else _create_registry()
        self.memory_store = memory_store if memory_store is not None else _create_memory_store(self.sinan_home)
        self.session_db = session_db if session_db is not None else _create_session_db(self.sinan_home)
        self.knowledge_base = knowledge_base if knowledge_base is not None else _create_knowledge_base(self.sinan_home)
        self.llm_client = llm_client
        self.event_callback = event_callback
        self.confirm_dangerous = confirm_dangerous
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.run_dir = Path(output_dir) if output_dir is not None else self.sinan_home / "runs" / self.run_id
        self.writer = RunTraceWriter(self.run_dir)

    def run(self, goal: str) -> dict[str, Any]:
        """Execute the visible run loop for a user goal."""
        started_at = _now()
        task = {
            "run_id": self.run_id,
            "goal": goal,
            "project_path": str(self.project_path),
            "started_at": started_at,
            "success": False,
            "run_dir": str(self.run_dir),
        }
        self.writer.write_task(task)
        self._emit("run_start", goal=goal, run_id=self.run_id)

        if self.llm_client is not None:
            return self._run_with_agent_session(goal, task)

        orchestrator = AgentOrchestrator(
            registry=self.registry,
            memory_store=self.memory_store,
            session_db=self.session_db,
            knowledge_base=self.knowledge_base,
            llm_client=self.llm_client,
            memories_dir=self.sinan_home / "memories",
        )

        phases: dict[str, Any] = {}

        phases["understand"] = self._run_phase("understand", lambda: orchestrator._phase_understand(goal))
        phases["retrieve"] = self._run_phase("retrieve", lambda: orchestrator._phase_retrieve(goal))
        phases["plan"] = self._run_phase("plan", lambda: orchestrator._phase_plan(goal, phases["retrieve"]))
        self.writer.write_plan(phases["plan"])
        phases["execute"] = self._run_phase("execute", lambda: self._execute_plan(phases["plan"]))
        phases["verify"] = self._run_phase(
            "verify",
            lambda: orchestrator._phase_verify(phases["plan"], phases["execute"], goal),
        )
        phases["consolidate"] = self._run_phase(
            "consolidate",
            lambda: orchestrator._phase_consolidate(goal, phases, self.run_id),
        )

        success = phases["execute"].get("all_passed", True) and phases["verify"].get("all_passed", True)
        result = {
            "success": success,
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "phases": phases,
            "result": phases["execute"].get("summary", ""),
            "memory_written": phases["consolidate"].get("written", False),
        }
        task.update({
            "finished_at": _now(),
            "success": success,
            "result": result["result"],
        })
        self.writer.write_task(task)
        self.writer.write_report(result)
        self._emit("run_done", run_id=self.run_id, success=success, run_dir=str(self.run_dir))
        return result

    def _run_with_agent_session(self, goal, task):
        from agent.core import AgentSession, TraceRenderer, AutoApprove, DenyDangerous

        approval = AutoApprove() if self.confirm_dangerous else DenyDangerous()
        renderer = TraceRenderer(event_path=self.run_dir / "event.jsonl")
        session = AgentSession(
            self.llm_client, self.registry,
            system_prompt=_RUN_SYSTEM_PROMPT,
            approval=approval, renderer=renderer,
            max_tool_depth=getattr(self, "max_tool_depth", 25),
            stream=False,
        )
        self._emit("phase_start", phase="execute", label="执行工具")
        turn = session.send(goal)
        self._emit("phase_done", phase="execute", label="执行工具",
                   summary=f"{turn.tool_calls_made} 次工具调用")

        result = {
            "success": turn.success,
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "phases": {"execute": {"summary": turn.final_text,
                                   "tool_results": turn.tool_results,
                                   "rejected_tools": turn.rejected_tools}},
            "result": turn.final_text,
            "memory_written": False,
        }
        task.update({"finished_at": _now(), "success": turn.success, "result": turn.final_text})
        self.writer.write_task(task)
        self.writer.write_report(result)
        self._emit("run_done", run_id=self.run_id, success=turn.success, run_dir=str(self.run_dir))
        return result

    def _run_phase(self, phase: str, fn: Callable[[], Any]) -> Any:
        self._emit("phase_start", phase=phase, label=_PHASE_LABELS[phase])
        result = fn()
        self._emit("phase_done", phase=phase, label=_PHASE_LABELS[phase], summary=_phase_summary(phase, result))
        return result

    def _execute_plan(self, plan: list[dict[str, Any]]) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        failures: list[str] = []
        all_passed = True
        previous_failed = False

        for step in plan:
            rec = self._skip_step_after_failure(step) if previous_failed else self._execute_step(step)
            steps.append(rec)
            if not rec.get("success", False):
                all_passed = False
                if rec.get("status") != "skipped_previous_failure":
                    previous_failed = True
                    failures.append(f"步骤{rec.get('step_id')}: {rec.get('error', '执行失败')}")

        summary = "全部成功" if all_passed else f"部分失败: {'; '.join(failures)}"
        return {"steps": steps, "all_passed": all_passed, "failures": failures, "summary": summary}

    def _execute_step(self, step: dict[str, Any]) -> dict[str, Any]:
        tool = step.get("tool")
        args = step.get("args", {}) or {}
        step_id = step.get("step_id", "?")
        action = step.get("action", "")
        rec: dict[str, Any] = {
            "step_id": step_id,
            "action": action,
            "tool": tool,
            "args": args,
            "status": "skipped",
            "success": True,
            "result": None,
            "error": None,
        }

        if tool is None:
            rec["result"] = "无需工具"
            self._emit("step_done", step_id=step_id, action=action, tool=None, status="skipped", success=True)
            return rec

        danger_level = _get_danger_level(self.registry, tool)
        if danger_level in (DangerLevel.MEDIUM, DangerLevel.HIGH) and not self.confirm_dangerous:
            error = f"工具 {tool} 为 {danger_level.value}，需要确认；使用 --yes 允许执行"
            rec.update(status="blocked_confirmation", success=False, error=error)
            self._emit(
                "step_blocked",
                step_id=step_id,
                action=action,
                tool=tool,
                danger_level=danger_level.value,
                status="blocked_confirmation",
                error=error,
            )
            return rec

        self._emit(
            "step_start",
            step_id=step_id,
            action=action,
            tool=tool,
            danger_level=danger_level.value,
        )
        result = _call_tool(self.registry, tool, args, allow_dangerous=self.confirm_dangerous)
        success = bool(result.get("success", False))
        rec.update(
            status="ok" if success else "failed",
            success=success,
            result=result,
            error=None if success else result.get("error", "执行失败"),
        )
        self._emit(
            "step_done",
            step_id=step_id,
            action=action,
            tool=tool,
            status=rec["status"],
            success=success,
            summary=_tool_result_summary(result),
        )
        return rec

    def _skip_step_after_failure(self, step: dict[str, Any]) -> dict[str, Any]:
        step_id = step.get("step_id", "?")
        tool = step.get("tool")
        action = step.get("action", "")
        error = "前序步骤失败，已停止顺序链路"
        rec = {
            "step_id": step_id,
            "action": action,
            "tool": tool,
            "args": step.get("args", {}) or {},
            "status": "skipped_previous_failure",
            "success": False,
            "result": None,
            "error": error,
        }
        self._emit(
            "step_skipped",
            step_id=step_id,
            action=action,
            tool=tool,
            status="skipped_previous_failure",
            error=error,
        )
        return rec

    def _emit(self, event: str, **payload: Any) -> None:
        item = {"event": event, **payload}
        self.writer.append_event(item)
        self._emit_sinan_event(event, item)
        if self.event_callback is not None:
            self.event_callback(item)

    def _emit_sinan_event(self, event: str, payload: dict[str, Any]) -> None:
        """Map legacy event strings to SinanEvent dataclasses and write structured log."""
        from agent.orchestration.events import (
            RunStartEvent, RunDoneEvent,
            PhaseStartEvent, PhaseDoneEvent,
            StepStartEvent, StepDoneEvent, StepBlockedEvent, StepSkippedEvent,
        )
        try:
            if event == "run_start":
                self.writer.write_sinan_event(
                    RunStartEvent(goal=payload.get("goal", ""),
                                  run_id=payload.get("run_id", "")))
            elif event == "run_done":
                self.writer.write_sinan_event(
                    RunDoneEvent(run_id=payload.get("run_id", ""),
                                 success=payload.get("success", False),
                                 run_dir=payload.get("run_dir", "")))
            elif event == "phase_start":
                self.writer.write_sinan_event(
                    PhaseStartEvent(phase=payload.get("phase", ""),
                                    label=payload.get("label", "")))
            elif event == "phase_done":
                self.writer.write_sinan_event(
                    PhaseDoneEvent(phase=payload.get("phase", ""),
                                   label=payload.get("label", ""),
                                   summary=payload.get("summary", "")))
            elif event == "step_start":
                self.writer.write_sinan_event(
                    StepStartEvent(step_id=payload.get("step_id", ""),
                                   action=payload.get("action", ""),
                                   tool=payload.get("tool"),
                                   danger_level=payload.get("danger_level", "safe")))
            elif event == "step_done":
                self.writer.write_sinan_event(
                    StepDoneEvent(step_id=payload.get("step_id", ""),
                                  action=payload.get("action", ""),
                                  tool=payload.get("tool"),
                                  success=payload.get("success", True),
                                  summary=payload.get("summary", "")))
            elif event == "step_blocked":
                self.writer.write_sinan_event(
                    StepBlockedEvent(step_id=payload.get("step_id", ""),
                                     action=payload.get("action", ""),
                                     tool=payload.get("tool"),
                                     danger_level=payload.get("danger_level", "safe"),
                                     reason=payload.get("error", payload.get("status", ""))))
            elif event == "step_skipped":
                self.writer.write_sinan_event(
                    StepSkippedEvent(step_id=payload.get("step_id", ""),
                                     action=payload.get("action", ""),
                                     tool=payload.get("tool"),
                                     reason=payload.get("error", payload.get("status", ""))))
        except Exception:
            pass


def format_run_event(event: dict[str, Any]) -> str:
    """Render a trace event as one concise CLI line."""
    kind = event.get("event")
    if kind == "phase_start":
        phase = event.get("phase", "")
        idx = PHASE_ORDER.index(phase) + 1 if phase in PHASE_ORDER else "?"
        return f"[{idx}/6] {event.get('label', phase)}"
    if kind == "phase_done":
        summary = event.get("summary") or ""
        return f"      {summary}" if summary else ""
    if kind == "step_start":
        return f"  -> {event.get('tool')}: calling"
    if kind == "step_blocked":
        return f"  !! {event.get('tool')}: 需要确认 ({event.get('danger_level')})"
    if kind == "step_skipped":
        return f"  xx {event.get('tool') or 'none'}: skipped ({event.get('status')})"
    if kind == "step_done":
        tool = event.get("tool") or "none"
        return f"  <- {tool}: {event.get('status')}"
    if kind == "run_done":
        status = "success" if event.get("success") else "incomplete"
        return f"trace: {event.get('run_dir')} ({status})"
    return ""


def _create_registry() -> Any:
    from agent.tools import get_registry

    return get_registry()


def _create_memory_store(sinan_home: Path) -> Any:
    from agent.memory.core_memory import MemoryStore

    memories_dir = sinan_home / "memories"
    memories_dir.mkdir(parents=True, exist_ok=True)
    store = MemoryStore()
    store.load_from_disk(memories_dir)
    return store


def _create_session_db(sinan_home: Path) -> Any:
    from agent.memory.session_db import SessionDB

    return SessionDB(sinan_home / "sessions")


def _create_knowledge_base(sinan_home: Path) -> Any:
    from agent.memory.knowledge_base import KnowledgeBase

    project_kb_dir = Path(__file__).resolve().parent.parent / "knowledge"
    return KnowledgeBase(kb_dir=project_kb_dir, user_kb_dir=sinan_home / "knowledge")


def _get_danger_level(registry: Any, tool: str) -> DangerLevel:
    if hasattr(registry, "get_danger_level"):
        level = registry.get_danger_level(tool)
        if isinstance(level, DangerLevel):
            return level
        try:
            return DangerLevel(str(level))
        except ValueError:
            return DangerLevel.SAFE
    if hasattr(registry, "is_dangerous") and registry.is_dangerous(tool):
        return DangerLevel.HIGH
    return DangerLevel.SAFE


def _call_tool(registry: Any, tool: str, args: dict[str, Any], allow_dangerous: bool) -> dict[str, Any]:
    previous_confirm = getattr(registry, "_danger_confirm", None)
    try:
        if allow_dangerous and hasattr(registry, "set_danger_confirm"):
            registry.set_danger_confirm(False)
        return registry.call_tool(tool, args)
    finally:
        if previous_confirm is not None and hasattr(registry, "set_danger_confirm"):
            registry.set_danger_confirm(previous_confirm)


def _phase_summary(phase: str, result: Any) -> str:
    if phase == "understand" and isinstance(result, dict):
        return f"intent={result.get('intent')}, target={result.get('target')}"
    if phase == "retrieve" and isinstance(result, dict):
        knowledge = result.get("knowledge") or ""
        memory = result.get("memory") or ""
        return f"knowledge={len(knowledge)} chars, memory={len(memory)} chars"
    if phase == "plan" and isinstance(result, list):
        return f"{len(result)} step(s)"
    if isinstance(result, dict):
        return str(result.get("summary", result.get("written", "")))
    return str(result)[:120]


def _tool_result_summary(result: dict[str, Any]) -> str:
    if result.get("success"):
        if "result" in result:
            value = result["result"]
            if isinstance(value, list):
                return f"{len(value)} item(s)"
            return str(value)[:120]
        return "ok"
    return str(result.get("error", "failed"))[:120]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
