# agent/memory/knowledge_base.py
"""司南 L3 知识库模块。

封装 KnowledgeIndex（Whoosh 全文检索），管理项目知识库（knowledge/ 下 .md/.yaml）
和用户知识库（~/.sinan/knowledge/），提供文档 CRUD、全文检索、LLM 上下文注入。
"""
from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Optional, List, Dict, Any

from agent.memory.knowledge_index import KnowledgeIndex, DocumentType
from agent.config import get_sinan_home

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_DOC_TYPE_CN: Dict[str, str] = {
    "mcu": "MCU",
    "protocol": "通信协议",
    "sensor": "传感器",
    "error_code": "错误码",
    "board": "板卡",
    "general": "通用",
}

# 目录名片段 → 文档类型（与 KnowledgeIndex._infer_doc_type 逻辑一致）
_DIR_TO_DOC: Dict[str, DocumentType] = {
    "mcu": DocumentType.MCU,
    "芯片": DocumentType.MCU,
    "protocol": DocumentType.PROTOCOL,
    "协议": DocumentType.PROTOCOL,
    "sensor": DocumentType.SENSOR,
    "传感器": DocumentType.SENSOR,
    "error": DocumentType.ERROR_CODE,
    "error_codes": DocumentType.ERROR_CODE,
    "错误码": DocumentType.ERROR_CODE,
    "board": DocumentType.BOARD,
    "板卡": DocumentType.BOARD,
}

_KNOWN_SUFFIXES = (".md", ".yaml", ".yml")


