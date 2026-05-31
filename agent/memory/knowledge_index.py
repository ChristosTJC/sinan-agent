# agent/memory/knowledge_index.py
from __future__ import annotations
from pathlib import Path
from enum import Enum
from typing import Optional, List, Dict, Any
import uuid

try:
    from whoosh import index
    from whoosh.fields import Schema, TEXT, ID, KEYWORD, STORED
    from whoosh.qparser import MultifieldParser, QueryParser
    from whoosh.analysis import StemmingAnalyzer
    from whoosh.writing import AsyncWriter
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
            # 使用 doc_count() 而不是 doc_count_all()，排除已删除的文档
            return searcher.doc_count()

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
            # 在 searcher 关闭前提取所有需要的字段
            old_title = old_doc["title"]
            old_content = old_doc["content"]
            old_doc_type = old_doc["doc_type"]
            old_tags = old_doc.get("tags", "")
            old_filepath = old_doc.get("filepath", "")

        # 删除旧文档
        self.delete_document(doc_id)

        # 添加新文档（保留未更新的字段）
        self.add_document(
            doc_id=doc_id,
            title=title or old_title,
            content=content or old_content,
            doc_type=doc_type or DocumentType(old_doc_type),
            tags=tags or (old_tags.split(",") if old_tags else []),
            filepath=filepath or old_filepath,
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
