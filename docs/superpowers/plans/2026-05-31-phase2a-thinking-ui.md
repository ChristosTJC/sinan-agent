# Phase 2A: 思维链可视化 + UI/UX 升级 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现思维链可视化和 UI/UX 升级，提升用户体验和交互质量

**Architecture:** 
- 思维链系统：ThinkingChain 追踪推理过程，ThinkingRenderer 渲染树状结构
- UI 组件：TaskCard 任务卡片，ProgressBar 进度条，SyntaxHighlighter 代码高亮
- 集成到 REPL：实时显示思维链和任务状态

**Tech Stack:** Python 3.10+, rich (UI), dataclasses (数据结构), pytest (测试)

---

## 文件结构

### 新增文件
- `agent/context/thinking_chain.py` - 思维链追踪和管理
- `agent/repl/thinking_renderer.py` - 思维链可视化渲染
- `agent/repl/widgets.py` - UI 组件（任务卡片、进度条）
- `agent/repl/syntax_highlighter.py` - 代码语法高亮
- `tests/test_thinking_chain.py` - 思维链测试
- `tests/test_widgets.py` - UI 组件测试

### 修改文件
- `agent/repl/repl.py` - 集成思维链和 UI 组件
- `agent/context/__init__.py` - 导出 ThinkingChain

---

## Task 1: 实现 ThinkingChain 核心数据结构

**Files:**
- Create: `agent/context/thinking_chain.py`
- Test: `tests/test_thinking_chain.py`

- [ ] **Step 1: 编写 ThinkingStep 测试**

```python
# tests/test_thinking_chain.py
from agent.context.thinking_chain import ThinkingStep, ThinkingType

def test_thinking_step_creation():
    step = ThinkingStep(
        type=ThinkingType.REASONING,
        content="分析用户需求",
        metadata={"confidence": 0.9}
    )
    assert step.type == ThinkingType.REASONING
    assert step.content == "分析用户需求"
    assert step.metadata["confidence"] == 0.9
    assert step.timestamp is not None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_thinking_chain.py::test_thinking_step_creation -v`
Expected: FAIL with "No module named 'agent.context.thinking_chain'"

- [ ] **Step 3: 实现 ThinkingStep 数据结构**

```python
# agent/context/thinking_chain.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

class ThinkingType(Enum):
    REASONING = "reasoning"
    PLANNING = "planning"
    REFLECTION = "reflection"
    ANALYSIS = "analysis"
    DECISION = "decision"

@dataclass
class ThinkingStep:
    type: ThinkingType
    content: str
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    parent_id: Optional[str] = None
    step_id: str = field(default_factory=lambda: f"step-{datetime.now().timestamp()}")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_thinking_chain.py::test_thinking_step_creation -v`
Expected: PASS

- [ ] **Step 5: 提交 ThinkingStep**

```bash
git add agent/context/thinking_chain.py tests/test_thinking_chain.py
git commit -m "feat(context): 添加 ThinkingStep 数据结构

- 定义 ThinkingType 枚举（5 种思维类型）
- 实现 ThinkingStep dataclass
- 支持元数据和父子关系
- 添加单元测试"
```

---

## Task 2: 实现 ThinkingChain 管理器

**Files:**
- Modify: `agent/context/thinking_chain.py`
- Modify: `tests/test_thinking_chain.py`

- [ ] **Step 1: 编写 ThinkingChain 测试**

```python
# tests/test_thinking_chain.py (追加)
from agent.context.thinking_chain import ThinkingChain

def test_thinking_chain_add_step():
    chain = ThinkingChain(session_id="test-session")
    step_id = chain.add_step(
        type=ThinkingType.REASONING,
        content="分析问题"
    )
    assert len(chain.steps) == 1
    assert chain.steps[0].step_id == step_id

def test_thinking_chain_get_tree():
    chain = ThinkingChain(session_id="test-session")
    root_id = chain.add_step(ThinkingType.REASONING, "根节点")
    child_id = chain.add_step(ThinkingType.PLANNING, "子节点", parent_id=root_id)
    
    tree = chain.get_tree()
    assert len(tree) == 1
    assert tree[0].step_id == root_id
    assert len(tree[0].children) == 1
    assert tree[0].children[0].step_id == child_id
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_thinking_chain.py::test_thinking_chain_add_step -v`
Expected: FAIL

- [ ] **Step 3: 实现 ThinkingChain 类**

