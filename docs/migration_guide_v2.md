# 司南 2.0 迁移指南

本文档指导从司南 1.x 迁移到 2.0 版本。

## 概述

司南 2.0 引入了以下核心改进：

1. **任务编排系统** - 统一的任务管理、执行和调度框架
2. **上下文管理** - 智能对话历史压缩和管理
3. **配置管理** - 基于 Pydantic 的类型安全配置系统
4. **增强工具注册** - 支持依赖注入和生命周期管理

## 破坏性变更

### 1. 配置文件结构

**旧版本 (1.x)**:
```python
from agent.config import load_settings

settings = load_settings()
model = settings["model"]["name"]
```

**新版本 (2.0)**:
```python
from agent.config import ConfigLoader, SinanSettings

loader = ConfigLoader()
settings: SinanSettings = loader.load()
model = settings.model.name
```

**迁移步骤**:
- 使用 `ConfigLoader` 替代 `load_settings()`
- 配置对象现在是类型安全的 Pydantic 模型
- 访问配置项使用点号语法而非字典键

### 2. 工具注册

**旧版本 (1.x)**:
```python
from agent.tools import ToolRegistry

registry = ToolRegistry()
registry.register_tool("my_tool", my_func, schema)
```

**新版本 (2.0)**:
```python
from agent.tools import EnhancedToolRegistry

registry = EnhancedToolRegistry()
registry.register(
    name="my_tool",
    func=my_func,
    schema=schema,
    dependencies={"config": config_obj}
)
```

**迁移步骤**:
- 使用 `EnhancedToolRegistry` 替代 `ToolRegistry`
- `register_tool()` 改为 `register()`
- 支持依赖注入：通过 `dependencies` 参数传递依赖

### 3. 任务执行

**旧版本 (1.x)**:
```python
# 直接调用工具
result = tool_func(**args)
```

**新版本 (2.0)**:
```python
from agent.tasks import TaskManager, TaskExecutor, TaskType

manager = TaskManager()
executor = TaskExecutor(manager, max_workers=4)

task = manager.create_task(
    name="my_task",
    type=TaskType.TOOL_CALL,
    executor=lambda: tool_func(**args),
    args={},
    dependencies=[]
)

result = executor.execute_task(task.id)
```

**迁移步骤**:
- 将直接工具调用包装为 Task
- 使用 TaskManager 管理任务生命周期
- 使用 TaskExecutor 执行任务

## 新增功能

### 1. 上下文管理

```python
from agent.context import ContextManager, MessageCompactor

# 自动压缩对话历史
context_mgr = ContextManager(max_turns=10, max_tokens=100000)
messages = context_mgr.compact(messages)

# 压缩工具输出
compactor = MessageCompactor()
compressed = compactor.compress_tool_result(
    tool_name="read_file",
    output=long_output,
    max_chars=400
)
```

### 2. 任务调度

```python
from agent.tasks import TaskScheduler

scheduler = TaskScheduler(task_manager, task_executor)

# 批量执行任务（自动处理依赖）
results = scheduler.execute_batch([task1, task2, task3])
```

### 3. 配置验证

```python
from agent.config import ConfigLoader

loader = ConfigLoader()
settings = loader.load()  # 自动验证配置

# 访问配置（带类型提示）
max_tokens: int = settings.model.max_tokens
thinking_enabled: bool = settings.model.thinking.enabled
```

## 兼容性层

为了平滑迁移，2.0 保留了部分 1.x API：

```python
# 这些函数仍然可用（从 agent.config.legacy 导入）
from agent.config import apply_settings, get_model_config, load_settings

settings = load_settings()  # 返回字典（旧格式）
```

**注意**: 兼容性层将在 3.0 版本移除，建议尽快迁移到新 API。

## 迁移检查清单

- [ ] 更新 `requirements.txt`，添加 `pydantic>=2.0.0`
- [ ] 将 `load_settings()` 替换为 `ConfigLoader().load()`
- [ ] 将 `ToolRegistry` 替换为 `EnhancedToolRegistry`
- [ ] 将直接工具调用包装为 Task（如果需要任务管理）
- [ ] 在 REPL 中集成 `ContextManager` 进行上下文压缩
- [ ] 运行测试套件确保功能正常

## 常见问题

### Q: 为什么配置从字典改为 Pydantic 模型？

A: Pydantic 提供：
- 类型安全和自动验证
- IDE 自动补全支持
- 更好的错误提示
- 配置文档自动生成

### Q: 旧的工具还能用吗？

A: 可以。`EnhancedToolRegistry` 向后兼容旧的工具定义，只需修改注册方式。

### Q: 任务系统是强制的吗？

A: 不是。如果不需要任务编排、依赖管理或并发控制，可以继续直接调用工具。任务系统主要用于复杂工作流。

### Q: 如何调试配置加载问题？

A: 启用调试日志：
```python
import logging
logging.basicConfig(level=logging.DEBUG)

from agent.config import ConfigLoader
loader = ConfigLoader()
settings = loader.load()  # 会输出详细加载过程
```

## 获取帮助

- 查看示例代码：`tests/` 目录
- 阅读 API 文档：各模块的 docstring
- 提交 Issue：描述迁移中遇到的问题
