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

def test_search_performance():
    import time
    with tempfile.TemporaryDirectory() as tmpdir:
        index = KnowledgeIndex(index_dir=tmpdir)

        # 添加 100 个文档
        for i in range(100):
            index.add_document(
                title=f"Document {i}",
                content=f"This is test document number {i} with some content",
                doc_type=DocumentType.GENERAL
            )

        # 测试搜索速度
        start = time.time()
        results = index.search("document", limit=10)
        elapsed = time.time() - start

        assert len(results) > 0
        assert elapsed < 0.1  # 搜索应在 100ms 内完成
