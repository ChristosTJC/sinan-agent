# 司南 2.0 整体升级设计文档

> 版本: 2.0  
> 日期: 2026-05-31  
> 作者: Claude Opus 4.8  
> 状态: 设计阶段

---

## 一、项目概述

### 1.1 升级目标

将司南从原型阶段升级为**面向整个嵌入式开发领域的专业级智能体工具**，具备完整的任务编排能力、智能上下文管理和优秀的用户体验。

### 1.2 核心原则

- **渐进式重构**：保持系统始终可用，分 3 个阶段实施
- **部分兼容**：核心数据（L1/L2/L3 记忆）保持兼容，配置可调整
- **独立部署**：不依赖 Claude Code，作为独立工具运行
- **参考最佳实践**：借鉴 Claude Code 的任务系统、上下文管理等设计

### 1.3 升级范围

| 维度 | 当前状态 | 目标状态 |
|------|---------|---------|
| 任务系统 | 简单递归调用 | 完整任务编排（依赖管理、并行执行、断点续传） |
| 上下文管理 | 无压缩机制 | 自动压缩、分层缓存、滑动窗口 |
| 工具系统 | 基础注册 | 元数据、依赖管理、分类、危险等级 |
| UI/UX | 基础 rich | 任务卡片、进度条、语法高亮、实时反馈 |
| 配置管理 | 简单 JSON | Pydantic schema 验证 |
| 日志系统 | 基础 logging | 结构化日志（structlog） |
| 测试覆盖 | 几乎无 | 80% 覆盖率 |

---

## 二、总体架构

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        交互层 (REPL)                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 增强型 REPL (prompt_toolkit + rich)                  │   │
│  │ • 任务卡片可视化  • 实时进度反馈  • 语法高亮        │   │
│  └──────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                    任务编排层 (新增)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │ TaskManager  │  │ TaskExecutor │  │ TaskScheduler   │   │
│  │ 任务注册管理  │  │ 执行引擎     │  │ 依赖调度        │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Task (状态机 + 生命周期 + 结果压缩 + 持久化)         │   │
│  └──────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                   上下文管理层 (重构)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │ ContextMgr   │  │ ThinkingChain│  │ MessageCompactor│   │
│  │ 滑动窗口     │  │ 思维链追踪   │  │ 智能压缩        │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                    记忆系统 (保留+增强)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │ L1 核心记忆  │  │ L2 会话DB    │  │ L3 知识库+索引  │   │
│  │ (保持不变)   │  │ (保持不变)   │  │ (增加Whoosh)    │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                   工具系统 (增强)                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ EnhancedToolRegistry (元数据 + 依赖 + 分类)          │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌────────┐ ┌──────────┐ ┌────────┐ ┌──────────────────┐   │
│  │串口增强│ │编译增强  │ │烧录增强│ │J-Link支持(新增)  │   │
│  │协议解析│ │增量编译  │ │批量烧录│ │                  │   │
│  └────────┘ └──────────┘ └────────┘ └──────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                   配置与日志 (新增)                          │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ Pydantic配置 │  │ structlog日志│                        │
│  │ Schema验证   │  │ 结构化记录   │                        │
│  └──────────────┘  └──────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块职责

| 模块 | 职责 | 关键类 |
|------|------|--------|
| **任务编排层** | 管理工具调用的生命周期、依赖关系、并行执行 | Task, TaskManager, TaskExecutor, TaskScheduler |
| **上下文管理层** | 自动压缩历史消息、追踪思维链、智能压缩工具结果 | ContextManager, ThinkingChain, MessageCompactor |
| **记忆系统** | L1 核心记忆、L2 会话数据库、L3 知识库全文索引 | MemoryStore, SessionDB, KnowledgeIndex |
| **工具系统** | 工具注册、元数据管理、执行调度、参数验证 | EnhancedToolRegistry, ToolMetadata, ToolWrapper |
| **配置管理** | 配置加载、验证、环境变量管理 | SinanSettings, ConfigLoader |
| **日志系统** | 结构化日志记录、性能追踪 | structlog |

---

## 三、分阶段实施计划

### 阶段 1：核心基础设施（1-2 周）

**目标**：建立坚实的基础架构，解决当前核心痛点

#### 3.1.1 任务系统实现

**新增模块**：
- `agent/tasks/task.py` - Task 类、TaskStatus、TaskType、TaskResult
- `agent/tasks/manager.py` - TaskManager（任务注册、依赖管理）
- `agent/tasks/executor.py` - TaskExecutor（同步/异步执行、并行执行）
- `agent/tasks/scheduler.py` - TaskScheduler（依赖调度、优先级队列）
- `agent/tasks/persistence.py` - TaskPersistence（断点续传）

