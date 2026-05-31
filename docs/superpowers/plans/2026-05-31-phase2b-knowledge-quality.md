# Phase 2B: 知识库全文索引 + 技能蒸馏质量评分 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现知识库全文索引（Whoosh）和技能蒸馏质量评分，提升检索速度和技能质量

**Architecture:** 
- 知识库索引：KnowledgeIndex 基于 Whoosh 实现 BM25F 全文检索
- 质量评分：QualityScorer 评估技能完整性、可复用性、清晰度
- 增量更新：支持添加、更新、删除文档，自动重建索引

**Tech Stack:** Python 3.10+, Whoosh (全文索引), dataclasses, pytest

---

## 文件结构

### 新增文件
- `agent/memory/knowledge_index.py` - Whoosh 全文索引
- `agent/distill/quality_scorer.py` - 技能质量评分器
- `tests/test_knowledge_index.py` - 知识库索引测试
- `tests/test_quality_scorer.py` - 质量评分测试

### 修改文件
- `agent/memory/__init__.py` - 导出 KnowledgeIndex
- `agent/distill/__init__.py` - 导出 QualityScorer
- `agent/cli.py` - 添加索引重建命令

---

## Task 1: 实现 KnowledgeIndex 核心结构

**Files:**
- Create: `agent/memory/knowledge_index.py`
- Create: `tests/test_knowledge_index.py`

- [ ] **Step 1: 编写索引初始化测试**

```python
# tests/test_knowledge_index.py
import tempfile
import shutil
from pathlib import Path
from agent.memory.knowledge_index import KnowledgeIndex, DocumentType

def test_knowledge_index_init():
    with tempfile.TemporaryDirectory() as tmpdir:
        index = KnowledgeIndex(index_dir=tmpdir)
        assert index.index_dir == Path(tmpdir)
        assert index.is_initialized()

def test_knowledge_index_create_schema():
    with tempfile.TemporaryDirectory() as tmpdir:
        index = KnowledgeIndex(index_dir=tmpdir)
        # 验证 schema 包含必需字段
        schema = index.get_schema()
        assert "doc_id" in schema.names()
        assert "title" in schema.names()
        assert "content" in schema.names()
        assert "doc_type" in schema.names()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_knowledge_index.py::test_knowledge_index_init -v`
Expected: FAIL with "No module named 'agent.memory.knowledge_index'"

- [ ] **Step 3: 实现 KnowledgeIndex 基础结构**

```python
# agent/memory/knowledge_index.py
from __future__ import annotations
from pathlib import Path
from enum import Enum
from typing import Optional, List, Dict, Any

try:
    from whoosh import index
    from whoosh.fields import Schema, TEXT, ID, KEYWORD, STORED
    from whoosh.qparser import MultifieldParser, QueryParser
    from whoosh.analysis import StemmingAnalyzer
    HAS_WHOOSH = True
except ImportError:
    HAS_WHOOSH = False

class DocumentType(Enum):
    MCU = "mcu"
    PROTOCOL = "protocol"
    SENSOR = "sensor"
    ERROR_CODE = "error_code"
    BOARD = "board"
    GENERAL = "general"

class KnowledgeIndex:
    def __init__(self, index_dir: str | Path):
        if not HAS_WHOOSH:
            raise RuntimeError("Whoosh 未安装，请运行: pip install whoosh")
        
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        
        if not self.is_initialized():
            self._create_index()
        
        self.ix = index.open_dir(str(self.index_dir))
    
    def is_initialized(self) -> bool:
        return index.exists_in(str(self.index_dir))
    
    def get_schema(self) -> Schema:
        return Schema(
            doc_id=ID(stored=True, unique=True),
            title=TEXT(stored=True, analyzer=StemmingAnalyzer()),
            content=TEXT(stored=True, analyzer=StemmingAnalyzer()),
            doc_type=KEYWORD(stored=True),
            tags=KEYWORD(stored=True, commas=True),
            filepath=STORED(),
            metadata=STORED(),
        )
    
    def _create_index(self) -> None:
        schema = self.get_schema()
        index.create_in(str(self.index_dir), schema)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_knowledge_index.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 提交 KnowledgeIndex 基础**

```bash
git add agent/memory/knowledge_index.py tests/test_knowledge_index.py
git commit -m "feat(memory): 添加 KnowledgeIndex 基础结构

