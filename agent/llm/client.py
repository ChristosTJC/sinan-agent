"""
司南 LLM 客户端 —— 统一多模型后端抽象。

支持三种后端:
- Claude (Anthropic)  — 需要 ANTHROPIC_API_KEY
- OpenAI              — 需要 OPENAI_API_KEY
- Ollama (本地)       — 无需 API Key，默认 http://localhost:11434

消息格式统一采用 OpenAI 风格:
    {"role": "system"|"user"|"assistant"|"tool", "content": "..."}
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """LLM 返回的工具调用请求。"""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """LLM 完整响应。"""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class StreamChunk:
    """流式输出块。"""
    type: str = "text"          # "text" | "tool_call" | "done"
    content: str = ""
    tool_call: Optional[ToolCall] = None


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------


class LLMClient(ABC):
    """LLM 客户端抽象基类。"""

    def __init__(self, model: str, params: Optional[dict[str, Any]] = None, **kwargs: Any) -> None:
        self.model = model
        self.params = params or {}
        self.kwargs = kwargs

    @abstractmethod
    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse:
        """发送聊天请求并返回完整响应。"""
        ...

    @abstractmethod
    def chat_stream(self, messages: list[dict], tools: Optional[list[dict]] = None) -> Iterator[StreamChunk]:
        """发送聊天请求并以流式方式返回响应块。"""
        ...

    def provider_name(self) -> str:
        return self.__class__.__name__.replace("Client", "")


# ---------------------------------------------------------------------------
# Claude (Anthropic) 客户端
# ---------------------------------------------------------------------------


class ClaudeClient(LLMClient):
    """Anthropic Claude 客户端。"""

    # 支持扩展思考的模型前缀 (Claude 3.7+ / 4.x / DeepSeek V4)
    _THINKING_MODEL_PREFIXES = ("claude-3-7-sonnet", "claude-sonnet-4", "claude-opus-4", "deepseek-v4")

    def __init__(self, model: str = "claude-sonnet-4-20250514", params: Optional[dict[str, Any]] = None, **kwargs: Any) -> None:
        super().__init__(model=model, params=params, **kwargs)
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    def _build_headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _to_claude_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """转换为 Claude 格式: system 单独提取, tool results 转换。"""
        system = ""
        claude_msgs: list[dict] = []

        for msg in messages:
            role = msg.get("role", "")
            if role == "system":
                system = msg.get("content", "")
            elif role == "tool":
                # OpenAI tool result -> Claude tool_result
                claude_msgs.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
            elif role == "assistant" and msg.get("tool_calls"):
                # 带 tool_calls 的 assistant 消息
                content: list[dict] = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    content.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc.get("function", {}).get("name", ""),
                        "input": json.loads(tc["function"]["arguments"])
                        if isinstance(tc.get("function", {}).get("arguments"), str)
                        else tc.get("function", {}).get("arguments", {}),
                    })
                claude_msgs.append({"role": "assistant", "content": content})
            else:
                claude_msgs.append({"role": role, "content": msg.get("content", "")})

        return system, claude_msgs

    def _to_claude_tools(self, tools: Optional[list[dict]]) -> Optional[list[dict]]:
        if not tools:
            return None
        return [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]

    def _supports_thinking(self) -> bool:
        """检查当前模型是否支持扩展思考。"""
        model_lower = self.model.lower()
        return any(model_lower.startswith(p) for p in self._THINKING_MODEL_PREFIXES)

    def _build_body(self, stream: bool = False) -> dict[str, Any]:
        """构建 Claude API 请求体，注入 params 配置。"""
        max_tokens = self.params.get("max_tokens") or 4096
        body: dict[str, Any] = {
            "model": self.model,
        }
        # stream 仅在流式请求时加入 body (Anthropic 规范: 非流式不含 stream 字段)
        if stream:
            body["stream"] = True
        # temperature (仅在不启用 thinking 时生效)
        temp = self.params.get("temperature")
        if temp is not None and not self._thinking_enabled():
            body["temperature"] = temp
        # 扩展思考
        if self._thinking_enabled():
            thinking_budget = self.params.get("thinking")
            if isinstance(thinking_budget, dict):
                budget = thinking_budget.get("budget_tokens", 10000)
                body["thinking"] = thinking_budget
            else:
                budget = int(thinking_budget) if thinking_budget else 10000
                body["thinking"] = {"type": "enabled", "budget_tokens": budget}
            # Anthropic 要求 max_tokens > budget_tokens (max_tokens 含思考+输出)
            # 自动确保 max_tokens 足够大
            output_reserve = 4096  # 输出预留
            required_max_tokens = budget + output_reserve
            max_tokens = max(max_tokens, required_max_tokens)
        body["max_tokens"] = max_tokens
        return body

    def _thinking_enabled(self) -> bool:
        """是否启用扩展思考。"""
        return self._supports_thinking() and self.params.get("thinking") is not None

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse:
        system, claude_msgs = self._to_claude_messages(messages)
        body = self._build_body(stream=False)
        body["messages"] = claude_msgs
        if system:
            body["system"] = system
        claude_tools = self._to_claude_tools(tools)
        if claude_tools:
            body["tools"] = claude_tools

        resp = httpx.post(
            f"{self.base_url}/v1/messages",
            headers=self._build_headers(),
            json=body,
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()

        content = ""
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block["type"] == "text":
                content += block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append(ToolCall(
                    id=block["id"],
                    name=block["name"],
                    arguments=block.get("input", {}),
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=data.get("model", self.model),
            usage=data.get("usage", {}),
        )

    def chat_stream(self, messages: list[dict], tools: Optional[list[dict]] = None) -> Iterator[StreamChunk]:
        system, claude_msgs = self._to_claude_messages(messages)
        body = self._build_body(stream=True)
        body["messages"] = claude_msgs
        if system:
            body["system"] = system
        claude_tools = self._to_claude_tools(tools)
        if claude_tools:
            body["tools"] = claude_tools

        with httpx.stream(
            "POST",
            f"{self.base_url}/v1/messages",
            headers=self._build_headers(),
            json=body,
            timeout=120.0,
        ) as resp:
            resp.raise_for_status()
            tool_id = ""
            tool_name = ""
            tool_args_buf = ""

            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                line = line[6:].strip()
                if not line or line == "[DONE]":
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = evt.get("type", "")
                if etype == "content_block_start":
                    block = evt.get("content_block", {})
                    if block.get("type") == "tool_use":
                        tool_id = block.get("id", "")
                        tool_name = block.get("name", "")
                        tool_args_buf = ""
                elif etype == "content_block_delta":
                    delta = evt.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield StreamChunk(type="text", content=delta.get("text", ""))
                    elif delta.get("type") == "input_json_delta":
                        tool_args_buf += delta.get("partial_json", "")
                elif etype == "content_block_stop":
                    if tool_name:
                        try:
                            args = json.loads(tool_args_buf) if tool_args_buf else {}
                        except json.JSONDecodeError:
                            args = {}
                        yield StreamChunk(
                            type="tool_call",
                            tool_call=ToolCall(id=tool_id, name=tool_name, arguments=args),
                        )
                        tool_id = ""
                        tool_name = ""
                        tool_args_buf = ""
                elif etype == "message_stop":
                    yield StreamChunk(type="done")


# ---------------------------------------------------------------------------
# OpenAI 兼容基类 (流式处理 + 非流式 共享逻辑)
# ---------------------------------------------------------------------------


class BaseOpenAICompatibleClient(LLMClient):
    """OpenAI 兼容 API 的共享基类。

    提取 OpenAIClient / OllamaClient / GenericOpenAIClient 的共同逻辑:
    - SSE 流式解析循环
    - tool_call 分片收集
    - 文本流式输出
    - done 信号处理
    - 非流式 chat() 响应解析

    子类只需实现:
    - _build_headers(): 构建请求头
    - _get_endpoint(): 返回 API 端点 URL
    - _build_chat_body() 已提供默认实现, 子类可覆盖
    """

    @abstractmethod
    def _build_headers(self) -> dict:
        """构建 HTTP 请求头。"""
        ...

    @abstractmethod
    def _get_endpoint(self) -> str:
        """获取 API 端点 URL。"""
        ...

    def _supports_reasoning_effort(self) -> bool:
        """检查模型是否支持 reasoning_effort。

        OpenAI o 系列和 DeepSeek V4 均支持推理强度控制。
        """
        model_lower = self.model.lower()
        if model_lower.startswith(("o1", "o3", "o4")):
            return True
        if "deepseek" in model_lower and ("v4" in model_lower or "reasoner" in model_lower):
            return True
        return False

    def _build_chat_body(
        self, messages: list[dict], tools: Optional[list[dict]], stream: bool
    ) -> dict[str, Any]:
        """构建聊天请求体，注入 params 配置。"""
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": stream}
        if tools:
            body["tools"] = tools
        # max_tokens
        max_tokens = self.params.get("max_tokens")
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        # temperature (推理模型不支持，避免 API 报错)
        temp = self.params.get("temperature")
        if temp is not None and not self._supports_reasoning_effort():
            body["temperature"] = temp
        # reasoning_effort — 推理强度控制
        effort = self.params.get("reasoning_effort")
        if effort is not None:
            effort_map = {1: "low", 2: "medium", 3: "high"}
            if isinstance(effort, int):
                effort = effort_map.get(effort, "medium")
            body["reasoning_effort"] = effort
        return body

    # ---- 非流式 chat (共享) ----

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse:
        body = self._build_chat_body(messages, tools, stream=False)

        resp = httpx.post(
            self._get_endpoint(),
            headers=self._build_headers(),
            json=body,
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]["message"]

        tool_calls: list[ToolCall] = []
        for tc in choice.get("tool_calls") or []:
            args = tc["function"]["arguments"]
            tool_calls.append(ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=json.loads(args) if isinstance(args, str) else args,
            ))

        return LLMResponse(
            content=choice.get("content") or "",
            tool_calls=tool_calls,
            model=data.get("model", self.model),
            usage=data.get("usage", {}),
        )

    # ---- 流式 chat_stream (共享 SSE 解析) ----

    def chat_stream(self, messages: list[dict], tools: Optional[list[dict]] = None) -> Iterator[StreamChunk]:
        yield from self._stream_sse(messages, tools)

    def _stream_sse(
        self, messages: list[dict], tools: Optional[list[dict]] = None
    ) -> Iterator[StreamChunk]:
        """通用 SSE 流式处理逻辑。

        解析 Server-Sent Events, 提取文本和工具调用分片。
        """
        body = self._build_chat_body(messages, tools, stream=True)
        headers = self._build_headers()
        endpoint = self._get_endpoint()

        with httpx.stream(
            "POST",
            endpoint,
            headers=headers,
            json=body,
            timeout=120.0,
        ) as resp:
            resp.raise_for_status()
            tc_buf: dict[int, dict] = {}

            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                line = line[6:].strip()
                if not line or line == "[DONE]":
                    if tc_buf:
                        for _, tc in sorted(tc_buf.items()):
                            try:
                                args = json.loads(tc["args_buf"]) if tc["args_buf"] else {}
                            except json.JSONDecodeError:
                                args = {}
                            yield StreamChunk(
                                type="tool_call",
                                tool_call=ToolCall(id=tc["id"], name=tc["name"], arguments=args),
                            )
                    yield StreamChunk(type="done")
                    return

                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue

                delta = evt["choices"][0].get("delta", {})

                if delta.get("content"):
                    yield StreamChunk(type="text", content=delta["content"])

                for tc in delta.get("tool_calls") or []:
                    idx = tc["index"]
                    if idx not in tc_buf:
                        tc_buf[idx] = {
                            "id": tc.get("id", ""),
                            "name": tc.get("function", {}).get("name", ""),
                            "args_buf": "",
                        }
                    if tc.get("id"):
                        tc_buf[idx]["id"] = tc["id"]
                    if tc.get("function", {}).get("name"):
                        tc_buf[idx]["name"] = tc["function"]["name"]
                    if tc.get("function", {}).get("arguments"):
                        tc_buf[idx]["args_buf"] += tc["function"]["arguments"]


# ---------------------------------------------------------------------------
# OpenAI 客户端
# ---------------------------------------------------------------------------


class OpenAIClient(BaseOpenAICompatibleClient):
    """OpenAI API 客户端。"""

    def __init__(self, model: str = "gpt-4o", params: Optional[dict[str, Any]] = None, **kwargs: Any) -> None:
        super().__init__(model=model, params=params, **kwargs)
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get_endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"


# ---------------------------------------------------------------------------
# Ollama 客户端
# ---------------------------------------------------------------------------


class OllamaClient(BaseOpenAICompatibleClient):
    """Ollama 本地模型客户端 (通过兼容 OpenAI 的 API)。"""

    def __init__(self, model: str = "qwen2.5:7b", params: Optional[dict[str, Any]] = None, **kwargs: Any) -> None:
        super().__init__(model=model, params=params, **kwargs)
        self.base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.api_key = os.environ.get("OLLAMA_API_KEY", "ollama")

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get_endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"


# ---------------------------------------------------------------------------
# 通用 OpenAI 兼容客户端 (支持第三方 API)
# ---------------------------------------------------------------------------


class GenericOpenAIClient(BaseOpenAICompatibleClient):
    """通用 OpenAI 兼容 API 客户端。

    支持任何兼容 OpenAI 格式的第三方模型服务:
    - Groq (groq.com)
    - DeepSeek (deepseek.com)
    - 智谱 AI (zhipuai.cn)
    - Moonshot (moonshot.cn)
    - 硅基流动 (siliconflow.cn)
    - 自定义私有部署
    """

    def __init__(
        self,
        model: str,
        api_key: str = "",
        base_url: str = "",
        params: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, params=params, **kwargs)
        self.api_key = api_key or os.environ.get("GENERIC_API_KEY", "")
        self.base_url = base_url or os.environ.get("GENERIC_BASE_URL", "")

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"


def detect_provider() -> str:
    """根据环境变量自动检测可用的 LLM 后端。

    优先级: ANTHROPIC_API_KEY > OPENAI_API_KEY > GENERIC_API_KEY > Ollama (fallback)
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GENERIC_API_KEY"):
        return "generic"
    return "ollama"


