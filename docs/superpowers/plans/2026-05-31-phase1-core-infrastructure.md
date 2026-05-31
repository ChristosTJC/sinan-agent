# 司南 2.0 阶段 1：核心基础设施实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立任务系统、上下文管理、配置验证等核心基础设施，解决当前核心痛点

**Architecture:** 新增任务编排层（Task/TaskManager/TaskExecutor/TaskScheduler）和上下文管理层（ContextManager/ThinkingChain/MessageCompactor），重构配置管理为 Pydantic 模型，增强工具系统元数据

**Tech Stack:** Python 3.10+, Pydantic 2.0+, pytest, structlog (可选)

---

## 文件结构规划

### 新增文件

**任务系统** (`agent/tasks/`):
- `agent/tasks/__init__.py` - 模块导出
- `agent/tasks/task.py` - Task 类、TaskStatus、TaskType、TaskResult
- `agent/tasks/manager.py` - TaskManager（任务注册、依赖管理）
- `agent/tasks/executor.py` - TaskExecutor（同步/异步执行）
- `agent/tasks/scheduler.py` - TaskScheduler（依赖调度）
- `agent/tasks/persistence.py` - TaskPersistence（断点续传）

**上下文管理** (`agent/context/`):
- `agent/context/__init__.py` - 模块导出
- `agent/context/manager.py` - ContextManager（滑动窗口、自动压缩）
- `agent/context/thinking.py` - ThinkingChain（思维链追踪）
- `agent/context/compactor.py` - MessageCompactor（消息压缩）

**配置管理** (`agent/config/`):
- `agent/config/models.py` - Pydantic 模型定义
- `agent/config/loader.py` - 配置加载器（带验证）

**工具增强** (`agent/tools/`):
- `agent/tools/enhanced_registry.py` - EnhancedToolRegistry
- `agent/tools/enhanced_serial.py` - 增强的串口工具
- `agent/tools/enhanced_build.py` - 增强的编译工具

**测试** (`tests/`):
- `tests/test_task_system.py` - 任务系统测试
- `tests/test_context_manager.py` - 上下文管理测试
- `tests/test_config.py` - 配置管理测试
- `tests/test_tool_registry.py` - 工具注册测试

### 修改文件

- `agent/repl/repl.py` - 集成任务系统和上下文管理
- `agent/config.py` - 迁移到新的配置加载器
- `requirements.txt` - 添加新依赖

---

## Task 1: 任务系统核心数据结构

**Files:**
- Create: `agent/tasks/__init__.py`
- Create: `agent/tasks/task.py`
- Test: `tests/test_task_system.py`

- [ ] **Step 1: 创建任务模块初始化文件**

```python
# agent/tasks/__init__.py
"""任务编排系统"""

from agent.tasks.task import Task, TaskStatus, TaskType, TaskResult

__all__ = ["Task", "TaskStatus", "TaskType", "TaskResult"]
```

- [ ] **Step 2: 编写 Task 类的失败测试**

```python
# tests/test_task_system.py
import pytest
from datetime import datetime
from agent.tasks.task import Task, TaskStatus, TaskType, TaskResult


def test_task_creation():
    """测试任务创建"""
    task = Task(
        id="task-001",
        name="test_task",
        type=TaskType.TOOL_CALL,
        status=TaskStatus.PENDING,
        executor=lambda: "result",
        args={"arg1": "value1"},
        dependencies=[],
        children=[],
        result=None,
        created_at=datetime.now(),
        started_at=None,
        completed_at=None,
        progress=0.0,
        checkpoint_data=None,
    )
    
    assert task.id == "task-001"
    assert task.status == TaskStatus.PENDING
    assert task.progress == 0.0


def test_task_duration():
    """测试任务时长计算"""
    task = Task(
        id="task-002",
        name="test_task",
        type=TaskType.TOOL_CALL,
        status=TaskStatus.COMPLETED,
        executor=lambda: "result",
        args={},
        dependencies=[],
        children=[],
        result=None,
        created_at=datetime(2026, 5, 31, 10, 0, 0),
        started_at=datetime(2026, 5, 31, 10, 0, 5),
        completed_at=datetime(2026, 5, 31, 10, 0, 15),
        progress=1.0,
        checkpoint_data=None,
    )
    
    assert task.duration() == 10.0
```

- [ ] **Step 3: 运行测试验证失败**

Run: `pytest tests/test_task_system.py::test_task_creation -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.tasks.task'"


- [ ] **Step 4: 实现 Task 类和枚举类型**

```python
# agent/tasks/task.py
"""任务实体定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(Enum):
    """任务类型"""
    TOOL_CALL = "tool_call"
    LLM_INFERENCE = "llm_inference"
    THINKING = "thinking"
    COMPOSITE = "composite"


@dataclass
class TaskResult:
    """任务执行结果"""
    success: bool
    output: Any
    error: Optional[str] = None
    compressed: bool = False


@dataclass
class Task:
    """任务实体"""
    id: str
    name: str
    type: TaskType
    status: TaskStatus
    
    executor: Optional[Callable]
    args: dict
    
    dependencies: list[str]
    children: list['Task']
    
    result: Optional[TaskResult]
    
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    progress: float
    
    checkpoint_data: Optional[dict] = None
    
    def duration(self) -> float:
        """计算任务执行时长（秒）"""
        if self.started_at is None or self.completed_at is None:
            return 0.0
        return (self.completed_at - self.started_at).total_seconds()
    
    def compress_result(self, max_chars: int = 400) -> str:
        """压缩结果输出（保留头尾各 max_chars/2 字符）"""
        if self.result is None or self.result.output is None:
            return ""
        
        output_str = str(self.result.output)
        if len(output_str) <= max_chars:
            return output_str
        
        half = max_chars // 2
        return f"{output_str[:half]}\n... (已截断 {len(output_str) - max_chars} 字符) ...\n{output_str[-half:]}"
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/test_task_system.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: 提交任务核心数据结构**

```bash
git add agent/tasks/__init__.py agent/tasks/task.py tests/test_task_system.py
git commit -m "feat(tasks): 添加任务核心数据结构

- 添加 Task 类、TaskStatus、TaskType、TaskResult
- 支持任务时长计算和结果压缩
- 添加单元测试覆盖核心功能"
```

---

## Task 2: TaskManager 实现

**Files:**
- Create: `agent/tasks/manager.py`
- Modify: `agent/tasks/__init__.py`
- Test: `tests/test_task_system.py`

- [ ] **Step 1: 编写 TaskManager 的失败测试**

```python
# tests/test_task_system.py (追加)

from agent.tasks.manager import TaskManager


def test_task_manager_create_task():
    """测试任务创建"""
    manager = TaskManager()
    
    task = manager.create_task(
        name="test_tool",
        type=TaskType.TOOL_CALL,
        executor=lambda: "result",
        args={"port": "/dev/ttyUSB0"},
        dependencies=[],
    )
    
    assert task.id in manager.tasks
    assert task.status == TaskStatus.PENDING
    assert len(manager.tasks) == 1


def test_task_manager_dependencies():
    """测试任务依赖管理"""
    manager = TaskManager()
    
    task_a = manager.create_task("task_a", TaskType.TOOL_CALL, lambda: "A", {}, [])
    task_b = manager.create_task("task_b", TaskType.TOOL_CALL, lambda: "B", {}, [task_a.id])
    
    ready_tasks = manager.get_ready_tasks()
    assert task_a.id in [t.id for t in ready_tasks]
    assert task_b.id not in [t.id for t in ready_tasks]
    
    # 标记 task_a 完成
    manager.update_status(task_a.id, TaskStatus.COMPLETED)
    
    ready_tasks = manager.get_ready_tasks()
    assert task_b.id in [t.id for t in ready_tasks]


def test_task_manager_circular_dependency():
    """测试循环依赖检测"""
    manager = TaskManager()
    
    task_a = manager.create_task("task_a", TaskType.TOOL_CALL, lambda: "A", {}, [])
    task_b = manager.create_task("task_b", TaskType.TOOL_CALL, lambda: "B", {}, [task_a.id])
    
    # 尝试创建循环依赖
    with pytest.raises(ValueError, match="循环依赖"):
        manager.create_task("task_c", TaskType.TOOL_CALL, lambda: "C", {}, [task_b.id, task_a.id])
        manager.update_dependencies(task_a.id, [task_b.id])
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_task_system.py::test_task_manager_create_task -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.tasks.manager'"


- [ ] **Step 3: 实现 TaskManager**

```python
# agent/tasks/manager.py
"""任务管理器"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable, Optional

