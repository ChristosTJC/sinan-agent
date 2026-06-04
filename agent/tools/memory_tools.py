"""
司南记忆工具 —— 供 LLM 主动写入记忆的桥接模块。

提供三个工具:
- remember_fact: 写入 L1 核心记忆 (MEMORY.md / USER.md)
- add_knowledge: 写入 L3 用户知识库 (~/.sinan/knowledge/)
- recall:        搜索 L2 会话历史
"""

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# remember_fact
# ---------------------------------------------------------------------------


def _make_remember_fact_handler(memory_store, sinan_home: Path):
    """创建 remember_fact 处理器闭包。

    Args:
        memory_store: MemoryStore 实例。
        sinan_home:   ~/.sinan/ 路径，用于 flush_to_disk。
    """

    def handler(arguments: dict) -> dict:
        """将事实记录到核心记忆。

        Args:
            fact (str): 要记录的事实内容 [required]
            category (str): memory (默认) 或 user
        """
        if memory_store is None:
            return {"success": False, "error": "核心记忆未初始化"}

        fact = arguments.get("fact", "").strip()
        if not fact:
            return {"success": False, "error": "缺少参数: fact"}

        category = arguments.get("category", "memory")

        ok = memory_store.add_user_pref(fact) if category == "user" else memory_store.add_fact(fact)

        if ok:
            memory_store.flush_to_disk(sinan_home / "memories")
            logger.info("remember_fact: %s", fact[:80])
            return {"success": True, "message": f"已记录到 {category}: {fact[:100]}"}
        else:
            return {"success": False, "error": "添加失败（内容未通过安全扫描或已存在）"}

    return handler


# ---------------------------------------------------------------------------
# add_knowledge
# ---------------------------------------------------------------------------


def _make_add_knowledge_handler(knowledge_base):
    """创建 add_knowledge 处理器闭包。

    Args:
        knowledge_base: KnowledgeBase 实例（含 user_kb_dir）。
    """

    def handler(arguments: dict) -> dict:
        """将知识条目写入用户知识库。

        Args:
            title (str): 知识条目标题 [required]
            content (str): 知识内容 [required]
            category (str): 知识类别，默认 pitfalls
        """
        if knowledge_base is None:
            return {"success": False, "error": "知识库未初始化"}

        title = arguments.get("title", "").strip()
        content = arguments.get("content", "").strip()
        category = arguments.get("category", "pitfalls")

        if not title:
            return {"success": False, "error": "缺少参数: title"}
        if not content:
            return {"success": False, "error": "缺少参数: content"}

        try:
            file_path = knowledge_base.add_entry(category, title, content)
            logger.info("add_knowledge: %s/%s", category, title)
            return {
                "success": True,
                "message": f"已添加知识: {category}/{title}",
                "path": str(file_path),
            }
        except Exception as exc:
            return {"success": False, "error": f"写入知识失败: {exc}"}

    return handler


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


def _make_recall_handler(session_db):
    """创建 recall 处理器闭包。

    Args:
        session_db: SessionDB 实例。
    """

    def handler(arguments: dict) -> dict:
        """搜索历史会话记录。

        Args:
            query (str): 搜索关键词 [required]
            limit (int): 返回条数，默认 5
        """
        if session_db is None:
            return {"success": False, "error": "会话数据库未初始化"}

        query = arguments.get("query", "").strip()
        if not query:
            return {"success": False, "error": "缺少参数: query"}

        limit = int(arguments.get("limit", 5))

        try:
            results = session_db.session_search(query, limit=limit)
            if not results:
                return {"success": True, "message": "未找到匹配的历史会话", "results": []}

            formatted = []
            for r in results:
                formatted.append({
                    "session_id": r.get("session_id", "")[:12],
                    "role": r.get("role", ""),
                    "content": (r.get("content") or "")[:200],
                    "timestamp": r.get("timestamp", ""),
                })
            return {
                "success": True,
                "message": f"找到 {len(formatted)} 条相关记录",
                "results": formatted,
            }
        except Exception as exc:
            return {"success": False, "error": f"搜索失败: {exc}"}

    return handler


# ---------------------------------------------------------------------------
# 批量注册
# ---------------------------------------------------------------------------


def register_memory_tools(
    registry,
    memory_store,
    knowledge_base,
    session_db,
    sinan_home: Path,
) -> None:
    """将三个记忆工具注册到 ToolRegistry。

    Args:
        registry:       ToolRegistry 实例。
        memory_store:   MemoryStore 实例（可为 None）。
        knowledge_base: KnowledgeBase 实例（可为 None）。
        session_db:     SessionDB 实例（可为 None）。
        sinan_home:     ~/.sinan/ 路径。
    """
    # remember_fact
    registry.register(
        "remember_fact",
        _make_remember_fact_handler(memory_store, sinan_home),
        description="将重要事实、踩坑记录、硬件参数记录到核心记忆",
        parameters={
            "fact": {
                "type": "string",
                "description": "要记录的事实内容",
                "required": True,
            },
            "category": {
                "type": "string",
                "description": "memory (默认，项目记忆) 或 user (用户偏好)",
                "required": False,
            },
        },
    )

    # add_knowledge
    registry.register(
        "add_knowledge",
        _make_add_knowledge_handler(knowledge_base),
        description="将调试发现、板卡踩坑等知识存入用户知识库",
        parameters={
            "title": {
                "type": "string",
                "description": "知识条目标题",
                "required": True,
            },
            "content": {
                "type": "string",
                "description": "知识内容描述",
                "required": True,
            },
            "category": {
                "type": "string",
                "description": "知识类别 (pitfalls/tips/findings 等，默认 pitfalls)",
                "required": False,
            },
        },
    )

    # recall
    registry.register(
        "recall",
        _make_recall_handler(session_db),
        description="搜索历史会话记录，回忆之前的调试过程",
        parameters={
            "query": {
                "type": "string",
                "description": "搜索关键词",
                "required": True,
            },
            "limit": {
                "type": "integer",
                "description": "返回条数 (默认 5)",
                "required": False,
            },
        },
    )

    logger.info("记忆工具已注册: remember_fact, add_knowledge, recall")
