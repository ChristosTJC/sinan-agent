"""
统一事件模型。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class EventType(str, Enum):
    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    STREAM_DONE = "stream_done"
    TOOL_START = "tool_start"
    TOOL_DONE = "tool_done"
    TOOL_ERROR = "tool_error"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    RUN_START = "run_start"
    RUN_DONE = "run_done"
    PHASE_START = "phase_start"
    PHASE_DONE = "phase_done"
    STEP_START = "step_start"
    STEP_DONE = "step_done"
    STEP_BLOCKED = "step_blocked"
    STEP_SKIPPED = "step_skipped"


def _now() -> float:
    return time.time()


@dataclass
class ToolStartEvent:
    tool_name: str
    danger_level: str
    arguments: dict[str, Any]
    type: str = field(init=False, default=EventType.TOOL_START.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class ToolDoneEvent:
    tool_name: str
    danger_level: str
    success: bool
    duration_ms: float
    result_summary: str
    type: str = field(init=False, default=EventType.TOOL_DONE.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class ToolErrorEvent:
    tool_name: str
    error: str
    type: str = field(init=False, default=EventType.TOOL_ERROR.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class ApprovalRequiredEvent:
    tool_name: str
    danger_level: str
    arguments: dict[str, Any]
    type: str = field(init=False, default=EventType.APPROVAL_REQUIRED.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class ApprovalGrantedEvent:
    tool_name: str
    type: str = field(init=False, default=EventType.APPROVAL_GRANTED.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class ApprovalDeniedEvent:
    tool_name: str
    type: str = field(init=False, default=EventType.APPROVAL_DENIED.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class RunStartEvent:
    goal: str
    run_id: str
    type: str = field(init=False, default=EventType.RUN_START.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class RunDoneEvent:
    run_id: str
    success: bool
    run_dir: str = ""
    type: str = field(init=False, default=EventType.RUN_DONE.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class PhaseStartEvent:
    phase: str
    label: str
    type: str = field(init=False, default=EventType.PHASE_START.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class PhaseDoneEvent:
    phase: str
    label: str
    summary: str = ""
    type: str = field(init=False, default=EventType.PHASE_DONE.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class StepStartEvent:
    step_id: Any
    action: str
    tool: Optional[str] = None
    danger_level: str = "safe"
    type: str = field(init=False, default=EventType.STEP_START.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class StepDoneEvent:
    step_id: Any
    action: str
    tool: Optional[str] = None
    success: bool = True
    summary: str = ""
    type: str = field(init=False, default=EventType.STEP_DONE.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class StepBlockedEvent:
    step_id: Any
    action: str
    tool: Optional[str] = None
    danger_level: str = "safe"
    reason: str = ""
    type: str = field(init=False, default=EventType.STEP_BLOCKED.value)
    timestamp: float = field(init=False, default_factory=_now)


@dataclass
class StepSkippedEvent:
    step_id: Any
    action: str
    tool: Optional[str] = None
    reason: str = ""
    type: str = field(init=False, default=EventType.STEP_SKIPPED.value)
    timestamp: float = field(init=False, default_factory=_now)


def sanitize_event_payload(obj: Any, key: str | None = None) -> Any:
    """Recursively redact event payloads before they are written to logs."""
    from agent.diagnostics import _is_sensitive_env_key, redact_text

    if key is not None and _is_sensitive_env_key(str(key)):
        return "[REDACTED]"
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: sanitize_event_payload(v, str(k)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_event_payload(v, key) for v in obj]
    return obj