```python
# agent/context/thinking_chain.py (追加)
from typing import List

@dataclass
class ThinkingNode:
    step: ThinkingStep
    children: List[ThinkingNode] = field(default_factory=list)

class ThinkingChain:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.steps: List[ThinkingStep] = []
        self.started_at = datetime.now()
    
    def add_step(
        self,
        type: ThinkingType,
        content: str,
        metadata: Optional[dict] = None,
        parent_id: Optional[str] = None
    ) -> str:
        step = ThinkingStep(
            type=type,
            content=content,
            metadata=metadata or {},
            parent_id=parent_id
        )
        self.steps.append(step)
        return step.step_id
    
    def get_tree(self) -> List[ThinkingNode]:
        nodes = {step.step_id: ThinkingNode(step=step) for step in self.steps}
        roots = []
        for step in self.steps:
            if step.parent_id is None:
                roots.append(nodes[step.step_id])
            else:
                if step.parent_id in nodes:
                    nodes[step.parent_id].children.append(nodes[step.step_id])
        return roots
    
    def clear(self) -> None:
        self.steps.clear()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_thinking_chain.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 提交 ThinkingChain**

```bash
git add agent/context/thinking_chain.py tests/test_thinking_chain.py
git commit -m "feat(context): 实现 ThinkingChain 管理器

- 添加 add_step() 方法
- 实现树状结构构建 get_tree()
- 支持父子关系
- 添加单元测试覆盖核心功能"
```

---

## Task 3: 实现 ThinkingRenderer 渲染器

**Files:**
- Create: `agent/repl/thinking_renderer.py`
- Modify: `tests/test_thinking_chain.py`

- [ ] **Step 1: 编写渲染器测试**

```python
# tests/test_thinking_chain.py (追加)
from agent.repl.thinking_renderer import ThinkingRenderer

def test_thinking_renderer_basic():
    chain = ThinkingChain(session_id="test")
    chain.add_step(ThinkingType.REASONING, "分析需求")
    chain.add_step(ThinkingType.DECISION, "决定方案")
    
    renderer = ThinkingRenderer()
    output = renderer.render(chain)
    
    assert "🧠 reasoning" in output
    assert "✅ decision" in output
    assert "分析需求" in output
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_thinking_chain.py::test_thinking_renderer_basic -v`
Expected: FAIL

- [ ] **Step 3: 实现 ThinkingRenderer**

```python
# agent/repl/thinking_renderer.py
from __future__ import annotations
from typing import Any, Optional
from agent.context.thinking_chain import ThinkingChain, ThinkingNode, ThinkingType

THINKING_ICONS = {
    ThinkingType.REASONING: "🧠",
    ThinkingType.PLANNING: "📋",
    ThinkingType.REFLECTION: "🤔",
    ThinkingType.ANALYSIS: "🔍",
    ThinkingType.DECISION: "✅",
}

class ThinkingRenderer:
    def render(self, chain: ThinkingChain, use_rich: bool = True) -> str:
        tree = chain.get_tree()
        if not tree:
            return ""
        
        lines = ["思维链："]
        for i, node in enumerate(tree):
            is_last = (i == len(tree) - 1)
            self._render_node(node, lines, prefix="", is_last=is_last)
        
        return "\n".join(lines)
    
    def _render_node(
        self,
        node: ThinkingNode,
        lines: list[str],
        prefix: str,
        is_last: bool
    ) -> None:
        icon = THINKING_ICONS.get(node.step.type, "•")
        connector = "└─" if is_last else "├─"
        
        lines.append(f"{prefix}{connector} {icon} {node.step.type.value}: {node.step.content}")
        
        child_prefix = prefix + ("   " if is_last else "│  ")
        for i, child in enumerate(node.children):
            child_is_last = (i == len(node.children) - 1)
            self._render_node(child, lines, child_prefix, child_is_last)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_thinking_chain.py::test_thinking_renderer_basic -v`
Expected: PASS

- [ ] **Step 5: 提交 ThinkingRenderer**

```bash
git add agent/repl/thinking_renderer.py tests/test_thinking_chain.py
git commit -m "feat(repl): 实现 ThinkingRenderer 渲染器

- 树状结构可视化
- 支持 5 种思维类型图标
- 递归渲染子节点
- 添加单元测试"
```

---

## Task 4: 实现 TaskCard UI 组件

**Files:**
- Create: `agent/repl/widgets.py`
- Create: `tests/test_widgets.py`

- [ ] **Step 1: 编写 TaskCard 测试**

```python
# tests/test_widgets.py
from agent.repl.widgets import TaskCard, TaskStatus