def create_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    params: Optional[dict[str, Any]] = None,
) -> LLMClient:
    """创建 LLM 客户端实例。

    Args:
        provider: 后端名称。
                  支持的 provider:
                  - claude / anthropic: Anthropic Claude
                  - openai: OpenAI API (也兼容 Azure、OneAPI 等)
                  - ollama: Ollama 本地 (通过 v1 兼容 API)
                  - generic / groq / deepseek / zhipu / moonshot / siliconflow:
                    通用 OpenAI 兼容接口
        model: 模型名称。为 None 时使用各后端默认模型。
        params: 模型参数 (max_tokens, temperature, thinking 等)。

    Returns:
        LLMClient 实例。
    """
    if provider is None:
        provider = detect_provider()

    provider = provider.lower().strip()

    # 通用 OpenAI 兼容接口的 provider 别名
    generic_providers = {
        "generic", "groq", "deepseek", "zhipu", "zhipuai",
        "moonshot", "siliconflow", "silicon", "aliyun", "bailian",
    }

    clients = {
        "claude": ClaudeClient,
        "anthropic": ClaudeClient,
        "openai": OpenAIClient,
        "ollama": OllamaClient,
    }

    # 检查是否为通用兼容接口
    if provider in generic_providers:
        if not model:
            raise ValueError(f"通用接口必须指定 model 参数")
        # 从模型名推断 base_url (如果未设置环境变量)
        base_url = os.environ.get("GENERIC_BASE_URL", "")
        api_key = os.environ.get("GENERIC_API_KEY", "")

        # 常见服务的默认 base_url
        if not base_url:
            if provider == "groq" or "llama" in model.lower() or "mixtral" in model.lower():
                base_url = "https://api.groq.com/openai/v1"
            elif provider == "deepseek":
                base_url = "https://api.deepseek.com/v1"
            elif provider in ("zhipu", "zhipuai"):
                base_url = "https://open.bigmodel.cn/api/paas/v4"
            elif provider == "moonshot":
                base_url = "https://api.moonshot.cn/v1"
            elif provider in ("siliconflow", "silicon"):
                base_url = "https://api.siliconflow.cn/v1"

        return GenericOpenAIClient(model=model, api_key=api_key, base_url=base_url, params=params)

    cls = clients.get(provider)
    if cls is None:
        raise ValueError(
            f"不支持的 LLM 后端: {provider}。\n"
            f"支持的 provider: claude, openai, ollama, generic, groq, deepseek, zhipu, moonshot, siliconflow"
        )

    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model
    if params:
        kwargs["params"] = params

    return cls(**kwargs)