from agent.tasks.task import Task, TaskStatus, TaskType


class TaskManager:
    """任务管理器 - 负责任务注册、查询、依赖管理"""
    
    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.task_graph: dict[str, list[str]] = {}  # 依赖图（邻接表）
    
    def create_task(
        self,
        name: str,
        type: TaskType,
        executor: Optional[Callable],
        args: dict,
        dependencies: list[str],
    ) -> Task:
        """创建任务"""
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        
        # 检查循环依赖
        if self._has_circular_dependency(task_id, dependencies):
            raise ValueError(f"检测到循环依赖: {task_id} -> {dependencies}")
        
        task = Task(
            id=task_id,
            name=name,
            type=type,
            status=TaskStatus.PENDING,
            executor=executor,
            args=args,
            dependencies=dependencies,
            children=[],
            result=None,
            created_at=datetime.now(),
            started_at=None,
            completed_at=None,
            progress=0.0,
            checkpoint_data=None,
        )
        
        self.tasks[task_id] = task
        self.task_graph[task_id] = dependencies
        
        return task
    
    def get_ready_tasks(self) -> list[Task]:
        """获取所有就绪的任务（依赖已满足）"""
        ready = []
        for task_id, task in self.tasks.items():
            if task.status != TaskStatus.PENDING:
                continue
            
            # 检查所有依赖是否完成
            deps_completed = all(
                self.tasks[dep_id].status == TaskStatus.COMPLETED
                for dep_id in task.dependencies
                if dep_id in self.tasks
            )
            
            if deps_completed:
                ready.append(task)
        
        return ready
    
    def get_blocked_tasks(self) -> list[Task]:
        """获取所有被阻塞的任务"""
        blocked = []
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING and task not in self.get_ready_tasks():
                blocked.append(task)
        return blocked
    
    def get_task_chain(self, task_id: str) -> list[str]:
        """获取任务的完整依赖链"""
        chain = []
        visited = set()
        
        def dfs(tid: str):
            if tid in visited:
                return
            visited.add(tid)
            
            for dep_id in self.task_graph.get(tid, []):
                dfs(dep_id)
            
            chain.append(tid)
        
        dfs(task_id)
        return chain
    
    def update_status(self, task_id: str, status: TaskStatus) -> None:
        """更新任务状态"""
        if task_id not in self.tasks:
            raise KeyError(f"任务不存在: {task_id}")
        
        self.tasks[task_id].status = status
        
        if status == TaskStatus.RUNNING:
            self.tasks[task_id].started_at = datetime.now()
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            self.tasks[task_id].completed_at = datetime.now()
    
    def update_dependencies(self, task_id: str, dependencies: list[str]) -> None:
        """更新任务依赖"""
        if self._has_circular_dependency(task_id, dependencies):
            raise ValueError(f"检测到循环依赖: {task_id} -> {dependencies}")
        
        self.tasks[task_id].dependencies = dependencies
        self.task_graph[task_id] = dependencies
    
    def _has_circular_dependency(self, task_id: str, dependencies: list[str]) -> bool:
        """检测循环依赖"""
        visited = set()
        
        def dfs(tid: str) -> bool:
            if tid == task_id:
                return True
            if tid in visited:
                return False
            
            visited.add(tid)
            
            for dep_id in self.task_graph.get(tid, []):
                if dfs(dep_id):
                    return True
            
            return False
        
        for dep_id in dependencies:
            if dfs(dep_id):
                return True
        
        return False
```

- [ ] **Step 4: 更新模块导出**

```python
# agent/tasks/__init__.py
"""任务编排系统"""

from agent.tasks.task import Task, TaskStatus, TaskType, TaskResult
from agent.tasks.manager import TaskManager

__all__ = ["Task", "TaskStatus", "TaskType", "TaskResult", "TaskManager"]
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/test_task_system.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: 提交 TaskManager**

```bash
git add agent/tasks/manager.py agent/tasks/__init__.py tests/test_task_system.py
git commit -m "feat(tasks): 添加 TaskManager 任务管理器

- 支持任务创建、查询、依赖管理
- 实现循环依赖检测
- 支持获取就绪任务和阻塞任务
- 添加单元测试覆盖核心功能"
```

---

## Task 3: TaskExecutor 实现

**Files:**
- Create: `agent/tasks/executor.py`
- Modify: `agent/tasks/__init__.py`
- Test: `tests/test_task_system.py`

- [ ] **Step 1: 编写 TaskExecutor 的失败测试**

```python
# tests/test_task_system.py (追加)

from agent.tasks.executor import TaskExecutor
import time


def test_task_executor_sync():
    """测试同步执行任务"""
    manager = TaskManager()
    executor = TaskExecutor()
    
    def mock_tool():
        return "success"
    
    task = manager.create_task("test", TaskType.TOOL_CALL, mock_tool, {}, [])
    
    result = executor.execute(task)
    
    assert result.success is True
    assert result.output == "success"
    assert task.status == TaskStatus.COMPLETED


def test_task_executor_error_handling():
    """测试错误处理"""
    manager = TaskManager()
    executor = TaskExecutor()
    
    def failing_tool():
        raise RuntimeError("Tool failed")
    
    task = manager.create_task("test", TaskType.TOOL_CALL, failing_tool, {}, [])
    
    result = executor.execute(task)
    
    assert result.success is False
    assert "Tool failed" in result.error
    assert task.status == TaskStatus.FAILED


def test_task_executor_parallel():
    """测试并行执行"""
    manager = TaskManager()
    executor = TaskExecutor(max_workers=2)
    
    def slow_tool(duration):
        time.sleep(duration)
        return f"done-{duration}"
    
    task1 = manager.create_task("task1", TaskType.TOOL_CALL, lambda: slow_tool(0.1), {}, [])
    task2 = manager.create_task("task2", TaskType.TOOL_CALL, lambda: slow_tool(0.1), {}, [])
    
    start = time.time()
    results = executor.execute_parallel([task1, task2])
    elapsed = time.time() - start
    
    assert len(results) == 2
    assert all(r.success for r in results)
    assert elapsed < 0.3  # 并行执行应该快于串行
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_task_system.py::test_task_executor_sync -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.tasks.executor'"


- [ ] **Step 3: 实现 TaskExecutor**

```python
# agent/tasks/executor.py
"""任务执行器"""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from agent.tasks.task import Task, TaskResult, TaskStatus


