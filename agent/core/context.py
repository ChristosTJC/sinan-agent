"""检索上下文注入 + turn 沉淀。只复用底层记忆/知识依赖，不碰 orchestrator。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.session import TurnResult

logger = logging.getLogger(__name__)


class RetrievalContextProvider:
    """检索 L3 知识库 + L1 记忆，格式化为单段 Markdown 注入文本。"""

    def __init__(
        self,
        knowledge_base=None,
        memory_store=None,
        session_db=None,
        max_chars: int = 2000,
    ) -> None:
        self._kb = knowledge_base
        self._memory = memory_store
        self._session_db = session_db
        self._max_chars = max_chars

    def provide(self, user_input: str) -> str:
        parts: list[str] = []
        if self._memory is not None:
            try:
                mem = self._memory.build_context()
                if mem and mem.strip():
                    parts.append(mem.strip())
            except Exception as exc:  # noqa: BLE001
                logger.warning("L1 记忆检索失败: %s", exc)
        if self._kb is not None:
            try:
                kb = self._kb.build_context(query=user_input, max_chars=self._max_chars)
                if kb and kb.strip():
                    parts.append(f"# 相关知识库\n\n{kb.strip()}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("L3 知识检索失败: %s", exc)
        return "\n\n".join(parts)


class TurnConsolidator:
    """turn 结束后写 L2 会话消息（+ 可选 L1 记忆）。输入是 TurnResult，非 phases dict。"""

    def __init__(
        self,
        memory_store=None,
        session_db=None,
        session_id: Optional[str] = None,
        memories_dir: Optional[Path] = None,
    ) -> None:
        self._memory = memory_store
        self._session_db = session_db
        self._session_id = session_id
        self._memories_dir = Path(memories_dir) if memories_dir else None

    def consolidate(self, user_input: str, result: "TurnResult") -> bool:
        wrote = False
        if self._session_db is not None and self._session_id:
            try:
                self._session_db.add_message(self._session_id, "user", content=user_input)
                self._session_db.add_message(
                    self._session_id, "assistant", content=result.final_text
                )
                wrote = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("L2 会话沉淀失败: %s", exc)
        return wrote
