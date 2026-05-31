"""
测试 Pydantic 配置模型和加载器。
"""

import json
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.config.loader import ConfigLoader
from agent.config.models import (
    ContextConfig,
    MemoryConfig,
    ModelConfig,
    SinanSettings,
    TaskConfig,
    ThinkingConfig,
    ToolsConfig,
)


# ---------------------------------------------------------------------------
# ThinkingConfig
# ---------------------------------------------------------------------------


class TestThinkingConfig:
    """测试思考配置。"""

    def test_default_disabled(self):
        config = ThinkingConfig()
        assert config.type == "disabled"
        assert config.budget_tokens is None

    def test_enabled_with_budget(self):
        config = ThinkingConfig(type="enabled", budget_tokens=5000)
        assert config.type == "enabled"
        assert config.budget_tokens == 5000

    def test_budget_out_of_range(self):
        with pytest.raises(ValidationError):
            ThinkingConfig(type="enabled", budget_tokens=500)  # < 1000


# ---------------------------------------------------------------------------
# ModelConfig
# ---------------------------------------------------------------------------


class TestModelConfig:
    """测试模型配置。"""

    def test_model_config_valid(self):
        config = ModelConfig(
            label="Claude Opus",
            model="claude-opus-4-8",
            provider="claude",
            api_key="sk-ant-test123",
        )
        assert config.label == "Claude Opus"
        assert config.provider == "claude"

    def test_model_config_invalid_api_key_claude(self):
        with pytest.raises(ValidationError, match="Claude API Key 必须以 'sk-ant-' 开头"):
            ModelConfig(
                label="Claude",
                model="claude-3",
                provider="claude",
                api_key="invalid-key",
            )

    def test_model_config_invalid_api_key_openai(self):
        with pytest.raises(ValidationError, match="OpenAI API Key 必须以 'sk-' 开头"):
            ModelConfig(
                label="GPT-4",
                model="gpt-4",
                provider="openai",
                api_key="invalid-key",
            )

    def test_model_config_no_api_key(self):
        config = ModelConfig(
            label="Ollama",
            model="qwen2.5:7b",
            provider="ollama",
        )
        assert config.api_key is None


# ---------------------------------------------------------------------------
# ToolsConfig
# ---------------------------------------------------------------------------


class TestToolsConfig:
    """测试工具配置。"""

    def test_default_values(self):
        config = ToolsConfig()
        assert config.enabled == []
        assert config.disabled == []
        assert config.danger_confirm is True
        assert config.timeout_seconds == 30

    def test_custom_values(self):
        config = ToolsConfig(
            enabled=["serial", "flash"],
            disabled=["usb"],
            danger_confirm=False,
            timeout_seconds=60,
        )
        assert config.enabled == ["serial", "flash"]
        assert config.timeout_seconds == 60


# ---------------------------------------------------------------------------
# ContextConfig
# ---------------------------------------------------------------------------


class TestContextConfig:
    """测试上下文配置。"""

    def test_default_values(self):
        config = ContextConfig()
        assert config.max_tokens == 100000
        assert config.compaction_threshold == 0.8
        assert config.preserve_recent_turns == 5

    def test_custom_values(self):
        config = ContextConfig(
            max_tokens=150000,
            compaction_threshold=0.9,
            preserve_recent_turns=10,
        )
        assert config.max_tokens == 150000
        assert config.compaction_threshold == 0.9


# ---------------------------------------------------------------------------
# MemoryConfig
# ---------------------------------------------------------------------------


class TestMemoryConfig:
    """测试记忆配置。"""

    def test_default_values(self):
        config = MemoryConfig()
        assert config.l1_core_dir == "~/.sinan/memories"
        assert config.auto_save is True
        assert config.max_session_age_days == 30


# ---------------------------------------------------------------------------
# TaskConfig
# ---------------------------------------------------------------------------


class TestTaskConfig:
    """测试任务配置。"""

    def test_default_values(self):
        config = TaskConfig()
        assert config.max_parallel == 3
        assert config.default_timeout_minutes == 30
        assert config.retry_on_failure is True
        assert config.max_retries == 2


# ---------------------------------------------------------------------------
# SinanSettings
# ---------------------------------------------------------------------------


