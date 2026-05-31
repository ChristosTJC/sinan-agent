# 司南配置文件说明

## 配置文件位置

```
~/.sinan/settings.json
```

首次运行 `sinan` 时会自动创建默认配置文件。

## 配置模型

### 方式 1: 编辑配置文件（推荐）

```bash
nano ~/.sinan/settings.json
```

修改 `model` 部分：

```json
{
  "model": {
    "provider": "groq",
    "name": "llama-3.3-70b-versatile",
    "api_key": "gsk_your_api_key"
  }
}
```

### 方式 2: 使用环境变量

```bash
export GENERIC_API_KEY="gsk_your_key"
export GENERIC_BASE_URL="https://api.groq.com/openai/v1"
sinan
```

### 方式 3: REPL 内切换

```
/model groq llama-3.3-70b-versatile
```

## 支持的 Provider

| Provider | 示例模型 | 配置方式 |
|----------|---------|----------|
| **ollama** | qwen2.5:7b | 本地运行 Ollama |
| **groq** | llama-3.3-70b | `GENERIC_API_KEY` |
| **deepseek** | deepseek-chat | `GENERIC_API_KEY` |
| **zhipu** | glm-4 | `GENERIC_API_KEY` |
| **moonshot** | moonshot-v1-8k | `GENERIC_API_KEY` |
| **siliconflow** | Qwen2.5-72B | `GENERIC_API_KEY` |
| **openai** | gpt-4o | `OPENAI_API_KEY` |
| **claude** | claude-sonnet-4 | `ANTHROPIC_API_KEY` |

## 配置示例

参考 `settings.json.example` 文件，包含所有支持服务的配置模板。

## 查看当前配置

在 REPL 内输入：

```
/settings
```
