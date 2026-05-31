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
            return searcher.doc_count_all()