- 定义 DocumentType 枚举
- 实现索引初始化和 schema 定义
- 基于 Whoosh 全文索引
- 添加单元测试"
```

---

## Task 2: 实现文档添加和搜索

**Files:**
- Modify: `agent/memory/knowledge_index.py`
- Modify: `tests/test_knowledge_index.py`

- [ ] **Step 1: 编写文档添加测试**

```python
# tests/test_knowledge_index.py (追加)
def test_add_document():
    with tempfile.TemporaryDirectory() as tmpdir:
        index = KnowledgeIndex(index_dir=tmpdir)
        
        doc_id = index.add_document(
            title="STM32F405 定时器",
            content="STM32F405 有 14 个定时器，最高频率 168MHz",
            doc_type=DocumentType.MCU,
            tags=["stm32", "timer"],
            filepath="/path/to/doc.md"
        )
        
        assert doc_id is not None
        assert index.get_document_count() == 1

def test_search_documents():
    with tempfile.TemporaryDirectory() as tmpdir:
        index = KnowledgeIndex(index_dir=tmpdir)
        
        index.add_document(
            title="STM32F405",
            content="168MHz ARM Cortex-M4",
            doc_type=DocumentType.MCU
        )
        
        results = index.search("STM32F405", limit=10)
        assert len(results) == 1
        assert "STM32F405" in results[0]["title"]
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_knowledge_index.py::test_add_document -v`
Expected: FAIL

- [ ] **Step 3: 实现添加和搜索方法**

```python
# agent/memory/knowledge_index.py (追加)
import uuid
from whoosh.writing import AsyncWriter

class KnowledgeIndex:
    # ... 现有代码 ...
    
    def add_document(
        self,
        title: str,
        content: str,
        doc_type: DocumentType,
        tags: Optional[List[str]] = None,
        filepath: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None
    ) -> str:
        if doc_id is None:
            doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        
        writer = AsyncWriter(self.ix)
        writer.add_document(
            doc_id=doc_id,
            title=title,
            content=content,
            doc_type=doc_type.value,
            tags=",".join(tags or []),
            filepath=filepath or "",
            metadata=str(metadata or {})
        )
        writer.commit()
        
        return doc_id
    
    def search(
        self,
        query: str,
        limit: int = 10,
        doc_type: Optional[DocumentType] = None
    ) -> List[Dict[str, Any]]:
        with self.ix.searcher() as searcher:
            parser = MultifieldParser(["title", "content"], schema=self.ix.schema)
            q = parser.parse(query)
            
            results = searcher.search(q, limit=limit)
            
            docs = []
            for hit in results:
                doc = {
                    "doc_id": hit["doc_id"],
                    "title": hit["title"],
                    "content": hit["content"],
                    "doc_type": hit["doc_type"],
                    "score": hit.score,
                }
                
                if doc_type is None or doc["doc_type"] == doc_type.value:
                    docs.append(doc)
            
            return docs
    
    def get_document_count(self) -> int:
        with self.ix.searcher() as searcher:
            return searcher.doc_count_all()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_knowledge_index.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: 提交添加和搜索功能**

```bash
git add agent/memory/knowledge_index.py tests/test_knowledge_index.py
git commit -m "feat(memory): 实现文档添加和搜索

- add_document() 支持元数据和标签
- search() 基于 BM25F 算法
- 支持按文档类型过滤
- 添加单元测试"
```

---

## Task 3: 实现增量更新和删除

**Files:**
- Modify: `agent/memory/knowledge_index.py`
- Modify: `tests/test_knowledge_index.py`

- [ ] **Step 1: 编写更新和删除测试**

```python
# tests/test_knowledge_index.py (追加)
def test_update_document():
    with tempfile.TemporaryDirectory() as tmpdir:
        index = KnowledgeIndex(index_dir=tmpdir)
        
        doc_id = index.add_document(
            title="旧标题",
            content="旧内容",
            doc_type=DocumentType.GENERAL
        )
        
        index.update_document(
            doc_id=doc_id,
            title="新标题",
            content="新内容"
        )
        
        results = index.search("新标题")
        assert len(results) == 1
        assert results[0]["title"] == "新标题"

def test_delete_document():
    with tempfile.TemporaryDirectory() as tmpdir:
        index = KnowledgeIndex(index_dir=tmpdir)
        
        doc_id = index.add_document(
            title="测试文档",
            content="测试内容",
            doc_type=DocumentType.GENERAL
        )
        
        assert index.get_document_count() == 1
        
        index.delete_document(doc_id)
        
        assert index.get_document_count() == 0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_knowledge_index.py::test_update_document -v`
