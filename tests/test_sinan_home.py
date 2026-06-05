"""SINAN_HOME 单一真相源测试。"""

from pathlib import Path


class TestGetSinanHome:
    def test_reads_env_each_call(self, monkeypatch, tmp_path):
        from agent.config import get_sinan_home

        monkeypatch.setenv("SINAN_HOME", str(tmp_path / "a"))
        assert get_sinan_home() == tmp_path / "a"
        # 同一进程内改 env，再次调用应返回新值（非 import 时缓存）
        monkeypatch.setenv("SINAN_HOME", str(tmp_path / "b"))
        assert get_sinan_home() == tmp_path / "b"

    def test_default_when_env_absent(self, monkeypatch):
        from agent.config import get_sinan_home

        monkeypatch.delenv("SINAN_HOME", raising=False)
        assert get_sinan_home() == Path.home() / ".sinan"


class TestSinanHomeWiring:
    """monkeypatch SINAN_HOME 后，各模块默认路径应落到该目录。"""

    def test_skill_loader_user_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SINAN_HOME", str(tmp_path))
        from agent.skills import SkillLoader
        assert SkillLoader().user_skills_dir == tmp_path / "skills"

    def test_knowledge_index_under_sinan_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SINAN_HOME", str(tmp_path))
        from agent.memory.knowledge_base import KnowledgeBase
        kb_dir = Path(__file__).resolve().parent.parent / "knowledge"
        KnowledgeBase(kb_dir=kb_dir)
        # __init__ 会 mkdir index_root；断言索引目录落到 SINAN_HOME
        assert (tmp_path / "knowledge_index").is_dir()

    def test_orchestrator_memories_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SINAN_HOME", str(tmp_path))
        from agent.orchestrator import AgentOrchestrator

        # __init__ 会调用 session_db.create_session/detect_project，
        # 不能传 None，用最小 stub 占位（真实签名要求）。
        class _SessionDBStub:
            def detect_project(self):
                return "test"

            def create_session(self, project):
                return "sid"

        orch = AgentOrchestrator(registry=None, memory_store=None,
                                 session_db=_SessionDBStub(), knowledge_base=None)
        assert orch._memories_dir == tmp_path / "memories"

    def test_set_memory_context_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SINAN_HOME", str(tmp_path))
        seen = {}
        import agent.tools as tools_mod

        def fake_register(reg, ms, kb, sdb, sinan_home):
            seen["sinan_home"] = sinan_home
        monkeypatch.setattr("agent.tools.memory_tools.register_memory_tools", fake_register)
        reg = tools_mod.get_registry()
        reg._memory_tools_registered = False
        reg.set_memory_context(memory_store=object(), knowledge_base=object(),
                               session_db=object(), sinan_home=None)
        assert seen["sinan_home"] == tmp_path

    def test_audit_logger_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SINAN_HOME", str(tmp_path))
        from agent.tools import AuditLogger
        assert AuditLogger()._log_dir == tmp_path / "audit"