**核心功能**：
- 任务状态机：PENDING → RUNNING → COMPLETED/FAILED/CANCELLED
- 依赖管理：任务可以声明依赖关系，自动按顺序执行
- 并行执行：独立任务自动并行运行（最多 4 个并发）
- 结果压缩：长输出自动截断（保留头尾各 200 字符）
- 断点续传：任务执行状态持久化到 `~/.sinan/checkpoints/`

**集成点**：
- REPL 中的工具调用转换为 Task
- 替换现有的递归调用机制

#### 3.1.2 上下文管理实现

**新增模块**：
- `agent/context/manager.py` - ContextManager（滑动窗口、自动压缩）
- `agent/context/thinking.py` - ThinkingChain（思维链追踪）
- `agent/context/compactor.py` - MessageCompactor（消息压缩）

**核心功能**：
- 滑动窗口：保留最近 20 轮对话 + 系统提示
- 自动压缩：超过 100k tokens 时触发，旧对话用 LLM 生成摘要
- 思维链追踪：记录 LLM 的推理、规划、反思步骤
- 智能压缩：根据工具类型选择压缩策略（传感器数据、编译日志、文件内容）

**集成点**：
- REPL 主循环中，每次 LLM 调用前检查上下文大小
- 工具调用结果自动压缩后注入消息历史

#### 3.1.3 配置验证

**新增模块**：
- `agent/config/models.py` - Pydantic 模型定义
- `agent/config/loader.py` - 配置加载器（带验证）

**核心功能**：
- 配置 schema 验证：启动时自动检查配置文件
- 类型安全：所有配置项都有类型提示
- 默认值：缺失配置项自动填充默认值
- 错误提示：配置错误时给出清晰的错误信息

**迁移指南**：
- 旧配置文件自动迁移到新格式
- 提供 `sinan config validate` 命令验证配置

#### 3.1.4 关键 Bug 修复

**修复项**：
1. **DeepSeek API 配置问题**
   - 修正 `ANTHROPIC_BASE_URL` 为 `https://api.deepseek.com`
   - 添加 API Key 格式验证
   - 提供配置示例和错误提示

2. **长工具调用链上下文爆炸**
   - 通过任务系统的结果压缩解决
   - 通过上下文管理器的自动压缩解决

#### 3.1.5 工具增强

**增强现有工具**：
- **串口监听**：增加协议解析（CRC16）、统计信息、CSV 导出
- **固件编译**：增加增量编译、编译缓存、并行编译
- **固件烧录**：增加烧录验证、批量烧录

**新增工具**：
- **J-Link 烧录**：支持 J-Link 调试器烧录

**工具注册增强**：
- 添加 ToolMetadata（分类、危险等级、依赖、预计时间）
- 添加参数验证（jsonschema）
- 添加进度回调支持

#### 3.1.6 交付物

- [ ] 任务系统完整实现（5 个模块）
- [ ] 上下文管理完整实现（3 个模块）
- [ ] 配置验证完整实现（2 个模块）
- [ ] 增强的工具系统（4 个工具）
- [ ] 集成到 REPL 主循环
- [ ] 单元测试（覆盖率 ≥ 60%）
- [ ] 迁移指南文档

---

### 阶段 2：功能增强与体验优化（2-3 周）

**目标**：提升用户体验，增加差异化功能

#### 3.2.1 思维链可视化

**新增模块**：
- `agent/repl/thinking_renderer.py` - 思维链渲染器

**核心功能**：
- 实时显示 LLM 思维过程（推理、规划、反思）
- 树状结构可视化
- 导出为 Markdown
- 持久化到会话数据库

**UI 设计**：
```
思维链：
  ├─ 🧠 reasoning: 分析用户需求...
  ├─ 📋 planning: 制定执行计划...
  ├─ 🤔 reflection: 检查潜在问题...
  └─ ✅ decision: 决定使用串口监听工具
```

#### 3.2.2 知识库全文索引

**新增模块**：
- `agent/memory/knowledge_index.py` - Whoosh 全文索引

**核心功能**：
- 基于 BM25F 算法的相关性排序
- 分类过滤（MCU、协议、传感器、错误码）
- 增量更新（添加、更新、删除文档）
- 重建索引命令

**性能提升**：
- 检索速度从 O(n) 降低到 O(log n)
- 支持模糊搜索和同义词

#### 3.2.3 UI/UX 升级

**新增模块**：
- `agent/repl/widgets.py` - 任务卡片、仪表板
- `agent/repl/syntax_highlighter.py` - 代码语法高亮

**核心功能**：
- **任务卡片**：每个工具调用显示为可折叠的卡片
- **进度条**：长时间任务显示实时进度
- **语法高亮**：代码块自动高亮（C/C++/Python/YAML）
- **结果预览**：长输出自动折叠，点击展开

