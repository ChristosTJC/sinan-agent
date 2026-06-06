"""Tests for REPL slash command registry and completion logic."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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


class _DistillClient:
    def __init__(self, proposals):
        self.model = "fake-distill"
        self.proposals = proposals

    def chat(self, prompt):
        return SimpleNamespace(content=json.dumps({"proposals": self.proposals}))


class _DistillSkillLoader:
    def __init__(self, skills_dir=None):
        self.skills_dir = skills_dir or Path("skills")
        self.reload_calls = []

    def load_all(self, reload=False):
        self.reload_calls.append(reload)
        return []


class _KnowledgeSink:
    def __init__(self):
        self.entries = []

    def add_entry(self, category, name, content):
        self.entries.append({"category": category, "name": name, "content": content})


def _minimal_distill_repl(proposals, knowledge_base=None, skill_loader=None):
    repl = object.__new__(SinanREPL)
    repl.messages = [
        {"role": "system", "content": "old prompt"},
        {"role": "user", "content": "帮我排查 I2C"},
        {"role": "assistant", "content": "先查上拉，再扫地址。"},
    ]
    repl.client = _DistillClient(proposals)
    repl.console = None
    repl._skill_loader = skill_loader if skill_loader is not None else _DistillSkillLoader()
    repl._knowledge_base = knowledge_base
    repl._distilled = False
    repl._build_system_prompt = lambda: "new prompt"
    return repl


def test_run_distillation_apply_all_writes_high_quality_skill(monkeypatch, tmp_path):
    monkeypatch.setenv("SINAN_HOME", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "a")

    repl = _minimal_distill_repl([
        {
            "type": "new_skill",
            "name": "i2c-debug-flow",
            "description": "用于 I2C 总线异常时复用的系统化排查流程，覆盖上拉、电平、地址扫描和验证。",
            "content": (
                "## 步骤\n"
                "1. 检查 SDA/SCL 是否有合适的上拉电阻\n"
                "2. 使用逻辑分析仪确认时钟和 ACK 波形\n"
                "3. 使用 i2cdetect 或等价工具扫描设备地址\n"
                "## 示例\n"
                "- i2cdetect -y 1\n"
            ),
            "reason": "排查流程可复用",
        }
    ])

    summary = repl._run_distillation()

    skill_file = tmp_path / "skills" / "i2c-debug-flow" / "SKILL.md"
    assert skill_file.is_file()
    assert "source: distilled" in skill_file.read_text()
    assert "已应用 1" in summary
    assert repl.messages[0]["content"] == "new prompt"
    assert True in repl._skill_loader.reload_calls


def test_run_distillation_apply_all_skips_low_quality_skill_but_writes_knowledge(monkeypatch, tmp_path):
    monkeypatch.setenv("SINAN_HOME", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "a")
    knowledge = _KnowledgeSink()

    repl = _minimal_distill_repl([
        {
            "type": "new_skill",
            "name": "bad-skill",
            "description": "差",
            "content": "",
            "reason": "x",
        },
        {
            "type": "new_knowledge",
            "category": "tips",
            "title": "MPU6050 地址",
            "content": "AD0=0 时地址为 0x68",
            "reason": "知识条目",
        },
    ], knowledge_base=knowledge)

    summary = repl._run_distillation()

    assert not (tmp_path / "skills" / "bad-skill").exists()
    assert knowledge.entries == [
        {"category": "tips", "name": "MPU6050 地址", "content": "AD0=0 时地址为 0x68"}
    ]
    assert "已应用 1" in summary
    assert "跳过 1" in summary


def test_run_distillation_manual_confirm_overrides_low_quality_skill(monkeypatch, tmp_path):
    monkeypatch.setenv("SINAN_HOME", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

    repl = _minimal_distill_repl([
        {
            "type": "new_skill",
            "name": "manual-low-quality",
            "description": "差",
            "content": "",
            "reason": "x",
        }
    ])

    summary = repl._run_distillation()

    assert (tmp_path / "skills" / "manual-low-quality" / "SKILL.md").is_file()
    assert "已应用 1" in summary


def test_run_distillation_applies_update_skill_type(monkeypatch, tmp_path):
    monkeypatch.setenv("SINAN_HOME", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

    existing = tmp_path / "skills" / "existing-skill"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text(
        "---\nname: existing-skill\ndescription: 已有技能\n---\n\n## 步骤\n1. 原步骤\n",
        encoding="utf-8",
    )

    repl = _minimal_distill_repl([
        {
            "type": "update_skill",
            "name": "existing-skill",
            "section": "注意事项",
            "description": "给已有技能补充注意事项",
            "content": "补充 I2C 上拉阻值和线长检查。",
            "reason": "已有技能可增强",
        }
    ])

    summary = repl._run_distillation()

    content = (existing / "SKILL.md").read_text(encoding="utf-8")
    assert "## 注意事项" in content
    assert "补充 I2C 上拉阻值和线长检查。" in content
    assert "已应用 1" in summary


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
