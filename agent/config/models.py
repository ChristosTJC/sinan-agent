"""
Pydantic 配置模型。

提供类型安全的配置验证和默认值管理。
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ThinkingConfig(BaseModel):
    """思考配置。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["enabled", "disabled"] = "disabled"
    budget_tokens: Optional[int] = Field(None, ge=1000, le=10000)


class ModelConfig(BaseModel):
    """模型配置。"""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    provider: Literal["claude", "openai", "ollama", "generic"] = "ollama"
    api_key: Optional[str] = None
    base_url: Optional[str] = None

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: Optional[str], info) -> Optional[str]:
        """验证 API Key 格式。"""
        if v is None:
            return v

        provider = info.data.get("provider")
        if provider == "claude" and not v.startswith("sk-ant-"):
            raise ValueError("Claude API Key 必须以 'sk-ant-' 开头")
        if provider == "openai" and not v.startswith("sk-"):
            raise ValueError("OpenAI API Key 必须以 'sk-' 开头")

        return v


class ToolsConfig(BaseModel):
    """工具配置。"""

    model_config = ConfigDict(extra="allow")  # 允许工具特定配置

    enabled: List[str] = Field(default_factory=list)
    disabled: List[str] = Field(default_factory=list)
    danger_confirm: bool = True
    timeout_seconds: int = Field(30, ge=1, le=300)


class ContextConfig(BaseModel):
    """上下文配置。"""

    model_config = ConfigDict(extra="forbid")

    max_tokens: int = Field(100000, ge=10000, le=200000)
    compaction_threshold: float = Field(0.8, ge=0.5, le=0.95)
    preserve_recent_turns: int = Field(5, ge=1, le=20)


class MemoryConfig(BaseModel):
    """记忆配置。"""

    model_config = ConfigDict(extra="forbid")

    l1_core_dir: str = "~/.sinan/memories"
    l2_session_dir: str = "~/.sinan/sessions"
    l3_knowledge_dir: str = "~/.sinan/knowledge"
    auto_save: bool = True
    max_session_age_days: int = Field(30, ge=1, le=365)


class TaskConfig(BaseModel):
    """任务配置。"""

    model_config = ConfigDict(extra="forbid")

    max_parallel: int = Field(3, ge=1, le=10)
    default_timeout_minutes: int = Field(30, ge=1, le=1440)
    retry_on_failure: bool = True
    max_retries: int = Field(2, ge=0, le=5)


class SinanSettings(BaseModel):
    """司南完整配置。"""

    model_config = ConfigDict(extra="forbid")

    available_models: List[ModelConfig] = Field(..., min_length=1)
    default_model: str = Field(..., min_length=1)
    max_tokens: int = Field(4096, ge=512, le=200000)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    thinking: Optional[ThinkingConfig] = None
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    task: TaskConfig = Field(default_factory=TaskConfig)
    env: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_default_model(self) -> "SinanSettings":
        """验证默认模型在可用列表中。"""
        available_names = [m.model for m in self.available_models]
        if self.default_model not in available_names:
            raise ValueError(
                f"default_model '{self.default_model}' 不在 available_models 中: {available_names}"
            )
        return self

    def get_model(self, name: Optional[str] = None) -> ModelConfig:
        """获取指定模型配置，默认返回 default_model。"""
        target = name or self.default_model
        for model in self.available_models:
            if model.model == target:
                return model
        raise ValueError(f"模型 '{target}' 未找到")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）。"""
        return self.model_dump(mode="json", exclude_none=True)