class TaskExecutor:
    """任务执行器 - 负责任务的实际执行"""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self.status_callback: Optional[Callable] = None
        self.progress_callback: Optional[Callable] = None
    
    def execute(self, task: Task) -> TaskResult:
        """同步执行任务"""
        if task.executor is None:
            return TaskResult(
                success=False,
                output=None,
                error="任务没有执行函数",
            )
        
        task.status = TaskStatus.RUNNING
        if self.status_callback:
            self.status_callback(task, TaskStatus.RUNNING)
        
        try:
            output = task.executor(**task.args) if task.args else task.executor()
            
            result = TaskResult(success=True, output=output, error=None)
            task.result = result
            task.status = TaskStatus.COMPLETED
            
            if self.status_callback:
                self.status_callback(task, TaskStatus.COMPLETED)
            
            return result
        
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            
            result = TaskResult(success=False, output=None, error=error_msg)
            task.result = result
            task.status = TaskStatus.FAILED
            
            if self.status_callback:
                self.status_callback(task, TaskStatus.FAILED)
            
            return result
    
    def execute_parallel(self, tasks: list[Task]) -> list[TaskResult]:
        """并行执行多个任务"""
        futures = {}
        
        for task in tasks:
            future = self.thread_pool.submit(self.execute, task)
            futures[future] = task
        
        results = []
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
        
        return results
    
    def set_callbacks(
        self,
        status_callback: Optional[Callable] = None,
        progress_callback: Optional[Callable] = None,
    ) -> None:
        """设置回调函数"""
        self.status_callback = status_callback
        self.progress_callback = progress_callback
    
    def shutdown(self) -> None:
        """关闭线程池"""
        self.thread_pool.shutdown(wait=True)
```

- [ ] **Step 4: 更新模块导出**

```python
# agent/tasks/__init__.py
"""任务编排系统"""

from agent.tasks.task import Task, TaskStatus, TaskType, TaskResult
from agent.tasks.manager import TaskManager
from agent.tasks.executor import TaskExecutor

__all__ = [
    "Task",
    "TaskStatus",
    "TaskType",
    "TaskResult",
    "TaskManager",
    "TaskExecutor",
]
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/test_task_system.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: 提交 TaskExecutor**

```bash
git add agent/tasks/executor.py agent/tasks/__init__.py tests/test_task_system.py
git commit -m "feat(tasks): 添加 TaskExecutor 任务执行器

- 支持同步和并行执行任务
- 实现错误处理和状态回调
- 使用线程池支持并发执行
- 添加单元测试覆盖核心功能"
```

---

## Task 4: TaskScheduler 实现

**Files:**
- Create: `agent/tasks/scheduler.py`
- Modify: `agent/tasks/__init__.py`
- Test: `tests/test_task_system.py`

- [ ] **Step 1: 编写 TaskScheduler 的失败测试**

```python
# tests/test_task_system.py (追加)

from agent.tasks.scheduler import TaskScheduler


def test_task_scheduler_dependency_order():
    """测试依赖顺序执行"""
    manager = TaskManager()
    executor = TaskExecutor()
    scheduler = TaskScheduler(manager, executor)
    
    execution_order = []
    
    def make_tool(name):
        def tool():
            execution_order.append(name)
            return name
        return tool
    
    task_a = manager.create_task("A", TaskType.TOOL_CALL, make_tool("A"), {}, [])
    task_b = manager.create_task("B", TaskType.TOOL_CALL, make_tool("B"), {}, [task_a.id])
    task_c = manager.create_task("C", TaskType.TOOL_CALL, make_tool("C"), {}, [task_b.id])
    
    result = scheduler.run_until_complete(task_c.id)
    
    assert result.success is True
    assert execution_order == ["A", "B", "C"]


def test_task_scheduler_parallel_execution():
    """测试并行执行独立任务"""
    manager = TaskManager()
    executor = TaskExecutor(max_workers=2)
    scheduler = TaskScheduler(manager, executor)
    
    task_a = manager.create_task("A", TaskType.TOOL_CALL, lambda: "A", {}, [])
    task_b = manager.create_task("B", TaskType.TOOL_CALL, lambda: "B", {}, [])
    
    results = scheduler.run_parallel([task_a.id, task_b.id])
    
    assert len(results) == 2
    assert all(r.success for r in results)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_task_system.py::test_task_scheduler_dependency_order -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.tasks.scheduler'"

- [ ] **Step 3: 实现 TaskScheduler**

```python
# agent/tasks/scheduler.py
"""任务调度器"""

from __future__ import annotations

from typing import Optional

from agent.tasks.executor import TaskExecutor
from agent.tasks.manager import TaskManager
from agent.tasks.task import TaskResult, TaskStatus


class TaskScheduler:
    """任务调度器 - 负责任务调度和编排"""
    
    def __init__(self, manager: TaskManager, executor: TaskExecutor):
        self.manager = manager
        self.executor = executor
    
    def schedule(self, task_id: str, priority: int = 0) -> None:
        """调度任务（暂不实现优先级）"""
        if task_id not in self.manager.tasks:
            raise KeyError(f"任务不存在: {task_id}")
    
    def schedule_with_dependencies(self, task_id: str) -> list[str]:
        """调度任务及其依赖链"""
        return self.manager.get_task_chain(task_id)
    
    def run_until_complete(self, task_id: str) -> TaskResult:
        """运行直到指定任务完成"""
        if task_id not in self.manager.tasks:
            raise KeyError(f"任务不存在: {task_id}")
        
        # 获取依赖链
        chain = self.manager.get_task_chain(task_id)
        
        # 按依赖顺序执行
        for tid in chain:
            task = self.manager.tasks[tid]
            
            if task.status == TaskStatus.COMPLETED:
                continue
            
            result = self.executor.execute(task)
            
            if not result.success:
                return result
        
        return self.manager.tasks[task_id].result
    
    def run_parallel(self, task_ids: list[str]) -> list[TaskResult]:
        """并行运行多个独立任务"""
        tasks = [self.manager.tasks[tid] for tid in task_ids]
        
        # 检查任务是否独立（无依赖关系）
        for task in tasks:
            if any(dep_id in task_ids for dep_id in task.dependencies):
                raise ValueError(f"任务 {task.id} 依赖其他待执行任务，无法并行")
        
        return self.executor.execute_parallel(tasks)
