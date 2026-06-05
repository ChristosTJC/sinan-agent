"""
司南技能加载器。

从 skills/ 目录扫描 SKILL.md 文件，解析 YAML frontmatter，
提供结构化的技能对象供 Agent 系统提示注入使用。

技能目录结构::

    skills/
    ├── board-manager/
    │   └── SKILL.md          # frontmatter + Markdown 正文
    ├── device-connect/
    │   └── SKILL.md
    └── ...

frontmatter 格式::

    ---
    name: board-manager
    description: 板卡管理器
    metadata:
      type: skill
    ---
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from agent.config import get_sinan_home

logger = logging.getLogger(__name__)

# 技能目录默认位置 (项目根目录/skills)
_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass
class Skill:
    """解析后的技能对象。

    Attributes:
        name: 技能标识名 (如 "board-manager")。
        description: 一句话描述。
        directory: 技能所在目录名。
        content: SKILL.md 完整 Markdown 正文 (不含 frontmatter)。
        metadata: frontmatter 中的 metadata 字典。
        raw_frontmatter: 原始 frontmatter 字典。
    """

    name: str
    description: str
    directory: str
    content: str = ""
    metadata: dict = field(default_factory=dict)
    raw_frontmatter: dict = field(default_factory=dict)

    @property
    def trigger_section(self) -> str:
        """提取 '## 触发条件' 段内容 (用于相关性匹配)。"""
        m = re.search(
            r"##\s*触发条件\s*\n(.*?)(?=\n##\s|\Z)",
            self.content,
            re.DOTALL,
        )
        return m.group(1).strip() if m else ""

    def summary(self, max_content: int = 200) -> str:
        """返回技能摘要 (描述 + 内容前 N 字)。"""
        if len(self.content) <= max_content:
            return self.content
        return self.content[:max_content] + "..."


class SkillLoader:
    """技能加载器 —— 扫描、解析、管理技能。

    支持双目录：策展技能（项目 skills/，只读） + 用户技能（~/.sinan/skills/，可写）。
    同名技能用户目录优先，允许覆盖策展而不修改原文件。

    Args:
        skills_dir: 项目策展技能目录。默认为项目根目录下的 ``skills/``。
        user_skills_dir: 用户自蒸馏技能目录。默认为 ``~/.sinan/skills/``。
    """

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        user_skills_dir: Optional[Path] = None,
    ) -> None:
        self._skills_dir = skills_dir or _DEFAULT_SKILLS_DIR
        self._user_skills_dir = user_skills_dir or (get_sinan_home() / "skills")
        self._skills: dict[str, Skill] = {}
        self._loaded = False

    @property
    def skills_dir(self) -> Path:
        return self._skills_dir

    @property
    def user_skills_dir(self) -> Path:
        return self._user_skills_dir

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def load_all(self, *, reload: bool = False) -> list[Skill]:
        """扫描并加载所有技能（策展 + 用户）。

        Args:
            reload: 强制重新加载 (忽略缓存)。

        Returns:
            所有已加载的 Skill 列表。
        """
        if self._loaded and not reload:
            return list(self._skills.values())

        self._skills.clear()

        # 先加载项目技能（策展，只读）
        self._scan_dir(self._skills_dir, source="curated")

        # 再加载用户技能（可写，同名覆盖策展）
        self._scan_dir(self._user_skills_dir, source="user")

        self._loaded = True
        logger.info("技能加载完成, 共 %d 个 (策展 + 用户)", len(self._skills))
        return list(self._skills.values())

    def _scan_dir(self, dir_path: Path, source: str) -> None:
        """扫描目录下所有子目录中的 SKILL.md 并加载为技能。

        Args:
            dir_path: 技能根目录
            source: 来源标记 ("curated" | "user")。同名时用户来源覆盖策展。
        """
        if not dir_path.exists():
            return

        for skill_dir in sorted(dir_path.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            skill = self._parse_skill_file(skill_md, skill_dir.name)
            if skill:
                # 同名时用户来源覆盖策展来源
                if skill.name in self._skills and source == "curated":
                    continue
                self._skills[skill.name] = skill
                logger.debug("已加载技能: %s (来源: %s)", skill.name, source)

    def get(self, name: str) -> Optional[Skill]:
        """按名称获取技能。"""
        if not self._loaded:
            self.load_all()
        return self._skills.get(name)

    def list_names(self) -> list[str]:
        """返回所有已加载技能名称。"""
        if not self._loaded:
            self.load_all()
        return sorted(self._skills.keys())

    # ------------------------------------------------------------------
    # 系统提示注入
    # ------------------------------------------------------------------

    def build_system_prompt_section(
        self,
        *,
        include_content: bool = False,
        max_content: int = 500,
    ) -> str:
        """构建技能摘要段, 用于注入 Agent 系统提示。

        Args:
            include_content: 是否包含技能正文摘要。
            max_content: 每个技能正文截取长度。

        Returns:
            Markdown 格式的技能列表文本。
        """
        if not self._loaded:
            self.load_all()

        if not self._skills:
            return ""

        lines = ["## 可用技能 (Skills)", ""]
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            lines.append(f"- **{skill.name}**: {skill.description}")
            if include_content and skill.content:
                lines.append(f"  {skill.summary(max_content)}")
        lines.append("")
        return "\n".join(lines)

    def build_tools_schemas(self) -> list[dict]:
        """将技能转换为 LLM function-calling 风格的 tool schema。

        每个技能映射为一个虚拟工具, LLM 可通过 function call 激活技能,
        从而将技能详细内容注入对话上下文。

        Returns:
            OpenAI 格式的 tool schema 列表。
        """
        if not self._loaded:
            self.load_all()

        schemas = []
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            schemas.append({
                "type": "function",
                "function": {
                    "name": f"skill_{skill.name.replace('-', '_')}",
                    "description": skill.description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["activate", "describe"],
                                "description": "activate=激活技能获取完整指引, describe=仅获取摘要",
                            },
                        },
                        "required": ["action"],
                    },
                },
            })
        return schemas

    # ------------------------------------------------------------------
    # 内部解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_skill_file(skill_md: Path, directory: str) -> Optional[Skill]:
        """解析单个 SKILL.md 文件。

        Args:
            skill_md: SKILL.md 文件路径。
            directory: 所在目录名。

        Returns:
            解析后的 Skill 对象, 解析失败返回 None。
        """
        try:
            text = skill_md.read_text(encoding="utf-8")
        except IOError as exc:
            logger.warning("无法读取技能文件 %s: %s", skill_md, exc)
            return None

        frontmatter, content = _split_frontmatter(text)

        name = frontmatter.get("name", directory)
        description = frontmatter.get("description", "")
        metadata = frontmatter.get("metadata", {})

        return Skill(
            name=name,
            description=description,
            directory=directory,
            content=content.strip(),
            metadata=metadata if isinstance(metadata, dict) else {},
            raw_frontmatter=frontmatter,
        )


# ---------------------------------------------------------------------------
# Frontmatter 解析 (纯标准库, 不依赖 yaml 库)
# ---------------------------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """拆分 YAML frontmatter 和正文。

    Args:
        text: SKILL.md 全文。

    Returns:
        (frontmatter_dict, body_text) 元组。
        解析失败时 frontmatter 为空字典。
    """
    if not text.startswith("---"):
        return {}, text

    # 找到第二个 ---
    end = text.find("---", 3)
    if end == -1:
        return {}, text

    fm_text = text[3:end].strip()
    body = text[end + 3:]

    # 使用 pyyaml 解析 frontmatter
    try:
        frontmatter = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        frontmatter = {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, body


# ---------------------------------------------------------------------------
# 模块级便捷 API
# ---------------------------------------------------------------------------


_loader: Optional[SkillLoader] = None


def get_skill_loader(skills_dir: Optional[Path] = None) -> SkillLoader:
    """获取全局 SkillLoader 单例。"""
    global _loader
    if _loader is None:
        _loader = SkillLoader(skills_dir)
        _loader.load_all()
    return _loader


def list_skills() -> list[Skill]:
    """快捷函数: 返回所有已加载技能。"""
    return get_skill_loader().load_all()


__all__ = [
    "Skill",
    "SkillLoader",
    "get_skill_loader",
    "list_skills",
]
