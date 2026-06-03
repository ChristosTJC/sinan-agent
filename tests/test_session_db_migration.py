"""Regression tests for migrating older SessionDB SQLite schemas."""

from __future__ import annotations

import sqlite3

from agent.memory.session_db import SessionDB


def test_session_db_migrates_legacy_integer_message_id_schema(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    db_path = sessions_dir / "state.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            model TEXT,
            token_count INTEGER DEFAULT 0,
            summary TEXT
        );

        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_name TEXT,
            tool_result TEXT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE VIRTUAL TABLE messages_fts USING fts5(content, tool_name, tool_result);
    """)
    conn.execute(
        "INSERT INTO sessions (id, project, model) VALUES (?, ?, ?)",
        ("legacy-session", "legacy", "old-model"),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        ("legacy-session", "user", "old hello"),
    )
    conn.commit()
    conn.close()

    db = SessionDB(sessions_dir)
    try:
        new_session = db.create_session(project="new", model="new-model")
        msg_id = db.add_message(new_session, "user", "你好")
        schema = db._conn.execute("PRAGMA table_info(messages)").fetchall()
        fts_schema = db._conn.execute("PRAGMA table_info(messages_fts)").fetchall()
        current = db.get_session(new_session)
        legacy = db.get_session("legacy-session")
    finally:
        db.close()

    assert isinstance(msg_id, str)
    assert {row[1]: row[2].upper() for row in schema}["id"] == "TEXT"
    assert [row[1] for row in fts_schema] == ["session_id", "content"]
    assert current["messages"][0]["content"] == "你好"
    assert legacy["messages"][0]["content"] == "old hello"
