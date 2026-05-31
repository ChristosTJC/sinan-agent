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
