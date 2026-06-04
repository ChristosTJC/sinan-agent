"""Tests for REPL slash command registry and completion logic."""

from __future__ import annotations

from prompt_toolkit.document import Document

from agent.llm.client import LLMResponse
from agent.repl.commands import CommandRegistry, SlashCommand, SlashCompleter, build_default_commands
from agent.repl.repl import SinanREPL


def test_command_registry_registers_aliases_and_executes_handler():
    registry = CommandRegistry()
    registry.register(SlashCommand("hello", "say hello", aliases=["hi"], handler=lambda args: f"hello {args}"))

    assert registry.get("/hi").name == "hello"
    assert registry.execute("/hello world") == "hello world"
    assert registry.execute("/missing") is None


def test_command_registry_catches_handler_exceptions():
    registry = CommandRegistry()

    def boom(_args):
        raise RuntimeError("boom")

    registry.register(SlashCommand("boom", "explode", handler=boom))

    assert registry.execute("/boom") == "命令执行出错: boom"


def test_command_registry_hides_hidden_commands_from_names_and_visible_list():
    registry = CommandRegistry()
    registry.register(SlashCommand("visible", "shown", aliases=["v"]))
    registry.register(SlashCommand("secret", "hidden", hidden=True))

    assert [cmd.name for cmd in registry.list_visible()] == ["visible"]
    assert registry.names() == ["/v", "/visible"]


def test_slash_completer_only_completes_slash_commands():
    registry = CommandRegistry()
    registry.register(SlashCommand("tools", "list tools", aliases=["t"]))
    completer = SlashCompleter(registry)

    completions = list(completer.get_completions(Document("/to"), None))
    assert [completion.text for completion in completions] == ["/tools"]
    assert list(completer.get_completions(Document("plain text"), None)) == []


def test_default_commands_include_help_settings_and_quit():
    registry = build_default_commands()

    names = registry.names()
    assert "/help" in names
    assert "/settings" in names
    assert "/quit" not in names
    assert registry.execute("/quit") == "__QUIT__"


def test_default_help_command_lists_visible_commands():
    registry = build_default_commands()

    output = registry.execute("/help")

    assert "/help" in output
    assert "/tools" in output
    assert "/quit" not in output


def _minimal_repl() -> SinanREPL:
    repl = object.__new__(SinanREPL)
    repl.messages = [{"role": "system", "content": "old"}]
    repl._model_ref = ["old-model"]
    repl._provider_ref = ["old-provider"]
    repl._thinking_ref = ["off"]
    repl._build_system_prompt = lambda: "new prompt"
    return repl


class _FakeClient:
    def __init__(self, model: str) -> None:
        self.model = model

    def chat(self, messages, tools=None):
        return LLMResponse(content="ok", model=self.model)

    def chat_stream(self, messages, tools=None):
        yield from ()


def test_switch_model_uses_configured_provider_for_catalog_model(monkeypatch):
    repl = _minimal_repl()
    calls = []

    monkeypatch.setattr("agent.repl.repl.apply_settings", lambda: {})
    monkeypatch.setattr(
        "agent.repl.repl.get_model_config",
        lambda _settings: {
            "params": {"max_tokens": 4096, "temperature": None, "thinking": None},
            "availableModels": [
                {"label": "DeepSeek V4 Pro", "model": "deepseek-v4-pro", "provider": "claude"}
            ],
        },
    )

    def fake_create_client(provider, model, params=None):
        calls.append((provider, model, params))
        return _FakeClient(model)

    monkeypatch.setattr("agent.repl.repl.create_client", fake_create_client)

    output = repl._switch_model("deepseek-v4-pro", "high")

    assert "已切换" in output
    assert calls[0][0] == "claude"
    assert calls[0][1] == "deepseek-v4-pro"


def test_switch_model_uses_anthropic_thinking_for_claude_provider(monkeypatch):
    repl = _minimal_repl()
    calls = []

    monkeypatch.setattr("agent.repl.repl.apply_settings", lambda: {})
    monkeypatch.setattr(
        "agent.repl.repl.get_model_config",
        lambda _settings: {
            "params": {"max_tokens": 4096, "temperature": None, "thinking": None},
            "availableModels": [
                {"label": "DeepSeek V4 Pro", "model": "deepseek-v4-pro", "provider": "claude"}
            ],
        },
    )

    def fake_create_client(provider, model, params=None):
        calls.append((provider, model, params))
        return _FakeClient(model)

    monkeypatch.setattr("agent.repl.repl.create_client", fake_create_client)

    repl._switch_model("deepseek-v4-pro", "high")

    params = calls[0][2]
    assert params["thinking"] == {"type": "enabled", "budget_tokens": 16000}
    assert "reasoning_effort" not in params