**UI 示例**：
```
┌─ ⏳ serial_monitor ────────────────────────┐
│ 正在监听 /dev/ttyUSB0...                   │
│ ████████████░░░░░░░░░░░░░░░░░░░░ 40%      │
│ 已接收 127 帧                              │
└────────────────────────────────────────────┘

┌─ ✓ build_firmware ─────────────────────────┐
│ 编译成功                                    │
│ • 耗时: 12.3s                              │
│ • 输出: firmware.bin (245 KB)             │
│ [展开详细日志]                             │
└────────────────────────────────────────────┘
```

#### 3.2.4 横向扩展平台支持

**新增支持**：
- **Nordic nRF 系列**：nRF52、nRF53
- **CMake 构建系统**：支持 CMake 项目编译
- **更多烧录工具**：pyOCD、OpenOCD

**知识库扩展**：
- 添加 Nordic nRF 芯片手册
- 添加 BLE 协议文档
- 添加 CMake 常见问题

#### 3.2.5 技能蒸馏质量评分

**新增模块**：
- `agent/distill/quality_scorer.py` - 技能质量评分器

**核心功能**：
- 完整性检查（必需字段）
- 可复用性检查（参数化步骤）
- 清晰度检查（描述长度、步骤数量）
- 自动过滤低质量提案（评分 < 0.6）

#### 3.2.6 交付物

- [ ] 思维链可视化完整实现
- [ ] 知识库全文索引（Whoosh）
- [ ] UI/UX 升级（任务卡片、进度条、语法高亮）
- [ ] 横向扩展平台（Nordic nRF、CMake）
- [ ] 技能蒸馏质量评分
- [ ] 单元测试（覆盖率 ≥ 70%）
- [ ] 用户手册更新

---

### 阶段 3：工程质量与生态扩展（2-3 周）

**目标**：达到生产就绪，支持第三方扩展

#### 3.3.1 测试覆盖

**测试框架**：pytest + pytest-cov

**测试范围**：
- **单元测试**：所有核心模块（任务系统、上下文管理、工具系统）
- **集成测试**：REPL 主循环、工具调用链、记忆系统
- **性能测试**：上下文压缩、知识库检索、并行任务执行

**目标覆盖率**：≥ 80%

**测试示例**：
```python
# tests/test_task_system.py
def test_task_dependency_execution():
    """测试任务依赖执行顺序"""
    manager = TaskManager()
    
    task_a = manager.create_task("A", TaskType.TOOL_CALL, lambda: "A")
    task_b = manager.create_task("B", TaskType.TOOL_CALL, lambda: "B", dependencies=[task_a.id])
    
    executor = TaskExecutor()
    scheduler = TaskScheduler(manager, executor)
    
    result = scheduler.run_until_complete(task_b.id)
    
    assert task_a.status == TaskStatus.COMPLETED
    assert task_b.status == TaskStatus.COMPLETED
    assert result.success
```

#### 3.3.2 结构化日志

**新增模块**：
- `agent/logging/config.py` - 日志配置
- `agent/logging/usage.py` - 日志使用示例

**核心功能**：
- 结构化日志（JSON 格式）
- 性能追踪（工具执行时间、LLM 调用时间）
- 日志分级（DEBUG/INFO/WARNING/ERROR）
- 日志轮转（按大小或时间）

**日志示例**：
```json
{
  "event": "tool_executed",
  "tool_name": "serial_monitor",
  "duration": 10.23,
  "success": true,
  "timestamp": "2026-05-31T10:30:45.123Z"
}
```

#### 3.3.3 插件系统

**新增模块**：
- `agent/plugins/loader.py` - 插件加载器
- `agent/plugins/interface.py` - 插件接口定义

**核心功能**：
- 从 `~/.sinan/plugins/` 加载第三方插件
- 插件可以注册新工具、新技能、新命令
- 插件隔离（独立命名空间）
- 插件依赖管理

**插件示例**：
```python
# ~/.sinan/plugins/my_plugin.py
from agent.plugins.interface import Plugin

class MyPlugin(Plugin):
    def register_tools(self, registry):
        registry.register(
            func=my_custom_tool,
            metadata=ToolMetadata(
                name="my_tool",
                description="My custom tool",
                category=ToolCategory.HARDWARE,
            )
        )
```

#### 3.3.4 调试分析工具

**新增工具**：
- **GDB 集成**：断点、变量查看、调用栈
- **逻辑分析仪集成**：Saleae、PulseView 数据导入
- **性能分析**：CPU 占用、内存使用、任务调度可视化

**实现方式**：
- GDB：通过 `pygdbmi` 库集成
- 逻辑分析仪：解析 CSV/VCD 文件
- 性能分析：集成 `py-spy` 或 `memray`

#### 3.3.5 文档完善

**文档类型**：
- **用户手册**：安装、配置、使用指南
- **开发者文档**：架构设计、API 参考、插件开发
- **迁移指南**：从 v1 迁移到 v2
- **最佳实践**：嵌入式开发工作流、技能编写规范