Expected: FAIL

- [ ] **Step 3: 实现更新和删除方法**

```python
# agent/memory/knowledge_index.py (追加)
class KnowledgeIndex:
    # ... 现有代码 ...
    
    def update_document(
        self,
        doc_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        doc_type: Optional[DocumentType] = None,
        tags: Optional[List[str]] = None,
        filepath: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        # 先获取现有文档
        with self.ix.searcher() as searcher:
            query = QueryParser("doc_id", self.ix.schema).parse(doc_id)
            results = list(searcher.search(query, limit=1))
            
            if not results:
                raise ValueError(f"文档不存在: {doc_id}")
            
            old_doc = results[0]
        
        # 删除旧文档
        self.delete_document(doc_id)
        
        # 添加新文档（保留未更新的字段）
        self.add_document(
            doc_id=doc_id,
            title=title or old_doc["title"],
            content=content or old_doc["content"],
            doc_type=doc_type or DocumentType(old_doc["doc_type"]),
            tags=tags or old_doc.get("tags", "").split(","),
            filepath=filepath or old_doc.get("filepath"),
            metadata=metadata
        )
    
    def delete_document(self, doc_id: str) -> None:
        writer = self.ix.writer()
        writer.delete_by_term("doc_id", doc_id)
        writer.commit()
    
    def rebuild_index(self, knowledge_dir: Path) -> int:
        # 清空现有索引
        writer = self.ix.writer()
        writer.commit(mergetype=index.CLEAR)
        
        # 重新扫描知识库目录
        count = 0
        for md_file in knowledge_dir.rglob("*.md"):
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 从文件路径推断文档类型
            doc_type = self._infer_doc_type(md_file)
            
            self.add_document(
                title=md_file.stem,
                content=content,
                doc_type=doc_type,
                filepath=str(md_file)
            )
            count += 1
        
        return count
    
    def _infer_doc_type(self, filepath: Path) -> DocumentType:
        parts = filepath.parts
        if "mcu" in parts or "芯片" in parts:
            return DocumentType.MCU
        if "protocol" in parts or "协议" in parts:
            return DocumentType.PROTOCOL
        if "sensor" in parts or "传感器" in parts:
            return DocumentType.SENSOR
        if "error" in parts or "错误码" in parts:
            return DocumentType.ERROR_CODE
        if "board" in parts or "板卡" in parts:
            return DocumentType.BOARD
        return DocumentType.GENERAL
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_knowledge_index.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: 提交增量更新功能**

```bash
git add agent/memory/knowledge_index.py tests/test_knowledge_index.py
git commit -m "feat(memory): 实现增量更新和索引重建

- update_document() 更新现有文档
- delete_document() 删除文档
- rebuild_index() 重建整个索引
- 自动推断文档类型
- 添加单元测试"
```

---

## Task 4: 实现 QualityScorer 核心结构

**Files:**
- Create: `agent/distill/quality_scorer.py`
- Create: `tests/test_quality_scorer.py`

- [ ] **Step 1: 编写质量评分测试**

```python
# tests/test_quality_scorer.py
from agent.distill.quality_scorer import QualityScorer, SkillProposal, QualityReport

def test_quality_scorer_completeness():
    scorer = QualityScorer()
    
    proposal = SkillProposal(
        name="test_skill",
        description="测试技能",
        steps=["步骤1", "步骤2"],
        examples=["示例1"],
        metadata={}
    )
    
    report = scorer.score(proposal)
    
    assert report.completeness_score > 0
    assert report.total_score > 0

def test_quality_scorer_filter_low_quality():
    scorer = QualityScorer(threshold=0.6)
    
    low_quality = SkillProposal(
        name="bad",
        description="差",
        steps=[],
        examples=[],
        metadata={}
    )
    
    report = scorer.score(low_quality)
    assert report.total_score < 0.6
    assert not scorer.should_accept(low_quality)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m pytest tests/test_quality_scorer.py::test_quality_scorer_completeness -v`
Expected: FAIL

- [ ] **Step 3: 实现 QualityScorer 基础结构**

```python
# agent/distill/quality_scorer.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class SkillProposal:
    name: str
    description: str
    steps: List[str]
    examples: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

