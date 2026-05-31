"""代码语法高亮器"""

from __future__ import annotations
from typing import Optional

try:
    from rich.syntax import Syntax
    from rich.console import Console
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class SyntaxHighlighter:
    """代码语法高亮器"""

    LANGUAGE_MAP = {
        "c": "c",
        "cpp": "cpp",
        "python": "python",
        "py": "python",
        "yaml": "yaml",
        "json": "json",
        "cmake": "cmake",
        "makefile": "makefile",
    }

    def highlight(
        self,
        code: str,
        language: Optional[str] = None,
        theme: str = "monokai"
    ) -> str:
        """高亮代码

        Args:
            code: 源代码
            language: 语言类型（None 表示自动检测）
            theme: 主题名称

        Returns:
            高亮后的代码字符串
        """
        if not HAS_RICH:
            return code

        if language is None:
            language = self._detect_language(code)

        lang = self.LANGUAGE_MAP.get(language.lower(), "text")

        syntax = Syntax(code, lang, theme=theme, line_numbers=False)
        console = Console()

        with console.capture() as capture:
            console.print(syntax)

        return capture.get()

    def _detect_language(self, code: str) -> str:
        """自动检测代码语言

        Args:
            code: 源代码

        Returns:
            检测到的语言类型
        """
        if "def " in code or "import " in code:
            return "python"
        if "void " in code or "#include" in code:
            return "c"
        if "{" in code and "}" in code:
            return "json"
        return "text"