#### 3.3.6 交付物

- [ ] 测试覆盖率 ≥ 80%
- [ ] 结构化日志完整实现
- [ ] 插件系统完整实现
- [ ] 调试分析工具（GDB、逻辑分析仪）
- [ ] 完整文档（用户手册、开发者文档、迁移指南）
- [ ] 性能优化（启动时间 < 2s，工具调用延迟 < 100ms）

---

## 四、核心模块详细设计

### 4.1 任务系统

#### 4.1.1 Task 类

```python
@dataclass
class Task:
    """任务实体"""
    id: str                              # 唯一标识
    name: str                            # 任务名称
    type: TaskType                       # 任务类型（TOOL_CALL/LLM_INFERENCE/THINKING/COMPOSITE）
    status: TaskStatus                   # 状态（PENDING/RUNNING/COMPLETED/FAILED/CANCELLED）
    
    executor: Optional[Callable]         # 执行函数
    args: dict                           # 参数
    
    dependencies: list[str]              # 依赖的任务 ID
    children: list['Task']               # 子任务
    
    result: Optional[TaskResult]         # 执行结果
    
    created_at: datetime                 # 创建时间
    started_at: Optional[datetime]       # 开始时间
    completed_at: Optional[datetime]     # 完成时间
    progress: float                      # 进度（0.0-1.0）
    
    checkpoint_data: Optional[dict]      # 断点数据
```

**关键方法**：
- `duration()` - 计算执行时长
- `compress_result(max_chars)` - 压缩结果输出

#### 4.1.2 TaskManager

**职责**：任务注册、查询、依赖管理

**关键方法**：
- `create_task(name, type, executor, args, dependencies)` - 创建任务
- `get_ready_tasks()` - 获取所有就绪的任务（依赖已满足）
- `get_blocked_tasks()` - 获取所有被阻塞的任务
- `get_task_chain(task_id)` - 获取任务的完整依赖链
- `update_status(task_id, status)` - 更新任务状态

**数据结构**：
- `tasks: Dict[str, Task]` - 任务字典
- `task_graph: Dict[str, List[str]]` - 依赖图（邻接表）

#### 4.1.3 TaskExecutor

**职责**：任务的实际执行

**关键方法**：
- `execute(task)` - 同步执行任务
- `execute_async(task)` - 异步执行任务
- `execute_parallel(tasks)` - 并行执行多个任务
- `set_callbacks(status_callback, progress_callback)` - 设置回调

**线程池**：
- 使用 `ThreadPoolExecutor`，默认 4 个 worker
- 支持动态调整并发数

#### 4.1.4 TaskScheduler

**职责**：任务调度和编排

**关键方法**：
- `schedule(task, priority)` - 调度任务
- `schedule_with_dependencies(task)` - 调度任务及其依赖链
- `run_until_complete(task_id)` - 运行直到指定任务完成
- `run_parallel(task_ids)` - 并行运行多个独立任务

**调度策略**：
- 优先级队列（依赖越早，优先级越高）
- 依赖检查（只执行依赖已满足的任务）
- 死锁检测（循环依赖检测）

---

### 4.2 上下文管理

#### 4.2.1 ContextManager

**职责**：自动压缩历史消息，避免上下文爆炸

**关键方法**：
- `compact(messages)` - 压缩消息历史
- `set_compressor(compressor)` - 设置 LLM 压缩器
- `_estimate_tokens(messages)` - 估算 token 数量
- `_summarize_messages(messages)` - 用 LLM 摘要消息

**压缩策略**：
1. **滑动窗口**：保留最近 N 轮对话（默认 20）
2. **系统消息保留**：始终保留系统提示
3. **旧消息摘要**：超出窗口的消息用 LLM 生成摘要
4. **长消息压缩**：单条消息超过 2000 字符时截断

**Token 估算**：
- 粗略估计：1 token ≈ 4 字符（中文）
- 精确估计：使用 `tiktoken` 库（可选）

#### 4.2.2 ThinkingChain

**职责**：追踪和可视化 LLM 思维过程

**关键方法**：
- `start_session(session_id)` - 开始新的思维会话
- `add_step(content, type, metadata)` - 添加思维步骤
- `get_chain()` - 获取完整思维链
- `visualize()` - 可视化思维链（树状结构）
- `export_to_markdown()` - 导出为 Markdown
- `persist(filepath)` - 持久化到文件

**思维类型**：
- REASONING - 推理
- PLANNING - 规划
- REFLECTION - 反思
- ANALYSIS - 分析
- DECISION - 决策

#### 4.2.3 MessageCompactor

**职责**：智能压缩工具调用结果

**关键方法**：
- `compress_tool_result(tool_name, result, max_chars)` - 压缩工具结果
- `compress_message_batch(messages)` - 批量压缩消息
- `get_stats()` - 获取压缩统计

