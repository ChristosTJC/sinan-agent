"""
llm/client.py 单元测试。

覆盖:
- 类继承关系验证
- create_client 工厂函数
- detect_provider 环境变量检测
- BaseOpenAICompatibleClient._build_chat_body 默认实现
"""

import os
from unittest import mock

import pytest

from agent.llm.client import (
    BaseOpenAICompatibleClient,
    ClaudeClient,
    GenericOpenAIClient,
    LLMClient,
    OllamaClient,
    OpenAIClient,
    create_client,
    detect_provider,
    normalize_proxy_environment,
)


# ---------------------------------------------------------------------------
# 继承关系
# ---------------------------------------------------------------------------


class TestInheritance:
    """验证客户端继承链。"""

    def test_openai_inherits_base(self):
        assert issubclass(OpenAIClient, BaseOpenAICompatibleClient)

    def test_ollama_inherits_base(self):
        assert issubclass(OllamaClient, BaseOpenAICompatibleClient)

    def test_generic_inherits_base(self):
        assert issubclass(GenericOpenAIClient, BaseOpenAICompatibleClient)

    def test_all_inherit_llm_client(self):
        assert issubclass(OpenAIClient, LLMClient)
        assert issubclass(OllamaClient, LLMClient)
        assert issubclass(GenericOpenAIClient, LLMClient)
        assert issubclass(ClaudeClient, LLMClient)

    def test_chat_from_base(self):
        """chat() 方法来自基类。"""
        assert OllamaClient.chat is BaseOpenAICompatibleClient.chat
        assert GenericOpenAIClient.chat is BaseOpenAICompatibleClient.chat

    def test_chat_stream_from_base(self):
        """chat_stream() 方法来自基类。"""
        assert OllamaClient.chat_stream is BaseOpenAICompatibleClient.chat_stream
        assert GenericOpenAIClient.chat_stream is BaseOpenAICompatibleClient.chat_stream


# ---------------------------------------------------------------------------
# 实例化
# ---------------------------------------------------------------------------


class TestInstantiation:
    def test_ollama_defaults(self):
        c = OllamaClient()
        assert c.model == "qwen2.5:7b"
        assert "localhost:11434" in c.base_url

    def test_ollama_endpoint(self):
        c = OllamaClient()
        assert c._get_endpoint().endswith("/chat/completions")

    def test_generic_requires_model(self):
        c = GenericOpenAIClient(model="test-model", base_url="http://x/v1")
        assert c.model == "test-model"
        assert c._get_endpoint() == "http://x/v1/chat/completions"

    def test_generic_headers_with_key(self):
        c = GenericOpenAIClient(model="m", api_key="sk-test", base_url="http://x")
        headers = c._build_headers()
        assert "Bearer sk-test" in headers.get("Authorization", "")

    def test_generic_headers_without_key(self):
        c = GenericOpenAIClient(model="m", base_url="http://x")
        headers = c._build_headers()
        assert "Authorization" not in headers

    def test_openai_defaults(self):
        c = OpenAIClient()
        assert c.model == "gpt-4o"


# ---------------------------------------------------------------------------
# _build_chat_body 默认实现
# ---------------------------------------------------------------------------


class TestBuildChatBody:
    def test_without_tools(self):
        c = OllamaClient()
        body = c._build_chat_body([{"role": "user", "content": "hi"}], None, stream=False)
        assert body["model"] == "qwen2.5:7b"
        assert body["stream"] is False
        assert "tools" not in body

    def test_with_tools(self):
        c = OllamaClient()
        tools = [{"type": "function", "function": {"name": "test"}}]
        body = c._build_chat_body([{"role": "user", "content": "hi"}], tools, stream=True)
        assert body["stream"] is True
        assert body["tools"] == tools


# ---------------------------------------------------------------------------
# Proxy environment normalization
# ---------------------------------------------------------------------------


class TestProxyNormalization:
    def test_socks_scheme_is_normalized_for_httpx(self):
        with mock.patch.dict(os.environ, {"ALL_PROXY": "socks://127.0.0.1:7897"}, clear=True):
            normalize_proxy_environment()
            assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:7897"

    def test_http_proxy_is_left_unchanged(self):
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:7897"}, clear=True):
            normalize_proxy_environment()
            assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"

    def test_loopback_https_proxy_is_normalized_to_plain_http_proxy(self):
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "https://127.0.0.1:7897/"}, clear=True):
            normalize_proxy_environment()
            assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897/"

    def test_remote_https_proxy_is_left_unchanged(self):
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "https://proxy.example.com:8443"}, clear=True):
            normalize_proxy_environment()
            assert os.environ["HTTPS_PROXY"] == "https://proxy.example.com:8443"


# ---------------------------------------------------------------------------
# detect_provider
# ---------------------------------------------------------------------------


class TestDetectProvider:
    def test_anthropic_first(self):
        env = {"ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "y"}
        with mock.patch.dict(os.environ, env, clear=False):
            assert detect_provider() == "claude"

    def test_openai_second(self):
        env = {"OPENAI_API_KEY": "x"}
        with mock.patch.dict(os.environ, env, clear=False):
            # 清除 ANTHROPIC_API_KEY
            os.environ.pop("ANTHROPIC_API_KEY", None)
            assert detect_provider() == "openai"

    def test_ollama_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_provider() == "ollama"


# ---------------------------------------------------------------------------
# create_client
# ---------------------------------------------------------------------------


class TestCreateClient:
    def test_create_ollama(self):
        c = create_client("ollama")
        assert isinstance(c, OllamaClient)

    def test_create_openai(self):
        c = create_client("openai")
        assert isinstance(c, OpenAIClient)

    def test_create_claude(self):
        c = create_client("claude")
        assert isinstance(c, ClaudeClient)

    def test_create_generic(self):
        c = create_client("generic", model="test-model")
        assert isinstance(c, GenericOpenAIClient)
        assert c.model == "test-model"

    def test_generic_requires_model(self):
        with pytest.raises(ValueError, match="必须指定 model"):
            create_client("generic")

    def test_invalid_provider(self):
        with pytest.raises(ValueError, match="不支持"):
            create_client("nonexistent")

    def test_provider_aliases(self):
        for alias in ("groq", "deepseek", "zhipu", "moonshot", "siliconflow"):
            c = create_client(alias, model="m")
            assert isinstance(c, GenericOpenAIClient)