```

- [ ] **Step 4: 更新模块导出**

```python
# agent/tasks/__init__.py
"""任务编排系统"""

from agent.tasks.task import Task, TaskStatus, TaskType, TaskResult
from agent.tasks.manager import TaskManager
from agent.tasks.executor import TaskExecutor
from agent.tasks.scheduler import TaskScheduler

__all__ = [
    "Task",
    "TaskStatus",
    "TaskType",
    "TaskResult",
    "TaskManager",
    "TaskExecutor",
    "TaskScheduler",
]
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/test_task_system.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6: 提交 TaskScheduler**

```bash
git add agent/tasks/scheduler.py agent/tasks/__init__.py tests/test_task_system.py
git commit -m "feat(tasks): 添加 TaskScheduler 任务调度器

- 支持依赖链调度和执行
- 支持并行执行独立任务
- 实现 run_until_complete 和 run_parallel
- 添加单元测试覆盖核心功能"
```

---

## Task 5: 上下文管理 - ContextManager

**Files:**
- Create: `agent/context/__init__.py`
- Create: `agent/context/manager.py`
- Test: `tests/test_context_manager.py`

- [ ] **Step 1: 创建上下文模块初始化文件**

```python
# agent/context/__init__.py
"""上下文管理系统"""

from agent.context.manager import ContextManager

__all__ = ["ContextManager"]
```

- [ ] **Step 2: 编写 ContextManager 的失败测试**

```python
# tests/test_context_manager.py
import pytest
from agent.context.manager import ContextManager


def test_context_manager_no_compression():
    """测试不需要压缩的情况"""
    manager = ContextManager(max_tokens=10000, window_size=20)
    
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    
    result = manager.compact(messages)
    
    assert len(result) == len(messages)
    assert result == messages


def test_context_manager_sliding_window():
    """测试滑动窗口压缩"""
    manager = ContextManager(max_tokens=1000, window_size=5)
    
    # 创建 100 条消息
    messages = [
        {"role": "user", "content": "test " * 50}
        for _ in range(100)
    ]
    
    result = manager.compact(messages)
    
    # 应该只保留最近 5 轮对话
    assert len(result) <= 10  # 5 轮 * 2 条消息（user + assistant）


def test_context_manager_system_message_preserved():
    """测试系统消息始终保留"""
    manager = ContextManager(max_tokens=500, window_size=2)
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "test " * 100},
        {"role": "assistant", "content": "response " * 100},
        {"role": "user", "content": "test2 " * 100},
        {"role": "assistant", "content": "response2 " * 100},
    ]
    
    result = manager.compact(messages)
    
    # 系统消息应该始终在第一条
    assert result[0]["role"] == "system"
```

- [ ] **Step 3: 运行测试验证失败**

Run: `pytest tests/test_context_manager.py::test_context_manager_no_compression -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.context.manager'"


- [ ] **Step 4: 实现 ContextManager**

```python
# agent/context/manager.py
"""上下文管理器"""

from __future__ import annotations

from typing import Any, Callable, Optional


class ContextManager:
    """上下文管理器 - 自动压缩历史消息，避免上下文爆炸"""
    
    def __init__(
        self,
        max_tokens: int = 100000,
        window_size: int = 20,
        compressor: Optional[Callable] = None,
    ):
        self.max_tokens = max_tokens
        self.window_size = window_size
        self.compressor = compressor  # LLM 压缩器（可选）
    
    def compact(self, messages: list[dict]) -> list[dict]:
        """压缩消息历史"""
        if not messages:
            return messages
        
        # 估算 token 数量
        total_tokens = self._estimate_tokens(messages)
        
        # 不需要压缩
        if total_tokens <= self.max_tokens:
            return messages
        
        # 分离系统消息、最近消息、旧消息
        system_messages = [m for m in messages if m.get("role") == "system"]
        non_system_messages = [m for m in messages if m.get("role") != "system"]
        
        # 保留最近 window_size 轮对话
        recent_messages = non_system_messages[-self.window_size * 2:]
        old_messages = non_system_messages[:-self.window_size * 2]
        
        # 如果有旧消息，生成摘要
        if old_messages and self.compressor:
            summary = self._summarize_messages(old_messages)
            summary_message = {
                "role": "system",
                "content": f"[历史对话摘要]\n{summary}",
            }
            return system_messages + [summary_message] + recent_messages
        
        # 没有压缩器，直接丢弃旧消息
        return system_messages + recent_messages
    
    def set_compressor(self, compressor: Callable) -> None:
        """设置 LLM 压缩器"""
        self.compressor = compressor
    
    def _estimate_tokens(self, messages: list[dict]) -> int:
        """估算 token 数量（粗略估计：1 token ≈ 4 字符）"""
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return total_chars // 4
    
    def _summarize_messages(self, messages: list[dict]) -> str:
        """用 LLM 摘要消息（需要外部 LLM 调用）"""
        if self.compressor is None:
            return "[无法生成摘要：未配置压缩器]"
        
        try:
            return self.compressor(messages)
        except Exception as e:
            return f"[摘要生成失败: {str(e)}]"
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/test_context_manager.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: 提交 ContextManager**

```bash
git add agent/context/__init__.py agent/context/manager.py tests/test_context_manager.py
git commit -m "feat(context): 添加 ContextManager 上下文管理器

- 实现滑动窗口压缩策略
- 支持 LLM 摘要压缩（可选）
- 系统消息始终保留
- 添加单元测试覆盖核心功能"
```

---

## Task 6: 上下文管理 - MessageCompactor

**Files:**
- Create: `agent/context/compactor.py`
- Modify: `agent/context/__init__.py`
- Test: `tests/test_context_manager.py`

- [ ] **Step 1: 编写 MessageCompactor 的失败测试**

```python
# tests/test_context_manager.py (追加)

from agent.context.compactor import MessageCompactor


def test_message_compactor_generic():
    """测试通用压缩策略"""
    compactor = MessageCompactor()
    
    long_text = "x" * 1000
    result = compactor.compress_tool_result("generic_tool", long_text, max_chars=400)
    
    assert len(result) <= 450  # 400 + 截断提示
    assert "已截断" in result


def test_message_compactor_sensor_data():
    """测试传感器数据压缩"""
    compactor = MessageCompactor()
    
    sensor_data = "\n".join([f"frame {i}: temp=25.{i}, humidity=60.{i}" for i in range(100)])
    result = compactor.compress_tool_result("read_sensor", sensor_data, max_chars=400)
    
    assert len(result) <= 450
    assert "frame 0" in result  # 保留开头
    assert "frame 99" in result  # 保留结尾


def test_message_compactor_build_log():
    """测试编译日志压缩"""
    compactor = MessageCompactor()
    
    build_log = "\n".join([
        "Building project...",
        "Compiling main.c",
        "Compiling utils.c",
        "ERROR: undefined reference to 'foo'",
        "WARNING: unused variable 'bar'",
        "Linking...",
        "Build complete",
    ])
    
    result = compactor.compress_tool_result("build_firmware", build_log, max_chars=200)
    
    # 应该保留错误和警告
    assert "ERROR" in result
    assert "WARNING" in result
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_context_manager.py::test_message_compactor_generic -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.context.compactor'"

- [ ] **Step 3: 实现 MessageCompactor**

```python
# agent/context/compactor.py
"""消息压缩器"""