**压缩策略**：
- **传感器数据**：提取统计信息（平均值、范围、前后几行）
- **编译日志**：保留错误和警告
- **文件内容**：保留开头和结尾
- **通用策略**：头尾保留

---

### 4.3 工具系统

#### 4.3.1 EnhancedToolRegistry

**职责**：工具注册、元数据管理、执行调度

**关键方法**：
- `register(func, metadata, override)` - 注册工具
- `get_tool(name)` - 获取工具
- `get_by_category(category)` - 按分类获取工具
- `execute(name, args, approval_callback, progress_callback)` - 执行工具
- `validate_args(name, args)` - 验证参数
- `to_openai_format()` - 转换为 OpenAI tool calling 格式

**ToolMetadata**：
```python
@dataclass
class ToolMetadata:
    name: str                            # 工具名称
    description: str                     # 描述
    category: ToolCategory               # 分类（HARDWARE/BUILD/DEBUG/MEMORY/FILE/NETWORK）
    danger_level: DangerLevel            # 危险等级（SAFE/CAUTION/DANGEROUS）
    
    dependencies: List[str]              # 依赖的其他工具
    required_packages: List[str]         # 依赖的 Python 包
    
    estimated_time: float                # 预计执行时间（秒）
    supports_progress: bool              # 是否支持进度回调
    
    platforms: List[str]                 # 支持的平台
    parameters_schema: Optional[dict]    # 参数 schema（jsonschema）
    examples: List[str]                  # 使用示例
```

#### 4.3.2 增强的串口工具

**EnhancedSerialMonitor**：
- 协议解析（CRC16、自定义协议）
- 统计信息（帧数、字节数、错误率）
- CSV 导出
- 自动重连

**ProtocolParser**：
- 基类：`ProtocolParser`
- 实现：`CRC16Parser`、`CustomProtocolParser`
- 可扩展：用户可以自定义解析器

#### 4.3.3 增强的编译工具

**EnhancedFirmwareBuilder**：
- 增量编译（基于文件哈希）
- 编译缓存（`.build_cache/`）
- 并行编译（`make -j4`）
- 编译日志解析（提取错误和警告）

**BuildCache**：
- 计算文件哈希（SHA256）
- 检测修改的文件
- 缓存持久化（JSON）

---

### 4.4 配置管理

#### 4.4.1 Pydantic 模型

**SinanSettings**：
```python
class SinanSettings(BaseModel):
    availableModels: List[ModelConfig]   # 可用模型列表
    maxTokens: int                       # 最大输出 token
    temperature: Optional[float]         # 温度参数
    thinking: Optional[ThinkingConfig]   # 思考配置
    
    env: EnvConfig                       # 环境变量
    repl: REPLConfig                     # REPL 配置
    proxy: ProxyConfig                   # 代理配置
    tools: ToolsConfig                   # 工具配置
    memory: MemoryConfig                 # 记忆配置
    task: TaskConfig                     # 任务配置
    context: ContextConfig               # 上下文配置
    
    debug: bool                          # 调试模式
```

**验证规则**：
- 模型列表至少包含 1 个模型
- URL 格式验证
- API Key 格式验证
- 至少配置一个 API Key（或使用 Ollama）
- 默认模型的 API Key 必须配置

#### 4.4.2 ConfigLoader

**职责**：加载、验证、保存配置

**关键方法**：
- `load()` - 加载并验证配置
- `save(settings)` - 保存配置
- `validate_file(filepath)` - 验证配置文件（不加载）
- `_create_default()` - 创建默认配置

**配置优先级**：
1. 命令行参数
2. `~/.sinan/settings.json`
3. 项目根目录 `config.defaults.yaml`
4. 硬编码默认值

---

### 4.5 日志系统

#### 4.5.1 结构化日志

**使用 structlog**：
```python
logger = get_logger(__name__)

logger.info(
    "tool_executed",
    tool_name="serial_monitor",
    duration=10.23,
    success=True,
)
```

**输出格式**（JSON）：
```json
{
  "event": "tool_executed",
  "tool_name": "serial_monitor",
  "duration": 10.23,
  "success": true,
  "logger": "agent.tools.serial_monitor",
  "level": "info",
  "timestamp": "2026-05-31T10:30:45.123Z"
}
```

#### 4.5.2 日志分类

**事件类型**：
- `tool_executed` - 工具执行
- `task_lifecycle` - 任务生命周期
- `context_compacted` - 上下文压缩
- `llm_call` - LLM 调用
- `memory_updated` - 记忆更新
- `skill_distilled` - 技能蒸馏

**日志级别**：
- DEBUG - 详细调试信息
- INFO - 正常操作信息
- WARNING - 警告信息
- ERROR - 错误信息

---

## 五、数据流设计

