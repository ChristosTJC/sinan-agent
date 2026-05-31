# -*- coding: utf-8 -*-
"""L2 会话数据库模块 — 基于 SQLite + FTS5 的跨会话全文检索。

提供 SessionDB 类，管理会话 (sessions) 和消息 (messages) 的持久化存储，
支持按项目筛选、全文搜索历史消息、以及自动维护 FTS5 索引。

使用方式::

    db = SessionDB(Path("~/.sinan/sessions").expanduser())
    sid = db.create_session(project="myproject", model="gpt-4")
    db.add_message(sid, "user", "你好")
    results = db.session_search("你好", limit=5)
    db.close()
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class SessionDB:
    """L2 会话数据库 — SQLite + FTS5 实现。

    用途：
      - 持久化所有会话与消息
      - 跨会话全文搜索历史对话
      - 为 recall 工具提供检索后端

    数据文件：
      sessions 目录下的 state.db（SQLite3，WAL 模式）。
    """

    def __init__(self, sessions_dir: Path) -> None:
        """初始化会话数据库。

        自动创建目录和数据库文件，首次使用时建表。

        Args:
            sessions_dir: 会话数据目录路径（如 ~/.sinan/sessions）。
                          目录不存在时自动创建。
        """
        sessions_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = sessions_dir / "state.db"
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """创建数据库表结构（幂等操作）。

        创建三张表：
          - sessions:    会话元数据（id、项目、模型、时间戳、状态）
          - messages:    消息记录（角色、正文、工具调用、元数据）
          - messages_fts: FTS5 全文索引（外部内容表，指向 messages）

        同时创建 INSERT / UPDATE / DELETE 触发器以保持 FTS 索引同步。
        """
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                project TEXT,
                model TEXT,
                created_at TEXT,
                updated_at TEXT,
                message_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT REFERENCES sessions(id),
                role TEXT,
                content TEXT,
                tool_calls TEXT,
                tool_results TEXT,
                created_at TEXT,
                metadata TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                session_id, content,
                content=messages, content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, session_id, content)
                VALUES (new.rowid, new.session_id, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, session_id, content)
                VALUES ('delete', old.rowid, old.session_id, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, session_id, content)
                VALUES ('delete', old.rowid, old.session_id, old.content);
                INSERT INTO messages_fts(rowid, session_id, content)
                VALUES (new.rowid, new.session_id, new.content);
            END;
        """)

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    def detect_project(self) -> str:
        """探测当前项目名称。

        探测策略（按优先级）：
          1. 读取当前目录下 AGENTS.md 第一行，若为 Markdown 标题则提取标题文本。
          2. 使用当前工作目录的目录名（basename）。
          3. 以上均失败时返回 ``"unknown"``。

        Returns:
            项目名称字符串。
        """
        cwd = Path.cwd()
        agents_md = cwd / "AGENTS.md"
        if agents_md.is_file():
            try:
                first_line = agents_md.read_text(encoding="utf-8").split("\n")[0].strip()
                if first_line.startswith("# "):
                    return first_line[2:].strip()
            except (OSError, UnicodeDecodeError):
                pass

        try:
            return cwd.name or "unknown"
        except Exception:
            return "unknown"

    def create_session(
        self,
        project: str = "unknown",
        model: str = "unknown",
    ) -> str:
        """创建新会话并返回会话 ID。

        Args:
            project: 项目名称（默认 ``"unknown"``）。
            model:   使用的 LLM 模型标识。

        Returns:
            新会话的 UUID（32 位 hex）字符串。
        """
        session_id = uuid.uuid4().hex
        now = _utcnow_iso()
        self._conn.execute(
            "INSERT INTO sessions (id, project, model, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, project, model, now, now),
        )
        self._conn.commit()
        return session_id

    def get_session(self, session_id: str) -> dict:
        """获取指定会话的完整信息（含所有消息）。

        Args:
            session_id: 会话 UUID。

        Returns:
            包含会话元数据与 messages 列表的字典。

        Raises:
            KeyError: 会话不存在。
        """
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"会话不存在: {session_id}")

        session = dict(row)
        msg_rows = self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        session["messages"] = [dict(m) for m in msg_rows]
        return session

    def get_current_session(self, session_id: Optional[str] = None) -> dict:
        """获取当前会话。

        若传入 session_id 则返回该会话；否则返回最近更新的活跃会话。

        Args:
            session_id: 可选，指定会话 UUID。

        Returns:
            包含会话元数据与 messages 列表的字典。

        Raises:
            KeyError: 指定会话不存在，或无活跃会话。
        """
        if session_id is not None:
            return self.get_session(session_id)

        row = self._conn.execute(
            "SELECT * FROM sessions WHERE status = 'active' "
            "ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise KeyError("无活跃会话")
        return self.get_session(row["id"])

    def list_sessions(
        self,
        limit: int = 20,
        project: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """列出最近的会话。

        Args:
            limit:   返回条数上限。
            project: 可选，按项目名称筛选。
            status:  可选，按状态筛选（如 ``'active'``、``'completed'``）。

        Returns:
            会话字典列表，按 updated_at 降序排列。
        """
        conditions = []
        params: list[Any] = []

        if project is not None:
            conditions.append("project = ?")
            params.append(project)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = (
            "SELECT * FROM sessions"
            + where
            + " ORDER BY updated_at DESC LIMIT ?"
        )
        params.append(limit)

        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 消息管理
    # ------------------------------------------------------------------

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[list] = None,
        tool_results: Optional[list] = None,
    ) -> str:
        """向会话追加一条消息。

        同时更新会话的 message_count（自增）与 updated_at（刷新为当前时间）。

        Args:
            session_id:   目标会话 UUID。
            role:         消息角色（``"user"`` / ``"assistant"`` / ``"system"`` / ``"tool"``）。
            content:      消息正文。
            tool_calls:   可选，LLM 发起的工具调用列表（序列化为 JSON）。
            tool_results: 可选，工具调用返回结果列表（序列化为 JSON）。

        Returns:
            新消息的 UUID（32 位 hex）字符串。
        """
        msg_id = uuid.uuid4().hex
        now = _utcnow_iso()
        tool_calls_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None
        tool_results_json = (
            json.dumps(tool_results, ensure_ascii=False) if tool_results else None
        )

        self._conn.execute(
            "INSERT INTO messages (id, session_id, role, content, "
            "tool_calls, tool_results, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (msg_id, session_id, role, content,
             tool_calls_json, tool_results_json, now),
        )
        self._conn.execute(
            "UPDATE sessions SET message_count = message_count + 1, "
            "updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        self._conn.commit()
        return msg_id

    # ------------------------------------------------------------------
    # 全文搜索
    # ------------------------------------------------------------------

    def _execute_fts_search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """执行 FTS5 全文搜索（底层实现，直接传入 FTS5 查询串）。

        Args:
            query: FTS5 查询字符串（已转义）。
            limit: 结果数量上限。

        Returns:
            匹配的消息字典列表，含 id、session_id、role、snippet、content、
            created_at 字段。
        """
        rows = self._conn.execute(
            "SELECT m.id, m.session_id, m.role, "
            "snippet(messages_fts, 1, '<mark>', '</mark>', '...', 40) AS snippet, "
            "m.content, m.created_at "
            "FROM messages_fts f "
            "JOIN messages m ON f.rowid = m.rowid "
            "WHERE messages_fts MATCH ? "
            "ORDER BY rank "
            "LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def session_search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """全文搜索历史消息（主要接口，供 recall 工具使用）。

        将用户输入转换为 FTS5 前缀查询，支持 CJK 等无空格语言。
        返回带高亮 snippet 的结果。

        Args:
            query: 搜索关键词（内部转为 FTS5 前缀查询）。
            limit: 结果数量上限（默认 10）。

        Returns:
            匹配的消息列表，每条含以下字段：
              - session_id: 所属会话 UUID
              - role:       消息角色
              - content:    消息全文
              - snippet:    FTS5 高亮摘要（匹配词用 ``<mark>`` 包裹）
              - timestamp:  消息创建时间（ISO 格式）
              - id:         消息 UUID
        """
        query = query.strip()
        if not query:
            return []

        words = query.split()
        fts_query = " AND ".join(f'"{w}"*' if " " not in w else f'"{w}"' for w in words)
        results = self._execute_fts_search(fts_query, limit=limit)
        for r in results:
            r["timestamp"] = r.pop("created_at", "")
        return results

    def query_sessions(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """全文搜索历史消息（别名接口）。

        Args:
            query: 搜索关键词。
            limit: 结果数量上限。

        Returns:
            匹配的消息列表。
        """
        return self.session_search(query, limit=limit)

    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """全文搜索历史消息（query_sessions 的便捷别名）。

        Args:
            query: 搜索关键词。
            limit: 结果数量上限。

        Returns:
            匹配的消息列表。
        """
        return self.session_search(query, limit=limit)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def close(self) -> None:
        """关闭数据库连接，释放 WAL 锁与文件描述符。

        关闭后不可再调用其他方法。重复调用安全（无操作）。
        """
        try:
            self._conn.close()
        except sqlite3.ProgrammingError:
            pass


def _utcnow_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串（含时区）。"""
    return datetime.now(timezone.utc).isoformat()