@dataclass
class QualityReport:
    completeness_score: float
    reusability_score: float
    clarity_score: float
    total_score: float
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

class QualityScorer:
    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold
    
    def score(self, proposal: SkillProposal) -> QualityReport:
        completeness = self._score_completeness(proposal)
        reusability = self._score_reusability(proposal)
        clarity = self._score_clarity(proposal)
        
        total = (completeness + reusability + clarity) / 3.0
        
        issues = []
        suggestions = []
        
        if completeness < 0.5:
            issues.append("缺少必需字段")
            suggestions.append("补充描述、步骤或示例")
        
        if reusability < 0.5:
            issues.append("可复用性低")
            suggestions.append("参数化步骤，避免硬编码")
        
        if clarity < 0.5:
            issues.append("清晰度不足")
            suggestions.append("增加描述长度，细化步骤")
        
        return QualityReport(
            completeness_score=completeness,
            reusability_score=reusability,
            clarity_score=clarity,
            total_score=total,
            issues=issues,
            suggestions=suggestions
        )
    
    def should_accept(self, proposal: SkillProposal) -> bool:
        report = self.score(proposal)
        return report.total_score >= self.threshold
    
    def _score_completeness(self, proposal: SkillProposal) -> float:
        score = 0.0
        
        if proposal.name:
            score += 0.2
        if proposal.description and len(proposal.description) >= 10:
            score += 0.3
        if proposal.steps and len(proposal.steps) >= 2:
            score += 0.3
        if proposal.examples:
            score += 0.2
        
        return min(score, 1.0)
    
    def _score_reusability(self, proposal: SkillProposal) -> float:
        score = 0.5  # 基础分
        
        # 检查是否有参数化步骤
        param_count = sum(1 for step in proposal.steps if "{" in step and "}" in step)
        if param_count > 0:
            score += 0.3
        
        # 检查是否有硬编码路径
        hardcoded = sum(1 for step in proposal.steps if "/home/" in step or "C:\\" in step)
        if hardcoded > 0:
            score -= 0.2
        
        return max(0.0, min(score, 1.0))
    
    def _score_clarity(self, proposal: SkillProposal) -> float:
        score = 0.0
        
        # 描述长度
        if len(proposal.description) >= 50:
            score += 0.4
        elif len(proposal.description) >= 20:
            score += 0.2
        
        # 步骤数量
        if 3 <= len(proposal.steps) <= 10:
            score += 0.3
        elif len(proposal.steps) > 0:
            score += 0.1
        
        # 步骤平均长度
        if proposal.steps:
            avg_len = sum(len(s) for s in proposal.steps) / len(proposal.steps)
            if avg_len >= 20:
                score += 0.3
        
        return min(score, 1.0)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m pytest tests/test_quality_scorer.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 提交 QualityScorer**

```bash
git add agent/distill/quality_scorer.py tests/test_quality_scorer.py
git commit -m "feat(distill): 实现 QualityScorer 质量评分器

- 完整性评分（必需字段）
- 可复用性评分（参数化、硬编码检测）
- 清晰度评分（描述长度、步骤数量）
- 自动过滤低质量提案
- 添加单元测试"
```

---

## Task 5: 集成到 CLI 和 REPL

**Files:**
- Modify: `agent/memory/__init__.py`
- Modify: `agent/distill/__init__.py`
- Modify: `agent/cli.py`

- [ ] **Step 1: 更新模块导出**

```python
# agent/memory/__init__.py
from .knowledge_index import KnowledgeIndex, DocumentType

__all__ = ["KnowledgeIndex", "DocumentType"]
```

```python
# agent/distill/__init__.py
from .quality_scorer import QualityScorer, SkillProposal, QualityReport

__all__ = ["QualityScorer", "SkillProposal", "QualityReport"]
```

- [ ] **Step 2: 添加索引重建命令**

```python
# agent/cli.py (添加子命令)
@cli.command()
@click.option("--knowledge-dir", default="knowledge", help="知识库目录")
def rebuild_index(knowledge_dir: str):
    """重建知识库索引"""
    from agent.memory import KnowledgeIndex
    from pathlib import Path
    
    index_dir = Path.home() / ".sinan" / "knowledge_index"
    knowledge_path = Path(knowledge_dir)
    
    if not knowledge_path.exists():
        click.echo(f"错误：知识库目录不存在: {knowledge_path}")
        return
    
    click.echo("正在重建索引...")
    index = KnowledgeIndex(index_dir=index_dir)
    count = index.rebuild_index(knowledge_path)
    
    click.echo(f"✓ 索引重建完成，共索引 {count} 个文档")
```

