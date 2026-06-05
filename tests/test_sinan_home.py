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