def test_task_card_pending():
    card = TaskCard(
        name="serial_monitor",
        status=TaskStatus.PENDING,
        description="监听串口"
    )
    output = card.render()
    assert "⏳" in output
    assert "serial_monitor" in output

def test_task_card_with_progress():
    card = TaskCard(
        name="build_firmware",
        status=TaskStatus.RUNNING,
        description="编译固件",
        progress=0.6
    )
    output = card.render()
    assert "⚙️" in output
    assert "60%" in output
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_widgets.py::test_task_card_pending -v`
Expected: FAIL

- [ ] **Step 3: 实现 TaskCard 组件**

```python
# agent/repl/widgets.py
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

STATUS_ICONS = {
    TaskStatus.PENDING: "⏳",
    TaskStatus.RUNNING: "⚙️",
    TaskStatus.COMPLETED: "✓",
    TaskStatus.FAILED: "✗",
}

@dataclass
class TaskCard:
    name: str
    status: TaskStatus
    description: str
    progress: Optional[float] = None
    details: Optional[str] = None
    
    def render(self, width: int = 50) -> str:
        icon = STATUS_ICONS[self.status]
        header = f"{icon} {self.name}"
        
        lines = [
            "┌─ " + header + " " + "─" * (width - len(header) - 4) + "┐",
            f"│ {self.description}" + " " * (width - len(self.description) - 3) + "│",
        ]
        
        if self.progress is not None and self.status == TaskStatus.RUNNING:
            bar_width = width - 6
            filled = int(bar_width * self.progress)
            bar = "█" * filled + "░" * (bar_width - filled)
            pct = f"{int(self.progress * 100)}%"
            lines.append(f"│ {bar} {pct}" + " " * (width - len(bar) - len(pct) - 4) + "│")
        
        lines.append("└" + "─" * (width - 2) + "┘")
        return "\n".join(lines)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_widgets.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 提交 TaskCard**

```bash
git add agent/repl/widgets.py tests/test_widgets.py
git commit -m "feat(repl): 实现 TaskCard UI 组件

- 支持 4 种任务状态
- 进度条可视化
- 可折叠详情
- 添加单元测试"
```

---

## Task 5: 实现 SyntaxHighlighter 代码高亮

**Files:**
- Create: `agent/repl/syntax_highlighter.py`
- Modify: `tests/test_widgets.py`

- [ ] **Step 1: 编写高亮器测试**

```python
# tests/test_widgets.py (追加)
from agent.repl.syntax_highlighter import SyntaxHighlighter

def test_syntax_highlighter_c():
    code = '''void setup() {
    Serial.begin(115200);
}'''
    highlighter = SyntaxHighlighter()
    output = highlighter.highlight(code, language="c")
    assert "void" in output
    assert "setup" in output

def test_syntax_highlighter_auto_detect():
    code = "def hello():\n    print('world')"
    highlighter = SyntaxHighlighter()
    output = highlighter.highlight(code)
    assert "def" in output
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_widgets.py::test_syntax_highlighter_c -v`
Expected: FAIL

- [ ] **Step 3: 实现 SyntaxHighlighter**

```python
# agent/repl/syntax_highlighter.py
from __future__ import annotations
from typing import Optional

try:
    from rich.syntax import Syntax
    from rich.console import Console
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

class SyntaxHighlighter:
    LANGUAGE_MAP = {
        "c": "c",
        "cpp": "cpp",
        "python": "python",
        "py": "python",
        "yaml": "yaml",
        "json": "json",
        "cmake": "cmake",
        "makefile": "makefile",
    }
    
    def highlight(
        self,
        code: str,
        language: Optional[str] = None,
        theme: str = "monokai"
    ) -> str:
        if not HAS_RICH:
            return code
        
        if language is None:
            language = self._detect_language(code)
        
        lang = self.LANGUAGE_MAP.get(language.lower(), "text")
        
        syntax = Syntax(code, lang, theme=theme, line_numbers=False)
        console = Console()
        
        with console.capture() as capture:
            console.print(syntax)
        
        return capture.get()
    
    def _detect_language(self, code: str) -> str:
        if "def " in code or "import " in code:
            return "python"
        if "void " in code or "#include" in code:
            return "c"
        if "{" in code and "}" in code:
            return "json"
        return "text"
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_widgets.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: 提交 SyntaxHighlighter**

```bash
git add agent/repl/syntax_highlighter.py tests/test_widgets.py
git commit -m "feat(repl): 实现 SyntaxHighlighter 代码高亮

