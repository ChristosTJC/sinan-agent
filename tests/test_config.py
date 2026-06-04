"""
config.py 单元测试。

覆盖:
- _deep_merge: 字典深度合并
- load_project_config: YAML 加载
- load_settings: 三级优先级合并
- get_model_config / get_tools_config: 配置提取
"""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from agent.config.legacy import (
    DEFAULT_SETTINGS,
    _deep_merge,
    _migrate_old_settings,
    get_model_config,
    get_tools_config,
    load_project_config,
    load_settings,
)


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    """测试 _deep_merge 深度合并。"""

    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"model": {"provider": "ollama", "name": "qwen"}}
        override = {"model": {"name": "llama3"}}
        result = _deep_merge(base, override)
        assert result == {"model": {"provider": "ollama", "name": "llama3"}}

    def test_deep_nested_merge(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"d": 3, "e": 4}}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": {"c": 1, "d": 3, "e": 4}}}

    def test_override_dict_with_scalar(self):
        base = {"a": {"b": 1}}
        override = {"a": "string"}
        result = _deep_merge(base, override)
        assert result == {"a": "string"}

    def test_empty_override(self):
        base = {"a": 1, "b": 2}
        result = _deep_merge(base, {})
        assert result == {"a": 1, "b": 2}

    def test_does_not_mutate_base(self):
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        _deep_merge(base, override)
        assert base == {"a": {"b": 1}}


# ---------------------------------------------------------------------------
# load_project_config
# ---------------------------------------------------------------------------


class TestLoadProjectConfig:
    """测试 load_project_config YAML 加载。"""

    def test_returns_dict_on_missing_file(self):
        with mock.patch("agent.config.legacy.PROJECT_CONFIG_FILE", Path("/nonexistent")):
            result = load_project_config()
            assert result == {}

    def test_loads_valid_yaml(self):
        yaml_content = "model:\n  provider: test\n  name: test-model\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            with mock.patch("agent.config.legacy.PROJECT_CONFIG_FILE", Path(f.name)), \
                    mock.patch("agent.config.legacy.HAS_YAML", True):
                result = load_project_config()
                assert result["model"]["provider"] == "test"

    def test_returns_empty_on_invalid_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("- just\n- a\n- list\n")
            f.flush()
            with mock.patch("agent.config.legacy.PROJECT_CONFIG_FILE", Path(f.name)), \
                    mock.patch("agent.config.legacy.HAS_YAML", True):
                result = load_project_config()
                assert result == {}


# ---------------------------------------------------------------------------
# load_settings
# ---------------------------------------------------------------------------


class TestLoadSettings:
    """测试 load_settings 三级优先级。"""

    def test_returns_defaults_when_no_files(self):
        with mock.patch("agent.config.legacy.PROJECT_CONFIG_FILE", Path("/nonexistent")), \
                mock.patch("agent.config.legacy.SETTINGS_FILE", Path("/nonexistent")):
            settings = load_settings()
            assert settings["availableModels"] == DEFAULT_SETTINGS["availableModels"]

    def test_project_config_overrides_defaults(self):
        yaml_content = "availableModels:\n  - label: Test\n    model: gpt-4o\n    provider: openai\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            with mock.patch("agent.config.legacy.PROJECT_CONFIG_FILE", Path(f.name)), \
                    mock.patch("agent.config.legacy.HAS_YAML", True), \
                    mock.patch("agent.config.legacy.SETTINGS_FILE", Path("/nonexistent")):
                settings = load_settings()
                assert settings["availableModels"][0]["provider"] == "openai"
                assert settings["availableModels"][0]["model"] == "gpt-4o"

    def test_user_config_highest_priority(self):
        user_settings = {"availableModels": [{"label": "My", "model": "my-custom-model", "provider": "openai"}]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(user_settings, f)
            f.flush()
            with mock.patch("agent.config.legacy.PROJECT_CONFIG_FILE", Path("/nonexistent")), \
                    mock.patch("agent.config.legacy.SETTINGS_FILE", Path(f.name)):
                settings = load_settings()
                assert settings["availableModels"][0]["model"] == "my-custom-model"


# ---------------------------------------------------------------------------
# get_model_config / get_tools_config
# ---------------------------------------------------------------------------


class TestConfigExtractors:
    """测试配置提取函数。"""

    def test_get_model_config_new_format(self):
        settings = {
            "availableModels": [
                {"label": "Claude 3", "model": "claude-3", "provider": "claude"},
            ],
            "maxTokens": 8192,
            "temperature": 0.7,
            "thinking": None,
        }
        result = get_model_config(settings)
        assert result["provider"] == "claude"
        assert result["name"] == "claude-3"
        assert result["params"]["max_tokens"] == 8192
        assert result["params"]["temperature"] == 0.7

    def test_get_model_config_old_format_migrated(self):
        """旧格式 (model 为嵌套对象) 应自动迁移。"""
        settings = {
            "model": {"provider": "openai", "name": "gpt-4o", "params": {"max_tokens": 2048}}
        }
        result = get_model_config(settings)
        assert result["provider"] == "openai"
        assert result["name"] == "gpt-4o"
        assert result["params"]["max_tokens"] == 2048

    def test_get_model_config_defaults(self):
        result = get_model_config({})
        # 空配置时回退到 DEFAULT_SETTINGS 的 availableModels[0]
        assert result["provider"] == "ollama"
        assert result["name"] == "qwen2.5:7b"

    def test_migrate_old_settings_nested_dict(self):
        old = {
            "model": {
                "provider": "claude",
                "name": "deepseek-v4-pro",
                "params": {"max_tokens": 4096, "temperature": None, "thinking": None},
                "catalog": [{"label": "Test", "model": "test", "provider": "claude"}],
            },
            "env": {"ANTHROPIC_API_KEY": "sk-test"},
        }
        result = _migrate_old_settings(old)
        assert "model" not in result
        assert result["availableModels"] == [{"label": "Test", "model": "test", "provider": "claude"}]
        assert result["maxTokens"] == 4096
        assert result["env"] == {"ANTHROPIC_API_KEY": "sk-test"}

    def test_migrate_old_settings_transition_format(self):
        """过渡格式 (model 字符串 + modelProvider) 应迁移。"""
        old = {
            "model": "deepseek-v4-pro",
            "modelProvider": "claude",
            "availableModels": [
                {"label": "DeepSeek V4 Pro", "model": "deepseek-v4-pro", "provider": "claude"},
            ],
        }
        result = _migrate_old_settings(old)
        assert "model" not in result
        assert "modelProvider" not in result
        assert result["availableModels"][0]["model"] == "deepseek-v4-pro"

    def test_migrate_new_format_passthrough(self):
        """新格式不应被修改。"""
        new = {"availableModels": [{"label": "Test", "model": "test", "provider": "ollama"}]}
        result = _migrate_old_settings(new)
        assert result == new

    def test_get_tools_config_empty(self):
        result = get_tools_config({})
        assert result == {}

    def test_get_tools_config_with_data(self):
        settings = {"tools": {"serial": {"max_bytes": 5120}}}
        result = get_tools_config(settings)
        assert result == {"serial": {"max_bytes": 5120}}
