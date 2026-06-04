"""AgentSession：UI 无关的 agentic loop 内核。

一个 turn = 给定用户输入，驱动 LLM↔工具循环，直到 LLM 不再请求工具或达深度上限。
流式/非流式差异由 Renderer 吸收；危险确认由 ApprovalPolicy 决定；
工具执行统一委托 tool_bridge；事件经 Renderer.on_event 发出。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from agent.core.approval import ApprovalPolicy
from agent.core.renderer import Renderer
from agent.llm.client import LLMResponse, ToolCall
from agent.orchestration.events import (
    ToolStartEvent, ToolDoneEvent, ToolErrorEvent, ApprovalRequiredEvent, ApprovalDeniedEvent,
)
from agent.repl.tool_bridge import (
    build_tool_call_message, execute_all_tool_calls, tools_to_openai_format,
)
from agent.tools import DangerLevel

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    final_text: str = ""
    tool_calls_made: int = 0
    depth_reached: int = 0
    hit_depth_limit: bool = False
    success: bool = True
    tool_results: list[dict] = field(default_factory=list)
    rejected_tools: list[str] = field(default_factory=list)


class AgentSession:
    def __init__(
        self,
        client,
        registry,
        *,
        system_prompt: str,
        approval: ApprovalPolicy,
        renderer: Renderer,
        context_provider=None,
        max_tool_depth: int = 25,
        stream: bool = True,
        messages: list[dict] | None = None,
    ) -> None:
        self._client = client
        self._registry = registry
        self._approval = approval
        self._renderer = renderer
        self._context_provider = context_provider
        self._max_tool_depth = max_tool_depth
        self._stream = stream
        # messages 可由调用方注入以共享同一历史对象（REPL：蒸馏/compact/换模型共用）；
        # 传入则原地复用并确保 system 在首位，否则自建。
        if messages is not None:
            self._messages = messages
            if not self._messages or self._messages[0].get("role") != "system":
                self._messages.insert(0, {"role": "system", "content": system_prompt})
        else:
            self._messages: list[dict] = [{"role": "system", "content": system_prompt}]
        self._openai_tools = tools_to_openai_format(registry.list_tools())

    @property
    def messages(self) -> list[dict]:
        return self._messages

    def send(self, user_input: str) -> TurnResult:
        if self._context_provider is not None:
            ctx = self._context_provider.provide(user_input)
            if ctx:
                self._messages.append({"role": "system", "content": ctx})
        self._messages.append({"role": "user", "content": user_input})

        result = TurnResult()
        depth = 0
        while depth < self._max_tool_depth:
            resp = self._run_turn()
            if not resp.tool_calls:
                self._messages.append({"role": "assistant", "content": resp.content or ""})
                result.final_text = resp.content or ""
                result.depth_reached = depth
                result.success = True
                return result

            depth += 1
            result.tool_calls_made += len(resp.tool_calls)
            self._messages.append(build_tool_call_message(resp.content, resp.tool_calls))

            for tc in resp.tool_calls:
                level = self._level_str(tc.name)
                self._renderer.on_event(ToolStartEvent(
                    tool_name=tc.name, danger_level=level, arguments=tc.arguments,
                ))
                # 危险工具：执行前补发 approval_required，保持与现有 REPL 事件序列一致
                if self._registry.is_dangerous(tc.name):
                    self._renderer.on_event(ApprovalRequiredEvent(
                        tool_name=tc.name, danger_level=level, arguments=tc.arguments,
                    ))

            tool_messages, records = execute_all_tool_calls(
                resp.tool_calls,
                self._registry,
                status_callback=self._renderer.on_tool_status,
                approval=self._approval.approve,
            )
            self._messages.extend(tool_messages)
            self._emit_records(records, result)

        result.hit_depth_limit = True
        result.depth_reached = depth
        result.success = False
        result.final_text = (
            f"工具调用轮次已达上限 ({self._max_tool_depth})，已终止。"
        )
        logger.warning("工具调用轮次达上限 %d，已终止本 turn", self._max_tool_depth)
        self._messages.append({"role": "assistant", "content": result.final_text})
        return result

    def _run_turn(self) -> LLMResponse:
        """执行一次 LLM 调用，统一返回 LLMResponse。流式时增量经 renderer 输出。"""
        if not self._stream or not hasattr(self._client, "chat_stream"):
            resp = self._client.chat(self._messages, tools=self._openai_tools)
            if resp.content:
                self._renderer.on_text_delta(resp.content)
            return resp
        return self._collect_stream()

    def _collect_stream(self) -> LLMResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for chunk in self._client.chat_stream(self._messages, tools=self._openai_tools):
            ctype = getattr(chunk, "type", None)
            if ctype == "text" and getattr(chunk, "content", None):
                content_parts.append(chunk.content)
                self._renderer.on_text_delta(chunk.content)
            elif ctype == "tool_call" and getattr(chunk, "tool_call", None):
                tool_calls.append(chunk.tool_call)
        return LLMResponse(content="".join(content_parts), tool_calls=tool_calls)

    def _emit_records(self, records: list[dict], result: TurnResult) -> None:
        for rec in records:
            result.tool_results.append(rec)
            if rec.get("rejected"):
                logger.info("工具 %s 审批被拒，未执行", rec["name"])
                result.rejected_tools.append(rec["name"])
                self._renderer.on_event(ApprovalDeniedEvent(tool_name=rec["name"]))
                continue
            if rec.get("success"):
                self._renderer.on_event(ToolDoneEvent(
                    tool_name=rec["name"],
                    danger_level=rec.get("danger_level", "safe"),
                    success=True,
                    duration_ms=rec.get("duration_ms", 0.0),
                    result_summary="ok",
                ))
            else:
                self._renderer.on_event(ToolErrorEvent(
                    tool_name=rec["name"], error=rec.get("error", ""),
                ))

    def _level_str(self, name: str) -> str:
        try:
            level = self._registry.get_danger_level(name)
            return level.value if isinstance(level, DangerLevel) else str(level)
        except Exception:  # noqa: BLE001
            return DangerLevel.SAFE.value