from __future__ import annotations


class MessageCompactor:
    """消息压缩器 - 智能压缩工具调用结果"""
    
    def __init__(self):
        self.stats = {
            "total_compressed": 0,
            "total_saved_chars": 0,
        }
    
    def compress_tool_result(
        self,
        tool_name: str,
        result: str,
        max_chars: int = 400,
    ) -> str:
        """压缩工具结果"""
        if len(result) <= max_chars:
            return result
        
        # 根据工具类型选择压缩策略
        if "sensor" in tool_name.lower() or "monitor" in tool_name.lower():
            compressed = self._compress_sensor_data(result, max_chars)
        elif "build" in tool_name.lower() or "compile" in tool_name.lower():
            compressed = self._compress_build_log(result, max_chars)
        elif "read" in tool_name.lower() or "file" in tool_name.lower():
            compressed = self._compress_file_content(result, max_chars)
        else:
            compressed = self._compress_generic(result, max_chars)
        
        # 更新统计
        self.stats["total_compressed"] += 1
        self.stats["total_saved_chars"] += len(result) - len(compressed)
        
        return compressed
    
    def compress_message_batch(self, messages: list[dict]) -> list[dict]:
        """批量压缩消息"""
        compressed = []
        for msg in messages:
            if msg.get("role") == "tool" and len(msg.get("content", "")) > 400:
                msg = msg.copy()
                msg["content"] = self.compress_tool_result(
                    msg.get("name", "unknown"),
                    msg["content"],
                    max_chars=400,
                )
            compressed.append(msg)
        return compressed
    
    def get_stats(self) -> dict:
        """获取压缩统计"""
        return self.stats.copy()
    
    def _compress_generic(self, text: str, max_chars: int) -> str:
        """通用压缩策略：保留头尾"""
        half = max_chars // 2
        return f"{text[:half]}\n... (已截断 {len(text) - max_chars} 字符) ...\n{text[-half:]}"
    
    def _compress_sensor_data(self, text: str, max_chars: int) -> str:
        """传感器数据压缩：提取统计信息 + 头尾"""
        lines = text.split("\n")
        
        if len(lines) <= 10:
            return self._compress_generic(text, max_chars)
        
        # 保留前 5 行和后 5 行
        head = "\n".join(lines[:5])
        tail = "\n".join(lines[-5:])
        summary = f"[共 {len(lines)} 帧数据，已截断 {len(lines) - 10} 帧]"
        
        return f"{head}\n{summary}\n{tail}"
    
    def _compress_build_log(self, text: str, max_chars: int) -> str:
        """编译日志压缩：保留错误和警告"""
        lines = text.split("\n")
        
        # 提取错误和警告
        errors = [line for line in lines if "ERROR" in line.upper() or "error:" in line]
        warnings = [line for line in lines if "WARNING" in line.upper() or "warning:" in line]
        
        result_lines = []
        
        if errors:
            result_lines.append(f"[错误 {len(errors)} 个]")
            result_lines.extend(errors[:5])
        
        if warnings:
            result_lines.append(f"[警告 {len(warnings)} 个]")
            result_lines.extend(warnings[:5])
        
        if not errors and not warnings:
            # 没有错误和警告，保留头尾
            return self._compress_generic(text, max_chars)
        
        compressed = "\n".join(result_lines)
        
        if len(compressed) > max_chars:
            return compressed[:max_chars] + "\n... (已截断)"
        
        return compressed
    
    def _compress_file_content(self, text: str, max_chars: int) -> str:
        """文件内容压缩：保留开头和结尾"""
        return self._compress_generic(text, max_chars)
```

- [ ] **Step 4: 更新模块导出**

```python
# agent/context/__init__.py
"""上下文管理系统"""

from agent.context.manager import ContextManager
from agent.context.compactor import MessageCompactor

__all__ = ["ContextManager", "MessageCompactor"]
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/test_context_manager.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: 提交 MessageCompactor**

```bash
git add agent/context/compactor.py agent/context/__init__.py tests/test_context_manager.py
git commit -m "feat(context): 添加 MessageCompactor 消息压缩器

- 实现多种压缩策略（通用、传感器、编译日志、文件）
- 支持批量压缩消息
- 提供压缩统计信息
- 添加单元测试覆盖核心功能"
```

---

## Task 7: 配置管理 - Pydantic 模型

**Files:**
- Create: `agent/config/models.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 编写配置模型的失败测试**

```python
# tests/test_config.py
import pytest
from pydantic import ValidationError
from agent.config.models import (
    SinanSettings,
    ModelConfig,
    ThinkingConfig,
    ToolsConfig,
    ContextConfig,
)


def test_model_config_valid():
    """测试有效的模型配置"""
    config = ModelConfig(
        id="claude-sonnet-4-20250514",
        name="Claude Sonnet 4",
        provider="claude",
        apiKey="sk-ant-api03-xxx",
    )
    
    assert config.id == "claude-sonnet-4-20250514"
    assert config.provider == "claude"


def test_model_config_invalid_api_key():
    """测试无效的 API Key"""
    with pytest.raises(ValidationError):
        ModelConfig(
            id="deepseek-chat",
            name="DeepSeek",
            provider="openai",
            apiKey="invalid-key-format",  # 应该是 sk- 开头
        )


def test_sinan_settings_valid():
    """测试有效的完整配置"""
    settings = SinanSettings(
        availableModels=[
            ModelConfig(
                id="claude-sonnet-4-20250514",
                name="Claude Sonnet 4",
                provider="claude",
                apiKey="sk-ant-api03-xxx",
            )
        ],
        defaultModel="claude-sonnet-4-20250514",
        maxTokens=8000,
        temperature=0.7,
    )
    
    assert len(settings.availableModels) == 1
    assert settings.defaultModel == "claude-sonnet-4-20250514"


def test_sinan_settings_no_models():
    """测试没有模型的配置"""
    with pytest.raises(ValidationError, match="至少需要一个模型"):
        SinanSettings(
            availableModels=[],
            defaultModel="",
        )
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_config.py::test_model_config_valid -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.config.models'"


- [ ] **Step 3: 实现 Pydantic 配置模型（第一部分）**

