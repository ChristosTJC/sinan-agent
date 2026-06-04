from __future__ import annotations

from types import SimpleNamespace

from agent.core.context import RetrievalContextProvider, TurnConsolidator


class FakeKB:
    def build_context(self, query, max_chars=2000):
        return f"[KB] {query[:10]}"


class FakeMemory:
    def build_context(self):
        return "[L1] 项目记忆"


class FakeSessionDB:
    def __init__(self):
        self.messages = []

    def add_message(self, session_id, role, content=""):
        self.messages.append((session_id, role, content))


def test_provider_combines_sources():
    p = RetrievalContextProvider(knowledge_base=FakeKB(), memory_store=FakeMemory())
    ctx = p.provide("帮我看蓝牙连接超时")
    assert "[KB]" in ctx
    assert "[L1]" in ctx


def test_provider_empty_returns_blank():
    p = RetrievalContextProvider()
    assert p.provide("anything") == ""


def test_consolidator_persists_messages():
    db = FakeSessionDB()
    c = TurnConsolidator(session_db=db, session_id="s1")
    result = SimpleNamespace(final_text="完成", success=True)
    assert c.consolidate("编译固件", result) is True
    roles = [m[1] for m in db.messages]
    assert "user" in roles and "assistant" in roles
