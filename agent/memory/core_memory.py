"""
司南 L1 核心记忆模块。

基于 Markdown 文件的键值持久化存储，管理：
- MEMORY.md: 项目记忆（事实、经验、踩坑记录）
- USER.md:   用户偏好

存储格式:
    # 标题
    ## 分区名
    - 条目一
    - 条目二

支持检索/写入/持久化/上下文注入，零外部依赖。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class MemoryStore:
    """L1 核心记忆存储。

    以 Markdown 文件为持久化后端，提供内存缓存 + 磁盘同步 的两层读写模型。
    所有操作线程不安全 —— 适用于单线程 REPL 场景。

    Attributes:
        _facts: 核心记忆条目字典 {"memory": [...], "user": [...]}
    """

    _FILE_MAP = {"memory": "MEMORY.md", "user": "USER.md"}

    def __init__(self) -> None:
        """初始化空的记忆存储。"""
        self._facts: dict[str, list[str]] = {"memory": [], "user": []}

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def load_from_disk(self, memories_dir: Path) -> None:
        """从磁盘加载 MEMORY.md 和 USER.md。

        Args:
            memories_dir: 记忆文件目录路径 (通常为 ~/.sinan/memories/)

        Raises:
            FileNotFoundError: 目录不存在时抛出，调用方应确保目录已创建。
        """
        if not memories_dir.is_dir():
            raise FileNotFoundError(f"记忆目录不存在: {memories_dir}")

        for category, filename in self._FILE_MAP.items():
            file_path = memories_dir / filename
            if not file_path.exists():
                continue
            facts = self._parse_markdown_facts(file_path.read_text(encoding="utf-8"))
            self._facts[category] = facts

    def _parse_markdown_facts(self, content: str) -> list[str]:
        """解析 Markdown 文件中的条目。

        提取以 ``- `` 开头的行作为条目，跳过标题和空行。

        Args:
            content: Markdown 文件原始文本。

        Returns:
            条目文本列表。
        """
        facts: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                fact = stripped[2:].strip()
                if fact:
                    facts.append(fact)
        return facts

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def add_fact(self, fact: str) -> bool:
        """添加项目记忆条目 (MEMORY.md)。

        Args:
            fact: 事实内容。

        Returns:
            True 表示已添加，False 表示重复跳过。
        """
        return self._add("memory", fact)

    def add_user_pref(self, fact: str) -> bool:
        """添加用户偏好条目 (USER.md)。

        Args:
            fact: 偏好内容。

        Returns:
            True 表示已添加，False 表示重复跳过。
        """
        return self._add("user", fact)

    def remember_fact(self, fact: str) -> bool:
        """add_fact 的别名 —— 向后兼容。

        Args:
            fact: 事实内容。

        Returns:
            True 表示已添加，False 表示重复跳过。
        """
        return self.add_fact(fact)

    def _add(self, category: str, fact: str) -> bool:
        """内部添加逻辑 —— 去重后追加。

        Args:
            category: 记忆分类 ("memory" 或 "user")。
            fact: 条目内容。

        Returns:
            True 表示已添加，False 表示重复。
        """
        if fact in self._facts[category]:
            return False
        self._facts[category].append(fact)
        return True

    def flush_to_disk(self, memories_dir: Path) -> None:
        """将所有记忆写回磁盘。

        Args:
            memories_dir: 记忆文件目录路径。
        """
        memories_dir.mkdir(parents=True, exist_ok=True)

        for category, filename in self._FILE_MAP.items():
            file_path = memories_dir / filename
            content = self._render_markdown(category, self._facts[category])
            file_path.write_text(content, encoding="utf-8")

    def _render_markdown(self, category: str, facts: list[str]) -> str:
        """渲染 Markdown 文件内容。

        Args:
            category: 分类名。
            facts: 条目列表。

        Returns:
            完整的 Markdown 文本。
        """
        title_map = {"memory": "项目记忆", "user": "用户偏好"}
        title = title_map.get(category, category)

        lines = ["# 司南项目记忆", "", f"## {title}", ""]
        for fact in facts:
            lines.append(f"- {fact}")
        if not facts:
            lines.append("(暂无记录)")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def build_context(self) -> str:
        """构建系统提示可注入的上下文字符串。

        LLM 通过此方法获取项目记忆和用户偏好的摘要。

        Returns:
            格式化的上下文文本，无内容时返回空字符串。
        """
        parts: list[str] = []

        memory_facts = self._facts.get("memory", [])
        if memory_facts:
            parts.append("## 项目记忆")
            for fact in memory_facts:
                parts.append(f"- {fact}")

        user_facts = self._facts.get("user", [])
        if user_facts:
            if parts:
                parts.append("")
            parts.append("## 用户偏好")
            for fact in user_facts:
                parts.append(f"- {fact}")

        return "\n".join(parts)

    def find_memories(self, query: str) -> list[str]:
        """在所有记忆条目中做子串搜索。

        Args:
            query: 搜索关键词。

        Returns:
            匹配的条目文本列表。
        """
        results: list[str] = []
        for facts in self._facts.values():
            for fact in facts:
                if query.lower() in fact.lower():
                    results.append(fact)
        return results

    def get_user_preference(self, key: str) -> str:
        """查找用户偏好中匹配 ``key: value`` 格式的条目。

        Args:
            key: 偏好键名。

        Returns:
            对应的值字符串，未找到返回空字符串。
        """
        for fact in self._facts.get("user", []):
            if fact.startswith(key + ":"):
                return fact[len(key) + 1:].strip()
        return ""

    def get_facts(self) -> list[str]:
        """获取所有项目记忆条目。

        Returns:
            项目记忆文本列表。
        """
        return list(self._facts["memory"])

    def get_user_prefs(self) -> list[str]:
        """获取所有用户偏好条目。

        Returns:
            用户偏好文本列表。
        """
        return list(self._facts["user"])

    def get_capacity(self) -> str:
        """返回记忆容量摘要。

        Returns:
            格式化的容量字符串。
        """
        m = len(self._facts["memory"])
        u = len(self._facts["user"])
        return f"📁 项目记忆: {m} 条 / 用户偏好: {u} 条"

    def remove_fact(self, idx: int) -> bool:
        """按索引移除项目记忆条目。

        Args:
            idx: 条目索引。

        Returns:
            True 表示移除成功，False 表示索引无效。
        """
        facts = self._facts["memory"]
        if 0 <= idx < len(facts):
            facts.pop(idx)
            return True
        return False

    # ------------------------------------------------------------------
    # 管理
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """清空所有内存中的记忆（不写回磁盘）。"""
        self._facts = {"memory": [], "user": []}

    @property
    def is_empty(self) -> bool:
        """检查是否无任何记忆条目。"""
        return not self._facts["memory"] and not self._facts["user"]

    @property
    def fact_count(self) -> int:
        """返回记忆条目总数。"""
        return len(self._facts["memory"]) + len(self._facts["user"])