```python
# agent/config/models.py
"""配置模型定义（使用 Pydantic）"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ThinkingConfig(BaseModel):
    """思考配置"""
    type: str = Field(default="enabled", pattern="^(enabled|disabled)$")
    budgetTokens: int = Field(default=8000, ge=1000, le=50000)


class ModelConfig(BaseModel):
    """模型配置"""
    id: str
    name: str
    provider: str = Field(pattern="^(claude|openai|ollama)$")
    apiKey: Optional[str] = None
    baseURL: Optional[str] = None
    thinking: Optional[ThinkingConfig] = None
    
    @field_validator("apiKey")
    @classmethod
    def validate_api_key(cls, v: Optional[str], info) -> Optional[str]:
        """验证 API Key 格式"""
        if v is None:
            return v
        
        provider = info.data.get("provider")
        
        if provider == "claude" and not v.startswith("sk-ant-"):
            raise ValueError("Claude API Key 必须以 sk-ant- 开头")
        
        if provider == "openai" and not v.startswith("sk-"):
            raise ValueError("OpenAI API Key 必须以 sk- 开头")
        
        return v


class ToolsConfig(BaseModel):
    """工具配置"""
    maxWorkers: int = Field(default=4, ge=1, le=16)
    timeout: int = Field(default=300, ge=10, le=3600)
    dangerousToolsRequireApproval: bool = True


class ContextConfig(BaseModel):
    """上下文配置"""
    maxTokens: int = Field(default=100000, ge=10000, le=200000)
    windowSize: int = Field(default=20, ge=5, le=50)
    enableCompression: bool = True


class MemoryConfig(BaseModel):
    """记忆配置"""
    l1CoreMemoryPath: str = "~/.sinan/memories"
    l2SessionDbPath: str = "~/.sinan/sessions/sessions.db"
    l3KnowledgeBasePath: str = "~/.sinan/knowledge"
    enableFullTextIndex: bool = True


class TaskConfig(BaseModel):
    """任务配置"""
    maxWorkers: int = Field(default=4, ge=1, le=16)
    enableCheckpoint: bool = True
    checkpointPath: str = "~/.sinan/checkpoints"


class SinanSettings(BaseModel):
    """司南完整配置"""
    availableModels: list[ModelConfig]
    defaultModel: str
    maxTokens: int = Field(default=8000, ge=1000, le=100000)
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    task: TaskConfig = Field(default_factory=TaskConfig)
    
    debug: bool = False
    
    @model_validator(mode="after")
    def validate_settings(self) -> "SinanSettings":
        """验证完整配置"""
        if len(self.availableModels) == 0:
            raise ValueError("至少需要一个模型")
        
        # 检查默认模型是否存在
        model_ids = [m.id for m in self.availableModels]
        if self.defaultModel not in model_ids:
            raise ValueError(f"默认模型 {self.defaultModel} 不在可用模型列表中")
        
        # 检查至少有一个模型配置了 API Key（或使用 Ollama）
        has_api_key = any(
            m.apiKey is not None or m.provider == "ollama"
            for m in self.availableModels
        )
        if not has_api_key:
            raise ValueError("至少需要配置一个模型的 API Key（或使用 Ollama）")
        
        return self
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_config.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: 提交配置模型**

```bash
git add agent/config/models.py tests/test_config.py
git commit -m "feat(config): 添加 Pydantic 配置模型

- 实现 SinanSettings、ModelConfig 等配置类
- 添加 API Key 格式验证
- 添加配置完整性验证
- 添加单元测试覆盖核心功能"
```

---

## Task 8: 配置管理 - ConfigLoader

**Files:**
- Create: `agent/config/loader.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 编写 ConfigLoader 的失败测试**