class KnowledgeBase:
    """L3 知识库管理器。

    维护两套 Whoosh 索引：
    - 项目知识库：只读，从 kb_dir 自动扫描构建。
    - 用户知识库：可读写，存储于 user_kb_dir，支持运行时添加。
    索引数据持久化到 ~/.sinan/knowledge_index/。
    """

    def __init__(self, kb_dir: Path, user_kb_dir: Path = None):
        """初始化知识库。

        Args:
            kb_dir: 项目知识库根目录（必须存在）。
            user_kb_dir: 用户知识库根目录，默认 ~/.sinan/knowledge/；为 None 时仅启用项目库。

        Raises:
            ValueError: kb_dir 不存在。
            RuntimeError: Whoosh 未安装。
        """
        self.kb_dir = Path(kb_dir)
        if not self.kb_dir.is_dir():
            raise ValueError(f"项目知识库目录不存在: {self.kb_dir}")

        self.user_kb_dir = Path(user_kb_dir) if user_kb_dir else None

        index_root = get_sinan_home() / "knowledge_index"
        index_root.mkdir(parents=True, exist_ok=True)

        try:
            self._project_index = KnowledgeIndex(index_root / "project")
        except RuntimeError as exc:
            raise RuntimeError(
                "Whoosh 未安装，知识库功能不可用。请运行: pip install whoosh"
            ) from exc

        self._user_index: Optional[KnowledgeIndex] = None
        if self.user_kb_dir is not None:
            self.user_kb_dir.mkdir(parents=True, exist_ok=True)
            with suppress(RuntimeError):
                self._user_index = KnowledgeIndex(index_root / "user")

        self._auto_index()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_doc_type(filepath: Path) -> DocumentType:
        parts = filepath.parts
        for fragment, dt in _DIR_TO_DOC.items():
            if any(fragment in p for p in parts):
                return dt
        return DocumentType.GENERAL

    def _auto_index(self) -> None:
        """项目索引为空时自动扫描 kb_dir 下 .md/.yaml 文件并逐条索引。"""
        if self._project_index.get_document_count() > 0:
            return

        for suffix in _KNOWN_SUFFIXES:
            for file_path in sorted(self.kb_dir.rglob(f"*{suffix}")):
                try:
                    content = file_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                doc_type = self._infer_doc_type(file_path)
                self._project_index.add_document(
                    title=file_path.stem,
                    content=content,
                    doc_type=doc_type,
                    filepath=str(file_path),
                )

    @staticmethod
    def _str_to_doc_type(s: str) -> DocumentType:
        """字符串 → DocumentType 枚举，无效值回退为 GENERAL。"""
        try:
            return DocumentType(s)
        except ValueError:
            return DocumentType.GENERAL

    def _write_entry_file(self, category: str, title: str, content: str) -> Path:
        """写入用户知识条目文件并返回路径。"""
        if self.user_kb_dir is None:
            raise RuntimeError("用户知识库未启用（user_kb_dir 为 None）")

        cat_dir = self.user_kb_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        safe_title = title.replace("/", "_").replace("\\", "_")
        file_path = cat_dir / f"{safe_title}.md"
        file_path.write_text(content, encoding="utf-8")
        return file_path

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self, query: str, limit: int = 10, source: str = "all"
    ) -> List[Dict[str, Any]]:
        """全文检索项目/用户知识库。

        Args:
            query: 搜索关键词。
            limit: 最大返回条数。
            source: "project" / "user" / "all"。

        Returns:
            结果列表，每条含 doc_id、title、content、doc_type、score、source 字段。
        """
        results: List[Dict[str, Any]] = []

        if source in ("all", "project"):
            for r in self._project_index.search(query, limit=limit):
                r["source"] = "project"
                results.append(r)

        if source in ("all", "user") and self._user_index is not None:
            for r in self._user_index.search(query, limit=limit):
                r["source"] = "user"
                results.append(r)

        results.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
        return results[:limit]

    def semantic_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """兼容旧接口（commands.py / cli.py 调用）。

        返回 _name / _category / _score / _source / _content / _doc_id 格式。
        """
        raw = self.search(query, limit=limit)
        return [
            {
                "_name": r.get("title", ""),
                "_category": r.get("doc_type", "general"),
                "_score": r.get("score", 0.0),
                "_source": r.get("source", ""),
                "_content": r.get("content", ""),
                "_doc_id": r.get("doc_id", ""),
            }
            for r in raw
        ]

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def add_document(
        self,
        title: str,
        content: str,
        doc_type: str = "general",
        tags: Optional[List[str]] = None,
        source: str = "user",
    ) -> str:
        """添加文档到知识库索引。

        Args:
            title: 文档标题。
            content: 文档正文。
            doc_type: 类型字符串（mcu/protocol/sensor/error_code/board/general）。
            tags: 标签列表。
            source: "user" 或 "project"。

        Returns:
            新文档的 doc_id。
        """
        dt = self._str_to_doc_type(doc_type)

        if source == "user" and self._user_index is not None:
            cat = doc_type if dt != DocumentType.GENERAL else "general"
            file_path = self._write_entry_file(cat, title, content)
            return self._user_index.add_document(
                title=title, content=content, doc_type=dt,
                tags=tags, filepath=str(file_path),
            )

        return self._project_index.add_document(
            title=title, content=content, doc_type=dt, tags=tags,
        )

    def add_entry(self, *args, **kwargs) -> str:
        """添加用户知识条目（兼容旧接口）。

        支持三种调用方式：
        - ``add_entry(title, content, doc_type="general", tags=None)``
        - ``add_entry(category, title, content)``  (兼容旧代码)
        - ``add_entry(category=..., name=..., content=...)``  (关键字)

        Returns:
            写入的用户知识库文件路径。
        """
        title = ""
        content = ""
        doc_type = "general"
        tags = None

        if len(args) == 2:
            title, content = args[0], args[1]
        elif len(args) == 3:
            doc_type, title, content = args[0], args[1], args[2]
        elif len(args) > 3:
            raise TypeError(f"add_entry 接受 2-3 个位置参数，传入了 {len(args)} 个")

        for key in ("title", "name"):
            if key in kwargs:
                title = kwargs.pop(key)
        if "content" in kwargs:
            content = kwargs.pop("content")
        for key in ("doc_type", "category"):
            if key in kwargs:
                doc_type = kwargs.pop(key)
        if "tags" in kwargs:
            tags = kwargs.pop("tags")
        if kwargs:
            raise TypeError(f"add_entry 收到未知关键字参数: {list(kwargs)}")

        if not title:
            raise ValueError("add_entry 缺少 title 参数")
        if not content:
            raise ValueError("add_entry 缺少 content 参数")

        file_path = self._write_entry_file(doc_type, title, content)

        if self._user_index is not None:
            dt = self._str_to_doc_type(doc_type)
            self._user_index.add_document(
                title=title, content=content, doc_type=dt,
                tags=tags, filepath=str(file_path),
            )

        return str(file_path)

    # ------------------------------------------------------------------
    # LLM 上下文构建
    # ------------------------------------------------------------------

    def build_context(
        self, query: str = "", limit: int = 5, max_chars: int = None
    ) -> str:
        """基于查询检索知识库，构建 LLM system prompt 可用的上下文文本。

        Args:
            query: 检索关键词；为空时返回空字符串。
            limit: 最大返回条目数。
            max_chars: 输出最大字符数，超限截断；None 不限制。

        Returns:
            格式化的 Markdown 上下文文本。
        """
        if not query:
            return ""

        results = self.search(query, limit=limit)
        if not results:
            return ""

        lines = ["## 相关知识库条目", ""]
        total_chars = 0

        for i, r in enumerate(results, 1):
            r_title = r.get("title", "未知")
            r_content = r.get("content", "")
            r_doc_type = r.get("doc_type", "general")
            r_source = r.get("source", "")

            cn_type = _DOC_TYPE_CN.get(r_doc_type, r_doc_type)
            src_label = "[用户]" if r_source == "user" else "[项目]"
            header = f"### {i}. {src_label} [{cn_type}] {r_title}"

            snippet = r_content[:300] + "..." if len(r_content) > 300 else r_content

            lines.append(header)
            if snippet:
                lines.append("")
                lines.append(snippet)
            lines.append("")

            total_chars += len(header) + len(snippet) + 3
            if max_chars is not None and total_chars >= max_chars:
                break

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 类别浏览
    # ------------------------------------------------------------------

    def list_categories(self) -> List[str]:
        """列出所有知识类别（项目与用户知识库一级子目录，去重排序）。"""
        cats: set[str] = set()
        for base_dir in (self.kb_dir, self.user_kb_dir):
            if base_dir is None or not base_dir.is_dir():
                continue
            for child in base_dir.iterdir():
                if child.is_dir():
                    cats.add(child.name)
        return sorted(cats)

    def list_entries(self, category: str) -> List[Dict[str, Any]]:
        """列出某类别下所有知识条目。

        Returns:
            条目列表，每条含 _name / _category / _path 字段。
        """
        entries: List[Dict[str, Any]] = []
        for base_dir in (self.kb_dir, self.user_kb_dir):
            if base_dir is None:
                continue
            cat_dir = base_dir / category
            if not cat_dir.is_dir():
                continue
            for file_path in sorted(cat_dir.iterdir()):
                if file_path.suffix in _KNOWN_SUFFIXES:
                    entries.append({
                        "_name": file_path.stem,
                        "_category": category,
                        "_path": str(file_path),
                    })
        return entries

    def list_indexed_dirs(self) -> List[str]:
        """返回所有已索引的根目录路径列表。"""
        dirs = [str(self.kb_dir)]
        if self.user_kb_dir is not None:
            dirs.append(str(self.user_kb_dir))
        return dirs

    # ------------------------------------------------------------------
    # 索引管理
    # ------------------------------------------------------------------

    def get_entry(self, category: str, entry_name: str) -> Optional[Dict[str, Any]]:
        """按分类和名称获取单条知识条目。

        Args:
            category: 分类名（如 mcu/sensors/protocols）。
            entry_name: 条目名（文件名，不含后缀）。

        Returns:
            条目字典，含 category/content/_name 等字段；未找到返回 None。
        """
        # 优先查项目知识库
        for d in [self.kb_dir] + ([self.user_kb_dir] if self.user_kb_dir else []):
            cat_dir = d / category
            if not cat_dir.is_dir():
                continue
            for suffix in _KNOWN_SUFFIXES:
                fp = cat_dir / f"{entry_name}{suffix}"
                if fp.is_file():
                    return {
                        "_name": entry_name,
                        "_category": category,
                        "_path": str(fp),
                        "content": fp.read_text(encoding="utf-8"),
                    }
        return None

    def get_index_stats(self) -> Dict[str, int]:
        """返回索引统计: {"project_docs": N, "user_docs": M, "total": N+M}。"""
        project_docs = self._project_index.get_document_count()
        user_docs = (
            self._user_index.get_document_count() if self._user_index else 0
        )
        return {
            "project_docs": project_docs,
            "user_docs": user_docs,
            "total": project_docs + user_docs,
        }

    def rebuild_indexes(self) -> int:
        """重建全部索引（清空后重新扫描 kb_dir 与 user_kb_dir 下的 .md 文件）。

        Returns:
            索引的总文档数。
        """
        total = self._project_index.rebuild_index(self.kb_dir)
        if self._user_index and self.user_kb_dir and self.user_kb_dir.is_dir():
            total += self._user_index.rebuild_index(self.user_kb_dir)
        return total

    def close(self) -> None:
        """清理索引资源（Whoosh 自动提交/释放，本方法为显式钩子）。"""
        pass
