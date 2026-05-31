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