```python
# tests/test_config.py (追加)

import json
import tempfile
from pathlib import Path
from agent.config.loader import ConfigLoader


def test_config_loader_load_valid():
    """测试加载有效配置"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        config_data = {
            "availableModels": [
                {
                    "id": "claude-sonnet-4-20250514",
                    "name": "Claude Sonnet 4",
                    "provider": "claude",
                    "apiKey": "sk-ant-api03-xxx",
                }
            ],
            "defaultModel": "claude-sonnet-4-20250514",
            "maxTokens": 8000,
        }
        json.dump(config_data, f)
        config_path = f.name
    
    try:
        loader = ConfigLoader(config_path)
        settings = loader.load()
        
        assert settings.defaultModel == "claude-sonnet-4-20250514"
        assert len(settings.availableModels) == 1
    finally:
        Path(config_path).unlink()


def test_config_loader_invalid_file():
    """测试加载无效配置文件"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("invalid json")
        config_path = f.name
    
    try:
        loader = ConfigLoader(config_path)
        with pytest.raises(Exception):
            loader.load()
    finally:
        Path(config_path).unlink()


def test_config_loader_validate():
    """测试配置验证"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        config_data = {
            "availableModels": [],  # 无效：没有模型
            "defaultModel": "",
        }
        json.dump(config_data, f)
        config_path = f.name
    
    try:
        loader = ConfigLoader(config_path)
        errors = loader.validate_file(config_path)
        
        assert len(errors) > 0
        assert any("至少需要一个模型" in err for err in errors)
    finally:
        Path(config_path).unlink()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_config.py::test_config_loader_load_valid -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.config.loader'"

- [ ] **Step 3: 实现 ConfigLoader**

```python
# agent/config/loader.py
"""配置加载器"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from agent.config.models import SinanSettings


class ConfigLoader:
    """配置加载器 - 负责加载、验证、保存配置"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._find_config_file()
    
    def load(self) -> SinanSettings:
        """加载并验证配置"""
        if not Path(self.config_path).exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        
        with open(self.config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        
        try:
            settings = SinanSettings(**config_data)
            return settings
        except ValidationError as e:
            raise ValueError(f"配置验证失败:\n{e}")
    
    def save(self, settings: SinanSettings) -> None:
        """保存配置"""
        config_data = settings.model_dump(exclude_none=True)
        
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
    
    def validate_file(self, filepath: str) -> list[str]:
        """验证配置文件（不加载）"""
        errors = []
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            
            SinanSettings(**config_data)
        
        except json.JSONDecodeError as e:
            errors.append(f"JSON 解析错误: {str(e)}")
        
        except ValidationError as e:
            for error in e.errors():
                field = " -> ".join(str(loc) for loc in error["loc"])
                errors.append(f"{field}: {error['msg']}")
        
        except Exception as e:
            errors.append(f"未知错误: {str(e)}")
        
        return errors
    
    def _find_config_file(self) -> str:
        """查找配置文件"""
        candidates = [
            Path.home() / ".sinan" / "settings.json",
            Path.cwd() / "settings.json",
            Path.cwd() / "config.defaults.yaml",
        ]
        
        for path in candidates:
            if path.exists():
                return str(path)
        
        raise FileNotFoundError("未找到配置文件")
    
    def _create_default(self) -> SinanSettings:
        """创建默认配置"""
        return SinanSettings(
            availableModels=[],
            defaultModel="",
            maxTokens=8000,
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_config.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: 提交 ConfigLoader**

```bash
git add agent/config/loader.py tests/test_config.py
git commit -m "feat(config): 添加 ConfigLoader 配置加载器

- 支持加载、验证、保存配置
- 自动查找配置文件
- 提供详细的验证错误信息
- 添加单元测试覆盖核心功能"
```

---

## Task 9: 增强工具注册 - EnhancedToolRegistry

**Files:**
- Create: `agent/tools/enhanced_registry.py`
- Test: `tests/test_tool_registry.py`

- [ ] **Step 1: 编写 EnhancedToolRegistry 的失败测试**

```python
# tests/test_tool_registry.py
import pytest
from agent.tools.enhanced_registry import (
    EnhancedToolRegistry,
    ToolMetadata,
    ToolCategory,
    DangerLevel,
)


def test_tool_registry_register():
    """测试工具注册"""
    registry = EnhancedToolRegistry()
    
    def mock_tool(port: str) -> str:
        return f"Connected to {port}"
    
    metadata = ToolMetadata(
        name="serial_connect",
        description="连接串口",
        category=ToolCategory.HARDWARE,
        danger_level=DangerLevel.SAFE,
    )
    
    registry.register(mock_tool, metadata)
    
    assert "serial_connect" in registry.tools
    assert registry.get_tool("serial_connect") is not None


def test_tool_registry_get_by_category():
    """测试按分类获取工具"""
    registry = EnhancedToolRegistry()
    
    def tool1():
        pass
    
    def tool2():
        pass
    
    registry.register(
        tool1,
        ToolMetadata(
            name="tool1",
            description="Tool 1",
            category=ToolCategory.HARDWARE,
            danger_level=DangerLevel.SAFE,
        ),
    )
    
    registry.register(
        tool2,
        ToolMetadata(
            name="tool2",
            description="Tool 2",
            category=ToolCategory.BUILD,
            danger_level=DangerLevel.SAFE,
        ),
    )
    
    hardware_tools = registry.get_by_category(ToolCategory.HARDWARE)
    
    assert len(hardware_tools) == 1
    assert hardware_tools[0].metadata.name == "tool1"


def test_tool_registry_execute():
    """测试工具执行"""
    registry = EnhancedToolRegistry()
    
    def mock_tool(x: int, y: int) -> int:
        return x + y
    
    metadata = ToolMetadata(
        name="add",
        description="加法",
        category=ToolCategory.DEBUG,
        danger_level=DangerLevel.SAFE,
    )
    
    registry.register(mock_tool, metadata)
    
    result = registry.execute("add", {"x": 1, "y": 2})
    
    assert result == 3
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_tool_registry.py::test_tool_registry_register -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.tools.enhanced_registry'"


- [ ] **Step 3: 实现 EnhancedToolRegistry（第一部分）**

```python
# agent/tools/enhanced_registry.py
"""增强的工具注册系统"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class ToolCategory(Enum):
    """工具分类"""
    HARDWARE = "hardware"
    BUILD = "build"
    DEBUG = "debug"
    MEMORY = "memory"
    FILE = "file"
    NETWORK = "network"


class DangerLevel(Enum):
    """危险等级"""
    SAFE = "safe"
    CAUTION = "caution"
    DANGEROUS = "dangerous"


@dataclass
class ToolMetadata:
    """工具元数据"""
    name: str
    description: str
    category: ToolCategory
    danger_level: DangerLevel
    
    dependencies: list[str] = field(default_factory=list)
    required_packages: list[str] = field(default_factory=list)
    
    estimated_time: float = 0.0
    supports_progress: bool = False
    
    platforms: list[str] = field(default_factory=lambda: ["linux", "darwin", "win32"])
    parameters_schema: Optional[dict] = None
    examples: list[str] = field(default_factory=list)


@dataclass
class ToolWrapper:
    """工具包装器"""
    func: Callable
    metadata: ToolMetadata


class EnhancedToolRegistry:
    """增强的工具注册表"""
    
    def __init__(self):
        self.tools: dict[str, ToolWrapper] = {}
    
    def register(
        self,
        func: Callable,
        metadata: ToolMetadata,
        override: bool = False,
    ) -> None:
        """注册工具"""
        if metadata.name in self.tools and not override:
            raise ValueError(f"工具已存在: {metadata.name}")
        
        wrapper = ToolWrapper(func=func, metadata=metadata)
        self.tools[metadata.name] = wrapper
    
    def get_tool(self, name: str) -> Optional[ToolWrapper]:
        """获取工具"""
        return self.tools.get(name)
    
    def get_by_category(self, category: ToolCategory) -> list[ToolWrapper]:
        """按分类获取工具"""
        return [
            wrapper
            for wrapper in self.tools.values()
            if wrapper.metadata.category == category
        ]
    
    def execute(
        self,
        name: str,
        args: dict,
        approval_callback: Optional[Callable] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Any:
        """执行工具"""
        wrapper = self.get_tool(name)
        if wrapper is None:
            raise KeyError(f"工具不存在: {name}")
        
        # 危险工具需要用户确认
        if wrapper.metadata.danger_level == DangerLevel.DANGEROUS:
            if approval_callback is None:
                raise RuntimeError(f"危险工具 {name} 需要用户确认")
            
            if not approval_callback(name, wrapper.metadata):
                raise RuntimeError(f"用户拒绝执行危险工具: {name}")
        
        # 执行工具
        return wrapper.func(**args)
    
    def validate_args(self, name: str, args: dict) -> list[str]:
        """验证参数（基于 jsonschema）"""
        wrapper = self.get_tool(name)
        if wrapper is None:
            return [f"工具不存在: {name}"]
        
        if wrapper.metadata.parameters_schema is None:
            return []  # 没有 schema，跳过验证
        
        # TODO: 实现 jsonschema 验证
        return []
    
    def to_openai_format(self) -> list[dict]:
        """转换为 OpenAI tool calling 格式"""
        tools = []
        
        for wrapper in self.tools.values():
            tool_def = {
                "type": "function",
                "function": {
                    "name": wrapper.metadata.name,
                    "description": wrapper.metadata.description,
                },
            }
            
            if wrapper.metadata.parameters_schema:
                tool_def["function"]["parameters"] = wrapper.metadata.parameters_schema
            
            tools.append(tool_def)
        
        return tools
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_tool_registry.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 提交 EnhancedToolRegistry**

```bash
git add agent/tools/enhanced_registry.py tests/test_tool_registry.py
git commit -m "feat(tools): 添加 EnhancedToolRegistry 增强工具注册

- 实现工具元数据管理（分类、危险等级、依赖）
- 支持按分类查询工具
- 支持危险工具确认机制
- 转换为 OpenAI tool calling 格式
- 添加单元测试覆盖核心功能"
```

---

## Task 10: 集成到 REPL - 第一阶段

**Files:**
- Modify: `agent/repl/repl.py`
- Test: 手动测试

- [ ] **Step 1: 阅读现有 REPL 实现**

Read: `agent/repl/repl.py`

- [ ] **Step 2: 在 REPL 中初始化任务系统**

在 `SinanREPL.__init__` 中添加：

```python
# agent/repl/repl.py (修改)

from agent.tasks import TaskManager, TaskExecutor, TaskScheduler

class SinanREPL:
    def __init__(self, settings):
        # ... 现有代码 ...
        
        # 初始化任务系统
        self.task_manager = TaskManager()
        self.task_executor = TaskExecutor(max_workers=4)
        self.task_scheduler = TaskScheduler(self.task_manager, self.task_executor)
```

- [ ] **Step 3: 在 REPL 中初始化上下文管理**

在 `SinanREPL.__init__` 中添加：

```python
from agent.context import ContextManager, MessageCompactor

class SinanREPL:
    def __init__(self, settings):
        # ... 现有代码 ...
        
        # 初始化上下文管理
        self.context_manager = ContextManager(
            max_tokens=100000,
            window_size=20,
        )
        self.message_compactor = MessageCompactor()
```

- [ ] **Step 4: 在消息处理前添加上下文压缩**

在 LLM 调用前添加：

```python
# agent/repl/repl.py (修改)

def _handle_user_message(self, user_input: str):
    # ... 现有代码 ...
    
    # 上下文压缩
    self.messages = self.context_manager.compact(self.messages)
    
    # 调用 LLM
    # ... 现有代码 ...
```

- [ ] **Step 5: 将工具调用转换为 Task**

在工具调用处理中：

```python
# agent/repl/repl.py (修改)

def _handle_tool_calls(self, tool_calls: list):
    for tool_call in tool_calls:
        # 创建任务
        task = self.task_manager.create_task(
            name=tool_call["name"],
            type=TaskType.TOOL_CALL,
            executor=lambda: self._execute_tool(tool_call),
            args={},
            dependencies=[],
        )
        
        # 执行任务
        result = self.task_executor.execute(task)
        
        # 压缩结果
        compressed_output = self.message_compactor.compress_tool_result(
            tool_call["name"],
            str(result.output),
            max_chars=400,
        )
        
        # 添加到消息历史
        self.messages.append({
            "role": "tool",
            "name": tool_call["name"],
            "content": compressed_output,
        })
```

- [ ] **Step 6: 手动测试基本功能**

Run: `python -m agent.cli`

测试：
1. 启动司南
2. 输入简单查询
3. 观察任务系统是否正常工作
4. 检查上下文压缩是否触发

- [ ] **Step 7: 提交 REPL 集成**

```bash
git add agent/repl/repl.py
git commit -m "feat(repl): 集成任务系统和上下文管理

- 初始化 TaskManager、TaskExecutor、TaskScheduler
- 初始化 ContextManager、MessageCompactor
- 工具调用转换为 Task 执行
- 自动压缩工具结果和上下文
- 手动测试通过"
```

---

## Task 11: 更新依赖和文档

**Files:**
- Modify: `requirements.txt`
- Create: `docs/migration_guide_v2.md`

- [ ] **Step 1: 更新 requirements.txt**

```txt
# requirements.txt (追加)

# 核心依赖
pydantic>=2.0.0
pytest>=7.0.0
pytest-cov>=4.0.0

# 可选依赖（阶段 2）
# whoosh>=2.7.4
# structlog>=23.0.0
```

- [ ] **Step 2: 安装新依赖**

Run: `pip install -r requirements.txt`

- [ ] **Step 3: 创建迁移指南**

```markdown
# docs/migration_guide_v2.md

# 司南 2.0 迁移指南

## 概述

司南 2.0 引入了任务系统、上下文管理等核心基础设施，提升了长工具调用链的稳定性和性能。

## 兼容性

### 完全兼容
- L1 核心记忆（MEMORY.md、USER.md）
- L2 会话数据库（SQLite）
- L3 知识库（文件结构）
- 技能文件（YAML 格式）

### 部分兼容
- 配置文件（需要迁移）

## 配置迁移

### 自动迁移

首次启动时，司南会自动检测旧配置并转换为新格式：

```bash
python -m agent.cli
```

### 手动迁移

如果自动迁移失败，请手动更新配置文件：

**旧格式** (`settings.json`):
```json
{
  "defaultModel": "claude-sonnet-4-20250514",
  "availableModels": [...]
}
```

**新格式** (`settings.json`):
```json
{
  "defaultModel": "claude-sonnet-4-20250514",
  "availableModels": [...],
  "tools": {
    "maxWorkers": 4,
    "timeout": 300
  },
  "context": {
    "maxTokens": 100000,
    "windowSize": 20
  }
}
```

### 验证配置

```bash
python -m agent.cli config validate
```

## 新功能

### 任务系统

工具调用现在通过任务系统执行，支持：
- 依赖管理
- 并行执行
- 断点续传

### 上下文管理

自动压缩历史消息，避免上下文爆炸：
- 滑动窗口（保留最近 20 轮）
- 智能压缩工具结果

## 已知问题

- 暂不支持断点续传（阶段 1 未实现 TaskPersistence）
- 思维链可视化需要等待阶段 2

## 回滚

如果遇到问题，可以回滚到 v1：

```bash
git checkout v1.0
pip install -r requirements.txt
```
```

- [ ] **Step 4: 提交依赖和文档**

```bash
git add requirements.txt docs/migration_guide_v2.md
git commit -m "docs: 更新依赖和迁移指南

- 添加 pydantic、pytest 依赖
- 创建迁移指南文档
- 说明兼容性和新功能"
```

---

## Task 12: 运行完整测试套件

**Files:**
- Test: 所有测试

- [ ] **Step 1: 运行所有单元测试**

Run: `pytest tests/ -v --cov=agent --cov-report=term-missing`

Expected: 所有测试通过，覆盖率 ≥ 60%

- [ ] **Step 2: 检查测试覆盖率**

查看覆盖率报告，确保核心模块覆盖率达标：
- `agent/tasks/` ≥ 70%
- `agent/context/` ≥ 70%
- `agent/config/` ≥ 60%
- `agent/tools/enhanced_registry.py` ≥ 60%

- [ ] **Step 3: 修复失败的测试**

如果有测试失败，分析原因并修复。

- [ ] **Step 4: 提交测试修复**

```bash
git add tests/
git commit -m "test: 修复测试并提升覆盖率

- 所有单元测试通过
- 覆盖率达到 60%+"
```

---

## 阶段 1 完成检查清单

- [ ] 任务系统完整实现（Task、TaskManager、TaskExecutor、TaskScheduler）
- [ ] 上下文管理完整实现（ContextManager、MessageCompactor）
- [ ] 配置验证完整实现（Pydantic 模型、ConfigLoader）
- [ ] 增强的工具系统（EnhancedToolRegistry）
- [ ] 集成到 REPL 主循环
- [ ] 单元测试覆盖率 ≥ 60%
- [ ] 迁移指南文档
- [ ] 所有代码已提交到 git

---

## 执行建议

**预计时间**: 1-2 周

**执行顺序**:
1. Task 1-4: 任务系统（3-4 天）
2. Task 5-6: 上下文管理（2-3 天）
3. Task 7-8: 配置管理（2 天）
4. Task 9: 工具注册（1 天）
5. Task 10: REPL 集成（1-2 天）
6. Task 11-12: 依赖、文档、测试（1 天）

**注意事项**:
- 每个 Task 完成后立即提交
- 保持测试通过
- 遇到问题及时调整计划

