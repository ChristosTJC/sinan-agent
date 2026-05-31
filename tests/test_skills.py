"""
skills.py 单元测试。

覆盖:
- _split_frontmatter: frontmatter 拆分 (使用 yaml.safe_load)
- SkillLoader: 技能加载、查询、系统提示构建
"""

import tempfile
from pathlib import Path

import pytest

from agent.skills import SkillLoader, _split_frontmatter


# ---------------------------------------------------------------------------
# _split_frontmatter
# ---------------------------------------------------------------------------


class TestSplitFrontmatter:
    def test_valid_frontmatter(self):
        text = "---\nname: test\ndescription: hello\n---\n\nBody text"
        fm, body = _split_frontmatter(text)
        assert fm["name"] == "test"
        assert fm["description"] == "hello"
        assert "Body text" in body

    def test_no_frontmatter(self):
        text = "Just plain markdown"
        fm, body = _split_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_unclosed_frontmatter(self):
        text = "---\nname: test\n"
        fm, body = _split_frontmatter(text)
        assert fm == {}

    def test_empty_frontmatter(self):
        text = "---\n---\nBody"
        fm, body = _split_frontmatter(text)
        assert fm == {}
        assert "Body" in body


# ---------------------------------------------------------------------------
# SkillLoader
# ---------------------------------------------------------------------------


class TestSkillLoader:
    @pytest.fixture
    def skills_dir(self, tmp_path):
        """创建临时技能目录。"""
        for name, desc in [("alpha", "Alpha skill"), ("beta", "Beta skill")]:
            skill_dir = tmp_path / name
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {desc}\nmetadata:\n  type: skill\n---\n\n"
                f"## 触发条件\n\nTrigger for {name}\n\n## 核心能力\n\nContent for {name}\n",
                encoding="utf-8",
            )
        return tmp_path

    def test_load_all(self, skills_dir):
        loader = SkillLoader(skills_dir)
        skills = loader.load_all()
        assert len(skills) == 2

    def test_list_names(self, skills_dir):
        loader = SkillLoader(skills_dir)
        loader.load_all()
        names = loader.list_names()
        assert names == ["alpha", "beta"]

    def test_get_by_name(self, skills_dir):
        loader = SkillLoader(skills_dir)
        loader.load_all()
        skill = loader.get("alpha")
        assert skill is not None
        assert skill.name == "alpha"
        assert skill.description == "Alpha skill"

    def test_get_nonexistent(self, skills_dir):
        loader = SkillLoader(skills_dir)
        loader.load_all()
        assert loader.get("nonexistent") is None

    def test_trigger_section(self, skills_dir):
        loader = SkillLoader(skills_dir)
        loader.load_all()
        skill = loader.get("alpha")
        assert "Trigger for alpha" in skill.trigger_section

    def test_build_system_prompt(self, skills_dir):
        loader = SkillLoader(skills_dir)
        loader.load_all()
        prompt = loader.build_system_prompt_section()
        assert "Alpha skill" in prompt
        assert "Beta skill" in prompt
        assert "## 可用技能" in prompt

    def test_build_tools_schemas(self, skills_dir):
        loader = SkillLoader(skills_dir)
        loader.load_all()
        schemas = loader.build_tools_schemas()
        assert len(schemas) == 2
        assert schemas[0]["type"] == "function"
        assert "skill_alpha" in schemas[0]["function"]["name"]

    def test_missing_dir(self, tmp_path):
        loader = SkillLoader(tmp_path / "nonexistent")
        skills = loader.load_all()
        assert skills == []

    def test_reload(self, skills_dir):
        loader = SkillLoader(skills_dir)
        loader.load_all()
        skills = loader.load_all(reload=True)
        assert len(skills) == 2