### 5.1 用户输入处理流程

```
用户输入
  ↓
检查斜杠命令
  ↓ (非命令)
上下文压缩检查 (ContextManager.compact)
  ↓
注入 L3 知识库上下文 (临时)
  ↓
添加到消息历史
  ↓
开始思维会话 (ThinkingChain.start_session)
  ↓
调用 LLM (流式输出)
  ↓
解析响应 (文本 + 工具调用)
  ↓
清理临时知识上下文
  ↓
处理工具调用 (转换为 Task)
  ↓
任务调度执行 (TaskScheduler)
  ↓
结果压缩 (MessageCompactor)
  ↓
添加到消息历史
  ↓
持久化到 L2 会话数据库
```

### 5.2 工具调用处理流程

```
LLM 返回工具调用列表
  ↓
遍历每个工具调用
  ↓
创建 Task (TaskManager.create_task)
  ↓
添加到任务仪表板 (TaskDashboard.add_task)
  ↓
检查依赖关系
  ↓
独立任务 → 并行执行 (TaskScheduler.run_parallel)
依赖任务 → 串行执行 (TaskScheduler.run_until_complete)
  ↓
执行前回调 (危险工具需要用户确认)
  ↓
执行工具 (TaskExecutor.execute)
  ↓
进度回调 (更新任务卡片)
  ↓
结果压缩 (Task.compress_result)
  ↓
更新任务状态 (COMPLETED/FAILED)
  ↓
保存检查点 (TaskPersistence.save_checkpoint)
  ↓
返回结果
```

### 5.3 上下文压缩流程

```
检查消息历史 token 数
  ↓
超过阈值？
  ↓ (是)
分离系统消息、最近消息、旧消息
  ↓
旧消息数量 > 0？
  ↓ (是)
调用 LLM 生成摘要
  ↓
构建摘要消息
  ↓
合并：系统消息 + 摘要消息 + 最近消息
  ↓
返回压缩后的消息历史
```

---

## 六、UI/UX 设计

### 6.1 任务卡片

**状态指示**：
- ⏳ PENDING - 黄色边框
- ⚙️ RUNNING - 蓝色边框 + 进度条
- ✓ COMPLETED - 绿色边框
- ✗ FAILED - 红色边框

**内容布局**：
```
┌─ ⚙️ serial_monitor ────────────────────────┐
│ 正在监听 /dev/ttyUSB0...                   │
│ ████████████░░░░░░░░░░░░░░░░░░░░ 40%      │
│ 已接收 127 帧                              │
└────────────────────────────────────────────┘
```

**交互**：
- 点击卡片展开/折叠详细信息
- 长输出自动截断，显示"展开"按钮

### 6.2 思维链可视化

**树状结构**：
```
思维链：
  ├─ 🧠 reasoning: 用户想要监听串口数据
  │   └─ 分析：需要指定端口、波特率、持续时间
  ├─ 📋 planning: 制定执行计划
  │   ├─ 步骤 1: 扫描可用串口
  │   ├─ 步骤 2: 启动监听
  │   └─ 步骤 3: 解析数据
  ├─ 🤔 reflection: 检查潜在问题
  │   └─ 注意：需要检查串口权限
  └─ ✅ decision: 使用 serial_monitor 工具
```

**导出格式**：
- Markdown（用于文档）
- JSON（用于持久化）
- 纯文本（用于日志）

### 6.3 语法高亮

**支持语言**：
- C/C++
- Python
- YAML
- JSON
- Makefile
- CMake

**高亮示例**：
```c
// 使用 rich.syntax 渲染
void setup() {
    Serial.begin(115200);  // 初始化串口
    pinMode(LED_PIN, OUTPUT);
}
```

### 6.4 进度反馈

**进度条类型**：
- **确定进度**：显示百分比（编译、烧录）
- **不确定进度**：显示旋转动画（串口监听）

**进度信息**：
- 当前步骤描述
- 已完成/总数
- 预计剩余时间（可选）

---

## 七、性能优化

### 7.1 启动性能

**目标**：启动时间 < 2 秒

**优化措施**：
- 延迟加载：工具、技能、知识库按需加载
- 缓存：配置文件、知识库索引缓存
- 并行初始化：记忆系统、工具系统并行初始化

### 7.2 工具调用性能

**目标**：工具调用延迟 < 100ms（不含工具执行时间）

**优化措施**：
- 任务创建优化：使用对象池
- 依赖检查优化：缓存依赖图
- 并行执行：独立任务自动并行

### 7.3 上下文压缩性能

**目标**：压缩 1000 条消息 < 1 秒

**优化措施**：
- Token 估算：使用快速估算算法（字符数 / 4）
- 批量压缩：一次性压缩多条消息
- 缓存摘要：相同消息段的摘要缓存

### 7.4 知识库检索性能