class TestSinanSettings:
    """测试完整配置。"""

    def test_sinan_settings_valid(self):
        settings = SinanSettings(
            available_models=[
                ModelConfig(
                    label="Qwen",
                    model="qwen2.5:7b",
                    provider="ollama",
                ),
            ],
            default_model="qwen2.5:7b",
        )
        assert len(settings.available_models) == 1
        assert settings.default_model == "qwen2.5:7b"

    def test_sinan_settings_no_models(self):
        with pytest.raises(ValidationError, match="at least 1 item"):
            SinanSettings(
                available_models=[],
                default_model="test",
            )

    def test_sinan_settings_invalid_default_model(self):
        with pytest.raises(ValidationError, match="不在 available_models 中"):
            SinanSettings(
                available_models=[
                    ModelConfig(
                        label="Qwen",
                        model="qwen2.5:7b",
                        provider="ollama",
                    ),
                ],
                default_model="nonexistent",
            )

    def test_get_model_default(self):
        settings = SinanSettings(
            available_models=[
                ModelConfig(label="A", model="model-a", provider="ollama"),
                ModelConfig(label="B", model="model-b", provider="ollama"),
            ],
            default_model="model-a",
        )
        model = settings.get_model()
        assert model.model == "model-a"

    def test_get_model_by_name(self):
        settings = SinanSettings(
            available_models=[
                ModelConfig(label="A", model="model-a", provider="ollama"),
                ModelConfig(label="B", model="model-b", provider="ollama"),
            ],
            default_model="model-a",
        )
        model = settings.get_model("model-b")
        assert model.model == "model-b"

    def test_get_model_not_found(self):
        settings = SinanSettings(
            available_models=[
                ModelConfig(label="A", model="model-a", provider="ollama"),
            ],
            default_model="model-a",
        )
        with pytest.raises(ValueError, match="未找到"):
            settings.get_model("nonexistent")

    def test_to_dict(self):
        settings = SinanSettings(
            available_models=[
                ModelConfig(label="Test", model="test-model", provider="ollama"),
            ],
            default_model="test-model",
            max_tokens=8192,
        )
        data = settings.to_dict()
        assert data["default_model"] == "test-model"
        assert data["max_tokens"] == 8192
        assert "available_models" in data


# ---------------------------------------------------------------------------
# ConfigLoader
# ---------------------------------------------------------------------------


class TestConfigLoader:
    """测试配置加载器。"""

    def test_config_loader_load_valid(self):
        config_data = {
            "available_models": [
                {
                    "label": "Qwen",
                    "model": "qwen2.5:7b",
                    "provider": "ollama",
                }
            ],
            "default_model": "qwen2.5:7b",
            "max_tokens": 4096,
            "temperature": 0.7,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            path = Path(f.name)

        try:
            settings = ConfigLoader.load(path)
            assert settings.default_model == "qwen2.5:7b"
            assert settings.max_tokens == 4096
            assert len(settings.available_models) == 1
        finally:
            path.unlink()

    def test_config_loader_invalid_file(self):
        with pytest.raises(FileNotFoundError):
            ConfigLoader.load(Path("/nonexistent/config.json"))

    def test_config_loader_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(json.JSONDecodeError):
                ConfigLoader.load(path)
        finally:
            path.unlink()

    def test_config_loader_invalid_schema(self):
        config_data = {
            "available_models": [],  # 至少需要 1 个
            "default_model": "test",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ValidationError):
                ConfigLoader.load(path)
        finally:
            path.unlink()

    def test_config_loader_validate(self):
        config_data = {
            "available_models": [
                {"label": "Test", "model": "test-model", "provider": "ollama"}
            ],
            "default_model": "test-model",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            path = Path(f.name)

        try:
            valid, error = ConfigLoader.validate(path)
            assert valid is True
            assert error is None
        finally:
            path.unlink()

    def test_config_loader_validate_invalid(self):
        path = Path("/nonexistent/config.json")
        valid, error = ConfigLoader.validate(path)
        assert valid is False
        assert "文件不存在" in error

    def test_config_loader_save(self):
        settings = SinanSettings(
            available_models=[
                ModelConfig(label="Test", model="test-model", provider="ollama")
            ],
            default_model="test-model",
            max_tokens=8192,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            ConfigLoader.save(settings, path)

            assert path.exists()
            loaded = ConfigLoader.load(path)
            assert loaded.default_model == "test-model"
            assert loaded.max_tokens == 8192

