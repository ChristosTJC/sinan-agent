"""
司南配置加载器。

从多个来源加载配置,支持三级优先级:
1. ~/.sinan/settings.json (用户覆盖)
2. 项目根目录的 config.defaults.yaml (项目默认)
3. DEFAULT_SETTINGS (硬编码兜底)

支持的配置:
- 模型配置 (provider, model, api_key, base_url)
- 环境变量 (API Keys, Base URLs)
- REPL 设置 (主题、历史记录)
- 代理配置
- 工具配置 (串口安全边界、设备节点默认参数)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

logger = logging.getLogger(__name__)

SINAN_HOME = Path(os.environ.get("SINAN_HOME", Path.home() / ".sinan"))
SETTINGS_FILE = SINAN_HOME / "settings.json"

# 项目根目录 (用于加载 config.defaults.yaml)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_CONFIG_FILE = PROJECT_ROOT / "config.defaults.yaml"

# 默认配置 (参考 Claude Code 风格)
# availableModels[0] 即为启动默认模型
DEFAULT_SETTINGS = {
    "availableModels": [
        {"label": "Qwen 2.5 7B (Ollama 本地)", "model": "qwen2.5:7b", "provider": "ollama"},
    ],
    # ── 模型参数 ──
    "maxTokens": 4096,
    "temperature": None,
    "thinking": None,
    "effortLevel": None,                # 推理努力程度: "low" | "medium" | "high" | None
    # ── 环境变量 ──
    "env": {
        "OLLAMA_BASE_URL": "http://localhost:11434/v1",
        "GENERIC_API_KEY": "",
        "GENERIC_BASE_URL": "",
        "OPENAI_API_KEY": "",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    },
    "repl": {
        "theme": "sinan",
        "auto_complete": True,
        "history_file": str(SINAN_HOME / "repl_history"),
        "max_history": 1000,
    },
    "proxy": {
        "http": "",
        "https": "",
    },
    "tools": {
        "max_tool_depth": 25,  # 单 turn 内 LLM↔工具最大循环轮数
    },
    "debug": False,
}


def load_project_config() -> dict[str, Any]:
    """加载项目默认配置 (config.defaults.yaml)。

    Returns:
        项目默认配置字典。文件不存在或解析失败时返回空字典。
    """
    if not HAS_YAML:
        logger.warning("PyYAML 未安装,无法加载项目默认配置")
        return {}

    if not PROJECT_CONFIG_FILE.exists():
        logger.debug("项目默认配置文件不存在: %s", PROJECT_CONFIG_FILE)
        return {}

    try:
        with open(PROJECT_CONFIG_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        logger.info("已加载项目默认配置: %s", PROJECT_CONFIG_FILE)
        return config if isinstance(config, dict) else {}
    except (yaml.YAMLError, IOError) as e:
        logger.warning("项目默认配置文件加载失败: %s，返回空配置", e)
        return {}


def _migrate_old_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """将旧格式迁移到新格式。

    支持两种旧格式:
    1. model 为嵌套对象 (原始格式)
    2. model 为字符串 + modelProvider (中间过渡格式)

    新格式::

        {"availableModels": [{"label": ..., "model": ..., "provider": ...}],
         "maxTokens": 4096, ...}
    """
    model_val = settings.get("model")
    result = settings.copy()

    # 情况 1: model 是嵌套 dict (原始旧格式)
    if isinstance(model_val, dict):
        old_model = model_val
        name = old_model.get("name", "qwen2.5:7b")
        provider = old_model.get("provider", "ollama")

        # 构建 availableModels
        if "catalog" in old_model:
            result["availableModels"] = old_model["catalog"]
        else:
            result["availableModels"] = [{"label": name, "model": name, "provider": provider}]

        # 迁移 params -> 顶层字段
        params = old_model.get("params", {})
        if "max_tokens" in params:
            result.setdefault("maxTokens", params["max_tokens"])
        if "temperature" in params:
            result.setdefault("temperature", params["temperature"])
        if "thinking" in params:
            result.setdefault("thinking", params["thinking"])

        del result["model"]
        return result

    # 情况 2: model 是字符串 + modelProvider (过渡格式)
    if isinstance(model_val, str) and "modelProvider" in settings:
        name = model_val
        provider = settings["modelProvider"]
        available = result.get("availableModels", [])

        # 确保默认模型在 availableModels[0]
        if available:
            # 如果默认模型不在列表中，插入到开头
            if not any(e.get("model") == name for e in available):
                available.insert(0, {"label": name, "model": name, "provider": provider})
        else:
            result["availableModels"] = [{"label": name, "model": name, "provider": provider}]

        del result["model"]
        del result["modelProvider"]
        return result

    return result  # 已经是新格式


def load_settings() -> dict[str, Any]:
    """加载用户配置。

    优先级 (从高到低):
    1. ~/.sinan/settings.json (用户覆盖)
    2. config.defaults.yaml (项目默认)
    3. DEFAULT_SETTINGS (硬编码兜底)

    自动将旧格式 (model 嵌套对象) 迁移到新格式 (扁平结构)。

    Returns:
        合并后的配置字典
    """
    # 从硬编码兜底开始
    settings = DEFAULT_SETTINGS.copy()

    # 合并项目默认配置 (第二优先级)
    project_config = load_project_config()
    if project_config:
        settings = _deep_merge(settings, project_config)

    # 合并用户配置 (最高优先级)
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                user_settings = json.load(f)
            settings = _deep_merge(settings, user_settings)
            logger.info("已加载用户配置: %s", SETTINGS_FILE)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("用户配置文件加载失败: %s，使用项目默认配置", e)

    # 自动迁移旧格式
    settings = _migrate_old_settings(settings)

    return settings


def save_settings(settings: dict[str, Any]) -> None:
    """保存配置到 ~/.sinan/settings.json。

    Args:
        settings: 配置字典
    """
    SINAN_HOME.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    logger.info(f"配置已保存: {SETTINGS_FILE}")


def apply_settings(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """加载配置并应用到环境变量。

    Args:
        settings: 可选的配置字典，为 None 时自动加载

    Returns:
        应用后的配置字典
    """
    if settings is None:
        settings = load_settings()

    # 应用环境变量
    env_config = settings.get("env", {})
    for key, value in env_config.items():
        if value and key not in os.environ:
            os.environ[key] = value
            logger.debug(f"设置环境变量: {key}")

    # 应用代理
    proxy_config = settings.get("proxy", {})
    if proxy_config.get("http") and "http_proxy" not in os.environ:
        os.environ["http_proxy"] = proxy_config["http"]
    if proxy_config.get("https") and "https_proxy" not in os.environ:
        os.environ["https_proxy"] = proxy_config["https"]

    return settings


def get_model_config(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """获取模型配置 (兼容新旧格式)。

    默认模型由 availableModels[0] 决定。

    Args:
        settings: 可选的配置字典

    Returns:
        标准化模型配置字典 {provider, name, params, availableModels}
    """
    if settings is None:
        settings = load_settings()

    # 旧格式兼容
    model_val = settings.get("model")
    if isinstance(model_val, (dict, str)):
        settings = _migrate_old_settings(settings)

    # 从 availableModels[0] 取默认模型
    available = settings.get("availableModels", [])
    default_entry = available[0] if available else {}

    return {
        "provider": default_entry.get("provider", "ollama"),
        "name": default_entry.get("model", "qwen2.5:7b"),
        "params": {
            "max_tokens": settings.get("maxTokens", 4096),
            "temperature": settings.get("temperature"),
            "thinking": settings.get("thinking"),
        },
        "availableModels": available,
    }


def get_tools_config(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """获取工具配置。

    包括串口安全边界、设备节点默认参数等。

    Args:
        settings: 可选的配置字典

    Returns:
        工具配置字典,例如::

            {
                "serial": {
                    "max_duration_sec": 30,
                    "max_bytes": 10240
                },
                "device_node": {
                    "default_port": 8765,
                    "timeout_sec": 5.0
                }
            }
    """
    if settings is None:
        settings = load_settings()

    return settings.get("tools", {})


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典。

    Args:
        base: 基础字典
        override: 覆盖字典

    Returns:
        合并后的字典
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def create_default_config() -> None:
    """创建默认配置文件（如果不存在）。"""
    if not SETTINGS_FILE.exists():
        SINAN_HOME.mkdir(parents=True, exist_ok=True)
        save_settings(DEFAULT_SETTINGS)
        logger.info(f"已创建默认配置: {SETTINGS_FILE}")