**目标**：检索 1000 个文档 < 100ms

**优化措施**：
- 全文索引：使用 Whoosh（BM25F 算法）
- 索引缓存：索引文件持久化
- 增量更新：只更新修改的文档

---

## 八、向后兼容与迁移

### 8.1 兼容性保证

**完全兼容**：
- L1 核心记忆（MEMORY.md、USER.md）
- L2 会话数据库（SQLite schema 不变）
- L3 知识库（文件结构不变）
- 技能文件（YAML 格式不变）

**部分兼容**：
- 配置文件（自动迁移，但建议手动检查）
- 工具接口（新增参数，旧工具仍可用）

**不兼容**：
- 内部 API（任务系统、上下文管理是新增的）

### 8.2 迁移步骤

**自动迁移**：
1. 首次启动时检测旧配置文件
2. 自动转换为新格式
3. 备份旧配置到 `settings.json.bak`
4. 验证新配置

**手动迁移**：
1. 阅读迁移指南文档
2. 检查配置文件中的 API Key 和 Base URL
3. 运行 `sinan config validate` 验证配置
4. 测试核心功能（串口、编译、烧录）

**迁移检查清单**：
- [ ] 配置文件验证通过
- [ ] L1 记忆加载成功
- [ ] L2 会话数据库可访问
- [ ] L3 知识库索引重建成功
- [ ] 所有工具可用
- [ ] LLM 调用正常

### 8.3 回滚方案

**如果升级失败**：
1. 停止司南进程
2. 恢复备份的配置文件
3. 删除新增的模块（`agent/tasks/`、`agent/context/`）
4. 重启司南

**数据安全**：
- 所有数据文件（记忆、会话、知识库）不会被修改
- 配置文件有自动备份
- 检查点文件可以安全删除

---

## 九、测试策略

### 9.1 单元测试

**测试框架**：pytest

**测试范围**：
- 任务系统（Task、TaskManager、TaskExecutor、TaskScheduler）
- 上下文管理（ContextManager、ThinkingChain、MessageCompactor）
- 工具系统（EnhancedToolRegistry、工具元数据）
- 配置管理（ConfigLoader、Pydantic 验证）

**测试示例**：
```python
def test_context_compression():
    """测试上下文压缩"""
    manager = ContextManager(max_tokens=1000, window_size=5)
    
    # 创建 100 条消息
    messages = [
        {"role": "user", "content": "test " * 100}
        for _ in range(100)
    ]
    
    # 压缩
    compressed = manager.compact(messages)
    
    # 验证
    assert len(compressed) < len(messages)
    assert manager._estimate_tokens(compressed) < 1000
```

### 9.2 集成测试

**测试场景**：
- 完整的工具调用链（用户输入 → LLM → 工具调用 → 结果返回）
- 并行任务执行
- 上下文压缩触发
- 配置加载和验证

**测试示例**：
```python
def test_tool_call_chain():
    """测试完整的工具调用链"""
    repl = EnhancedSinanREPL(settings)
    
    # 模拟用户输入
    repl.handle_user_input("监听 /dev/ttyUSB0 串口 10 秒")
    
    # 验证
    assert len(repl.task_manager.tasks) > 0
    assert repl.task_manager.tasks[0].status == TaskStatus.COMPLETED
```

### 9.3 性能测试

**测试指标**：
- 启动时间
- 工具调用延迟
- 上下文压缩时间
- 知识库检索时间
- 内存占用

**测试工具**：
- `pytest-benchmark` - 性能基准测试
- `memory_profiler` - 内存分析
- `py-spy` - CPU 分析

### 9.4 用户验收测试

**测试场景**：
- 串口监听和协议解析
- 固件编译和烧录
- 知识库检索
- 技能蒸馏
- 配置管理

**验收标准**：
- 所有核心功能正常工作
- 性能指标达标
- 用户体验流畅
- 文档完整准确

---

## 十、风险与缓解

### 10.1 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 任务系统复杂度高，开发延期 | 高 | 中 | 分阶段实施，先实现核心功能 |
| 上下文压缩效果不佳 | 中 | 低 | 提供多种压缩策略，可配置 |
| 性能不达标 | 中 | 低 | 提前进行性能测试，及时优化 |
| 第三方依赖冲突 | 低 | 低 | 使用虚拟环境，锁定版本 |

### 10.2 兼容性风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 配置迁移失败 | 高 | 中 | 提供详细的迁移指南和验证工具 |
| 旧工具不兼容 | 中 | 低 | 保留旧工具接口，逐步迁移 |
| 数据丢失 | 高 | 极低 | 自动备份，不修改原始数据 |

### 10.3 用户体验风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 学习曲线陡峭 | 中 | 中 | 提供详细文档和示例 |
| UI 变化过大 | 低 | 低 | 保持核心交互不变 |
| 性能下降 | 高 | 低 | 性能测试，及时优化 |

