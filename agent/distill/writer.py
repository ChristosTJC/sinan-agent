# agent/distill/writer.py — 技能写入器：将蒸馏提案持久化为 SKILL.md 文件
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SkillWriter:
    """技能写入器 —— 将技能提案写入用户技能目录。

    每个技能是一个子目录，内含 ``SKILL.md`` 文件（YAML frontmatter + Markdown 正文）。
    支持新增和章节追加，对策展技能可生成用户覆盖副本。

    Attributes:
        user_skills_dir: 用户技能目录（写入目标）。
    """

    def __init__(self, user_skills_dir: Path) -> None:
        self.user_skills_dir = Path(user_skills_dir)
        self.user_skills_dir.mkdir(parents=True, exist_ok=True)

    # ── 名字校验 ───────────────────────────────────────────────

    @staticmethod
    def _is_valid_name(name: str) -> bool:
        """检查技能名是否合法 —— 拒绝路径穿越、空名、绝对路径。"""
        if not name:
            return False
        if ".." in name:
            return False
        if name.startswith("/") or "/" in name:
            return False
        # 禁止非小写连字符格式
        return all(ch.islower() or ch.isdigit() or ch == "-" for ch in name)

    # ── 写技能 ─────────────────────────────────────────────────

    def write_skill(
        self, name: str, description: str, content: str
    ) -> Optional[Path]:
        """创建新技能文件。

        Args:
            name: 技能名（小写连字符）。
            description: 简短描述（写入 YAML frontmatter）。
            content: Markdown 正文。

        Returns:
            创建的 ``SKILL.md`` 路径；名称不合法或已存在返回 None。
        """
        if not self._is_valid_name(name):
            logger.warning("技能名校验失败: %s", name)
            return None

        skill_dir = self.user_skills_dir / name
        if skill_dir.exists():
            logger.info("技能已存在，跳过: %s", name)
            return None

        skill_dir.mkdir(parents=True)
        md_path = skill_dir / "SKILL.md"
        frontmatter = (
            f"---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"source: distilled\n"
            f"---\n\n"
        )
        md_path.write_text(frontmatter + content, encoding="utf-8")
        logger.info("技能写入成功: %s", md_path)
        return md_path

    # ── 更新技能 ───────────────────────────────────────────────

    def update_skill(
        self,
        name: str,
        section_title: str,
        section_content: str,
        project_skills_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """向已有技能追加/创建章节。

        若技能仅在策展目录中存在（不在用户目录），则先复制到用户目录再操作。
        若技能不存在，返回 None。

        Args:
            name: 技能名。
            section_title: 章节标题（不含 ``##`` 前缀，如 ``"注意事项"``）。
            section_content: 追加的章节正文。
            project_skills_dir: 策展/项目技能目录（只读源）。

        Returns:
            修改后的 ``SKILL.md`` 路径；未找到返回 None。
        """
        skill_dir = self.user_skills_dir / name
        src_path: Optional[Path] = None

        if skill_dir.exists():
            src_path = skill_dir / "SKILL.md"
        elif project_skills_dir is not None:
            curated_dir = Path(project_skills_dir) / name
            if curated_dir.is_dir():
                # 策展技能 → 复制到用户目录
                import shutil

                skill_dir.mkdir(parents=True)
                shutil.copy2(curated_dir / "SKILL.md", skill_dir / "SKILL.md")
                for item in curated_dir.iterdir():
                    if item.name != "SKILL.md":
                        dst = skill_dir / item.name
                        if not dst.exists():
                            if item.is_dir():
                                shutil.copytree(item, dst)
                            else:
                                shutil.copy2(item, dst)
                src_path = skill_dir / "SKILL.md"

        if src_path is None or not src_path.exists():
            logger.warning("更新目标不存在: %s", name)
            return None

        current = src_path.read_text(encoding="utf-8")
        heading = f"## {section_title}"

        # 章节已存在 → 在段落末尾追加
        if heading in current:
            # 找到该标题之后、下一个 ## 之前的结束位置
            pos = current.index(heading)
            # 找下一个 ## 标题或文件尾
            rest = current[pos + len(heading) :]
            next_heading = rest.find("\n## ")
            insert_pos = pos + len(heading) + next_heading if next_heading != -1 else len(current)
            new_content = (
                current[:insert_pos].rstrip()
                + "\n"
                + section_content
                + "\n"
                + current[insert_pos:].lstrip()
            )
        else:
            # 新章节 → 追加到文件末尾
            new_content = current.rstrip() + f"\n\n{heading}\n{section_content}\n"

        src_path.write_text(new_content, encoding="utf-8")
        logger.info("技能章节更新: %s → %s", name, section_title)
        return src_path