- 支持 C/C++/Python/YAML/JSON/CMake
- 自动语言检测
- 基于 rich.syntax
- 添加单元测试"
```

---

## Task 6: 集成到 REPL

**Files:**
- Modify: `agent/repl/repl.py`
- Modify: `agent/context/__init__.py`

- [ ] **Step 1: 更新 context 模块导出**

```python
# agent/context/__init__.py
from .manager import ContextManager
from .compactor import MessageCompactor
from .thinking_chain import ThinkingChain, ThinkingStep, ThinkingType

__all__ = [
    "ContextManager",
    "MessageCompactor",
    "ThinkingChain",
    "ThinkingStep",
    "ThinkingType",
]
```

- [ ] **Step 2: 在 REPL 中初始化思维链**

```python
# agent/repl/repl.py (在 __init__ 中添加)
from agent.context import ThinkingChain
from agent.repl.thinking_renderer import ThinkingRenderer
from agent.repl.widgets import TaskCard, TaskStatus

class SinanREPL:
    def __init__(self, ...):
        # ... 现有代码 ...
        
        # 思维链系统
        self.thinking_chain: Optional[ThinkingChain] = None
        self.thinking_renderer = ThinkingRenderer()
```

- [ ] **Step 3: 在消息处理中启动思维会话**

```python
# agent/repl/repl.py (在 _handle_user_message 中)
def _handle_user_message(self, user_input: str):
    # ... 现有代码 ...
    
    # 启动思维会话
    session_id = f"session-{datetime.now().timestamp()}"
    self.thinking_chain = ThinkingChain(session_id=session_id)
    
    # 调用 LLM
    # ...
```

- [ ] **Step 4: 在工具调用中使用 TaskCard**

```python
# agent/repl/repl.py (在 _execute_single_tool 中)
def _execute_single_tool(self, tool_call, status_callback, approval_callback):
    name = tool_call.name
    
    # 创建任务卡片
    card = TaskCard(
        name=name,
        status=TaskStatus.RUNNING,
        description=f"执行 {name}..."
    )
    print(card.render())
    
    # 执行工具
    # ... 现有代码 ...
```

- [ ] **Step 5: 手动测试集成**

Run: `python3 -m agent.cli`

测试：
1. 输入查询，观察思维链显示
2. 触发工具调用，观察任务卡片
3. 检查代码块是否高亮

- [ ] **Step 6: 提交 REPL 集成**

```bash
git add agent/repl/repl.py agent/context/__init__.py
git commit -m "feat(repl): 集成思维链和 UI 组件

- 初始化 ThinkingChain 和 ThinkingRenderer
- 工具调用使用 TaskCard 显示
- 代码块自动语法高亮
- 手动测试通过"
```

---

## Task 7: 运行完整测试套件

**Files:**
- Test: 所有测试

- [ ] **Step 1: 运行所有单元测试**

Run: `python3 -m pytest tests/ -v --cov=agent --cov-report=term-missing`

Expected: 所有测试通过，新增模块覆盖率 ≥ 70%

- [ ] **Step 2: 检查覆盖率**

查看覆盖率报告，确保：
- `agent/context/thinking_chain.py` ≥ 80%
- `agent/repl/thinking_renderer.py` ≥ 70%
- `agent/repl/widgets.py` ≥ 70%
- `agent/repl/syntax_highlighter.py` ≥ 60%

- [ ] **Step 3: 修复失败的测试**

如果有测试失败，分析原因并修复。

- [ ] **Step 4: 提交测试修复**

```bash
git add tests/
git commit -m "test: Phase 2A 测试完成

- 所有单元测试通过
- 新增模块覆盖率 ≥ 70%"
```

---

## Phase 2A 完成检查清单

- [ ] ThinkingChain 完整实现（追踪、树状结构）
- [ ] ThinkingRenderer 完整实现（可视化渲染）
- [ ] TaskCard UI 组件（4 种状态、进度条）
- [ ] SyntaxHighlighter 代码高亮（6 种语言）
- [ ] 集成到 REPL 主循环
- [ ] 单元测试覆盖率 ≥ 70%
- [ ] 手动测试通过
- [ ] 所有代码已提交到 git

---

## 执行建议

**预计时间**: 3-5 天

**执行顺序**:
1. Task 1-2: ThinkingChain 核心（1 天）
2. Task 3: ThinkingRenderer 渲染（0.5 天）
3. Task 4-5: UI 组件（1-1.5 天）
4. Task 6: REPL 集成（0.5-1 天）
5. Task 7: 测试和验证（0.5 天）

**注意事项**:
- 每个 Task 完成后立即提交
- 保持测试通过
- 遇到问题及时调整计划