---

## 十一、成功标准

### 11.1 阶段 1 成功标准

- [ ] 任务系统完整实现，通过单元测试
- [ ] 上下文管理完整实现，压缩率 > 50%
- [ ] 配置验证完整实现，启动时自动检查
- [ ] DeepSeek API 配置问题修复
- [ ] 增强的工具系统（4 个工具）
- [ ] 集成到 REPL，核心功能正常
- [ ] 测试覆盖率 ≥ 60%

### 11.2 阶段 2 成功标准

- [ ] 思维链可视化完整实现
- [ ] 知识库全文索引，检索速度提升 10 倍
- [ ] UI/UX 升级，任务卡片、进度条、语法高亮
- [ ] 横向扩展平台（Nordic nRF、CMake）
- [ ] 技能蒸馏质量评分，过滤率 > 30%
- [ ] 测试覆盖率 ≥ 70%

### 11.3 阶段 3 成功标准

- [ ] 测试覆盖率 ≥ 80%
- [ ] 结构化日志完整实现
- [ ] 插件系统完整实现，支持第三方扩展
- [ ] 调试分析工具（GDB、逻辑分析仪）
- [ ] 完整文档（用户手册、开发者文档、迁移指南）
- [ ] 性能达标（启动 < 2s，工具调用 < 100ms）

### 11.4 整体成功标准

- [ ] 所有阶段目标达成
- [ ] 用户验收测试通过
- [ ] 性能指标达标
- [ ] 文档完整准确
- [ ] 无严重 bug
- [ ] 团队满意度 ≥ 4/5

---

## 十二、后续规划

### 12.1 短期（3 个月内）

- 收集用户反馈，持续优化
- 修复发现的 bug
- 补充文档和示例
- 性能优化

### 12.2 中期（6 个月内）

- 扩展更多平台支持（TI、NXP）
- 增加更多调试工具（JTAG、SWD）
- 优化知识库内容
- 社区建设

### 12.3 长期（1 年内）

- 云端协作功能
- 团队知识共享
- AI 辅助调试
- 自动化测试生成

---

## 附录

### A. 依赖清单

**核心依赖**（必装）：
```
pyyaml>=6.0
prompt_toolkit>=3.0
rich>=13.0
httpx>=0.25
pyserial>=3.5
pydantic>=2.0
```

**可选依赖**（按需安装）：
```
whoosh>=2.7          # 知识库全文索引
structlog>=23.0      # 结构化日志
jsonschema>=4.0      # 配置验证
pytest>=7.0          # 测试框架
pytest-cov>=4.0      # 测试覆盖率
esptool>=4.0         # ESP32 烧录
pyocd>=0.35          # ARM 调试器
pygdbmi>=0.10        # GDB 集成
```

### B. 文件结构

```
sinan-embedded-agent/
├── agent/
│   ├── tasks/              # 任务系统（新增）
│   │   ├── task.py
│   │   ├── manager.py
│   │   ├── executor.py
│   │   ├── scheduler.py
│   │   └── persistence.py
│   ├── context/            # 上下文管理（新增）
│   │   ├── manager.py
│   │   ├── thinking.py
│   │   └── compactor.py
│   ├── config/             # 配置管理（重构）
│   │   ├── models.py
│   │   └── loader.py
│   ├── logging/            # 日志系统（新增）
│   │   ├── config.py
│   │   └── usage.py
│   ├── plugins/            # 插件系统（新增）
│   │   ├── loader.py
│   │   └── interface.py
│   ├── tools/              # 工具系统（增强）
│   │   ├── enhanced_registry.py
│   │   ├── enhanced_serial.py
│   │   └── enhanced_build.py
│   ├── repl/               # REPL（增强）
│   │   ├── enhanced_repl.py
│   │   ├── widgets.py
│   │   └── syntax_highlighter.py
│   ├── memory/             # 记忆系统（增强）
│   │   └── knowledge_index.py
│   └── distill/            # 技能蒸馏（增强）
│       └── quality_scorer.py
├── tests/                  # 测试（新增）
│   ├── test_task_system.py
│   ├── test_context_manager.py
│   ├── test_tool_registry.py
│   └── test_config.py
├── docs/
│   ├── user_manual.md      # 用户手册
│   ├── developer_guide.md  # 开发者指南
│   └── migration_guide.md  # 迁移指南
└── requirements.txt
```

### C. 参考资料

- [Claude Code 源码](https://github.com/anthropics/claude-code)
- [Pydantic 文档](https://docs.pydantic.dev/)
- [Whoosh 文档](https://whoosh.readthedocs.io/)
- [structlog 文档](https://www.structlog.org/)
- [pytest 文档](https://docs.pytest.org/)

---

**文档版本**: 2.0  
**最后更新**: 2026-05-31  
**状态**: 待审核