- [ ] **Step 3: 在技能蒸馏中使用质量评分**

```python
# agent/distill/distiller.py (如果存在，修改；否则跳过此步骤)
from agent.distill import QualityScorer, SkillProposal

class SkillDistiller:
    def __init__(self):
        self.scorer = QualityScorer(threshold=0.6)
    
    def distill(self, conversation_history):
        # ... 现有蒸馏逻辑 ...
        
        proposal = SkillProposal(
            name=extracted_name,
            description=extracted_desc,
            steps=extracted_steps,
            examples=extracted_examples
        )
        
        # 质量评分
        report = self.scorer.score(proposal)
        
        if not self.scorer.should_accept(proposal):
            print(f"技能质量不足 ({report.total_score:.2f}), 已过滤")
            print(f"问题: {', '.join(report.issues)}")
            return None
        
        return proposal
```

- [ ] **Step 4: 手动测试索引重建**

Run: `python3 -m agent.cli rebuild-index --knowledge-dir knowledge`

验证：
1. 索引文件创建在 `~/.sinan/knowledge_index/`
2. 输出显示索引的文档数量
3. 可以搜索到文档

- [ ] **Step 5: 提交集成**

```bash
git add agent/memory/__init__.py agent/distill/__init__.py agent/cli.py
git commit -m "feat: 集成知识库索引和质量评分到 CLI

- 添加 rebuild-index 命令
- 技能蒸馏使用质量评分过滤
- 更新模块导出
- 手动测试通过"
```

---

## Task 6: 运行完整测试套件

**Files:**
- Test: 所有测试

- [ ] **Step 1: 安装 Whoosh 依赖**

Run: `pip install whoosh`

- [ ] **Step 2: 运行所有单元测试**

Run: `python3 -m pytest tests/ -v --cov=agent --cov-report=term-missing`

Expected: 所有测试通过，新增模块覆盖率 ≥ 70%

- [ ] **Step 3: 检查覆盖率**

查看覆盖率报告，确保：
- `agent/memory/knowledge_index.py` ≥ 75%
- `agent/distill/quality_scorer.py` ≥ 80%

- [ ] **Step 4: 性能测试**

```python
# tests/test_knowledge_index.py (追加)
import time

def test_search_performance():
    with tempfile.TemporaryDirectory() as tmpdir:
        index = KnowledgeIndex(index_dir=tmpdir)
        
        # 添加 100 个文档
        for i in range(100):
            index.add_document(
                title=f"文档 {i}",
                content=f"这是第 {i} 个测试文档，包含一些内容",
                doc_type=DocumentType.GENERAL
            )
        
        # 测试搜索速度
        start = time.time()
        results = index.search("测试文档", limit=10)
        elapsed = time.time() - start
        
        assert len(results) > 0
        assert elapsed < 0.1  # 搜索应在 100ms 内完成
```

- [ ] **Step 5: 提交测试完成**

```bash
git add tests/
git commit -m "test: Phase 2B 测试完成

- 所有单元测试通过
- 新增模块覆盖率 ≥ 70%
- 性能测试通过（搜索 < 100ms）"
```

---

## Phase 2B 完成检查清单

- [ ] KnowledgeIndex 完整实现（添加、搜索、更新、删除）
- [ ] Whoosh 全文索引（BM25F 算法）
- [ ] 索引重建命令（CLI）
- [ ] QualityScorer 完整实现（3 个维度评分）
- [ ] 技能蒸馏集成质量过滤
- [ ] 单元测试覆盖率 ≥ 70%
- [ ] 性能测试通过（搜索 < 100ms）
- [ ] 所有代码已提交到 git

---

## 执行建议

**预计时间**: 2-3 天

**执行顺序**:
1. Task 1-2: KnowledgeIndex 核心（1 天）
2. Task 3: 增量更新和重建（0.5 天）
3. Task 4: QualityScorer 实现（0.5 天）
4. Task 5: CLI 集成（0.5 天）
5. Task 6: 测试和验证（0.5 天）

**注意事项**:
- 需要安装 Whoosh: `pip install whoosh`
- 索引文件较大，注意 .gitignore
- 性能测试确保搜索速度提升 10 倍
- 质量评分阈值可调整（默认 0.6）
