"""
司南斜杠命令系统。

提供 ``/`` 触发的交互式命令，包括:
- /help       显示帮助
- /skills     列出技能
- /tools      列出硬件工具
- /memory     查看核心记忆
- /board      查看板卡列表
- /knowledge  搜索知识库
- /model      切换模型
- /clear      清空对话
- /quit       退出
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from agent.repl.theme import (
    BRAND_PRIMARY, BRAND_ACCENT, DIM, RESET,
    TEXT_SECONDARY, TEXT_SUCCESS, TEXT_INFO, ROLE_TOOL,
    FG_CYAN, FG_GREEN, FG_YELLOW, FG_BLUE, FG_GRAY,
    BOLD,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 命令数据结构
# ---------------------------------------------------------------------------


@dataclass
class SlashCommand:
    """斜杠命令定义。"""
    name: str
    description: str
    aliases: list[str] = field(default_factory=list)
    handler: Optional[Callable[[str], Optional[str]]] = None
    hidden: bool = False


# ---------------------------------------------------------------------------
# 命令注册中心
# ---------------------------------------------------------------------------


class CommandRegistry:
    """斜杠命令注册中心。"""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, cmd: SlashCommand) -> None:
        """注册一个斜杠命令。"""
        self._commands[cmd.name] = cmd
        for alias in cmd.aliases:
            self._alias_map[alias] = cmd.name

    def get(self, name: str) -> Optional[SlashCommand]:
        """根据名称或别名获取命令。"""
        name = name.lstrip("/")
        actual = self._alias_map.get(name, name)
        return self._commands.get(actual)

    def execute(self, input_text: str) -> Optional[str]:
        """解析并执行斜杠命令。

        Args:
            input_text: 用户输入，如 ``/help`` 或 ``/model claude``

        Returns:
            命令输出文本，如果命令不存在返回 None。
        """
        parts = input_text.strip().split(maxsplit=1)
        name = parts[0].lstrip("/")
        args = parts[1] if len(parts) > 1 else ""

        cmd = self.get(name)
        if cmd is None or cmd.handler is None:
            return None

        try:
            return cmd.handler(args)
        except Exception as exc:
            return f"命令执行出错: {exc}"

    def list_visible(self) -> list[SlashCommand]:
        """返回所有非隐藏的命令列表。"""
        return [cmd for cmd in self._commands.values() if not cmd.hidden]

    def names(self) -> list[str]:
        """返回所有命令名和别名（用于补全）。"""
        names: list[str] = []
        for cmd in self._commands.values():
            if not cmd.hidden:
                names.append(f"/{cmd.name}")
                for alias in cmd.aliases:
                    names.append(f"/{alias}")
        return sorted(names)


# ---------------------------------------------------------------------------
# prompt_toolkit 补全器
# ---------------------------------------------------------------------------


class SlashCompleter(Completer):
    """斜杠命令自动补全器。

    仅在输入以 ``/`` 开头时触发补全菜单。
    """

    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    def get_completions(self, document: Document, complete_event: Any) -> list:
        text = document.text_before_cursor
        if not text.startswith("/"):
            return []

        word = text.split()[0] if text.split() else text
        prefix = word.lower()

        completions = []
        for cmd in self.registry.list_visible():
            full_name = f"/{cmd.name}"
            if full_name.lower().startswith(prefix):
                completions.append(Completion(
                    full_name,
                    start_position=-len(word),
                    display_meta=cmd.description,
                ))
            for alias in cmd.aliases:
                full_alias = f"/{alias}"
                if full_alias.lower().startswith(prefix):
                    completions.append(Completion(
                        full_alias,
                        start_position=-len(word),
                        display_meta=cmd.description,
                    ))
        return completions


# ---------------------------------------------------------------------------
# 默认命令集构建
# ---------------------------------------------------------------------------


def build_default_commands() -> CommandRegistry:
    """构建默认的斜杠命令注册中心。"""
    registry = CommandRegistry()

    # /help
    def _help(_args: str) -> str:
        lines = ["", f"  {BRAND_PRIMARY}{BOLD}可用命令{RESET}", ""]
        for cmd in registry.list_visible():
            lines.append(
                f"    {FG_CYAN}/{cmd.name}{RESET}"
                f"{' ' * max(2, 20 - len(cmd.name))}"
                f"{TEXT_SECONDARY}{cmd.description}{RESET}"
            )
        lines.append("")
        lines.append(f"  {DIM}直接输入文字与司南对话，输入 / 触发命令菜单。{RESET}")
        lines.append("")
        return "\n".join(lines)

    registry.register(SlashCommand(
        name="help", description="显示帮助信息",
        handler=_help,
    ))

    # /skills
    def _skills(_args: str) -> str:
        try:
            from agent.skills import get_skill_loader
            loader = get_skill_loader()
            skills = loader.load_all()
        except Exception as exc:
            return f"  {DIM}技能加载失败: {exc}{RESET}"

        lines = ["", f"  {BRAND_PRIMARY}{BOLD}司南技能 (Skills){RESET}", ""]
        if not skills:
            lines.append(f"    {DIM}(无已注册技能){RESET}")
        else:
            for i, skill in enumerate(skills, 1):
                lines.append(
                    f"    {FG_YELLOW}{i:2d}.{RESET} {FG_CYAN}{skill.name}{RESET}"
                    f"{' ' * max(2, 30 - len(skill.name))}"
                    f"{TEXT_SECONDARY}{skill.description}{RESET}"
                )
        lines.append("")
        return "\n".join(lines)

    registry.register(SlashCommand(
        name="skills", description="列出可用技能",
        handler=_skills,
    ))

    # /tools
    def _tools(_args: str) -> str:
        try:
            from agent.tools import get_registry
            reg = get_registry()
            tools = reg.list_tools()
        except Exception as exc:
            return f"  {DIM}工具加载失败: {exc}{RESET}"

        lines = ["", f"  {BRAND_PRIMARY}{BOLD}硬件工具{RESET}", ""]
        for t in tools:
            name = t.get("name", "?")
            desc = t.get("description", "")
            lines.append(
                f"    {FG_GREEN}•{RESET} {FG_CYAN}{name}{RESET}"
                f"{' ' * max(2, 22 - len(name))}"
                f"{TEXT_SECONDARY}{desc}{RESET}"
            )
        lines.append(f"\n  {DIM}共 {len(tools)} 个工具{RESET}")
        lines.append("")
        return "\n".join(lines)

    registry.register(SlashCommand(
        name="tools", description="列出硬件工具",
        handler=_tools,
    ))

    # /memory
    def _memory(_args: str) -> str:
        try:
            from agent.memory.core_memory import MemoryStore
            sinan_home = Path.home() / ".sinan"
            store = MemoryStore()
            store.load_from_disk(sinan_home / "memories")

            lines = ["", f"  {BRAND_PRIMARY}{BOLD}核心记忆 (MEMORY.md){RESET}", ""]
            facts = store.get_facts()
            if facts:
                for i, f in enumerate(facts):
                    lines.append(f"    {FG_YELLOW}[{i}]{RESET} {f}")
            else:
                lines.append(f"    {DIM}(空){RESET}")

            lines.append("")
            lines.append(f"  {BRAND_PRIMARY}{BOLD}用户偏好 (USER.md){RESET}")
            lines.append("")
            prefs = store.get_user_prefs()
            if prefs:
                for i, p in enumerate(prefs):
                    lines.append(f"    {FG_YELLOW}[{i}]{RESET} {p}")
            else:
                lines.append(f"    {DIM}(空){RESET}")
            lines.append("")
            return "\n".join(lines)
        except Exception as exc:
            return f"  {DIM}记忆加载失败: {exc}{RESET}"

    registry.register(SlashCommand(
        name="memory", description="查看核心记忆",
        handler=_memory,
    ))

    # /board
    def _board(_args: str) -> str:
        try:
            from agent.board_knowledge.manager import BoardKnowledgeBase
            kb = BoardKnowledgeBase()
            board_dir = Path(__file__).resolve().parent.parent.parent / "board_knowledge" / "boards"
            kb._boards_dir = board_dir
            boards = kb.list_boards()

            lines = ["", f"  {BRAND_PRIMARY}{BOLD}已注册板卡{RESET}", ""]
            if boards:
                for b in boards:
                    profile = kb.get_profile(b)
                    if profile:
                        mcu = profile.get("mcu", {})
                        lines.append(
                            f"    {FG_GREEN}•{RESET} {FG_CYAN}{b}{RESET}"
                            f" {DIM}—{RESET} {profile.get('display_name', '')} "
                            f"{DIM}({mcu.get('arch', '')}, {mcu.get('clock', '')}){RESET}"
                        )
            else:
                lines.append(f"    {DIM}(无已注册板卡){RESET}")
            lines.append("")
            return "\n".join(lines)
        except Exception as exc:
            return f"  {DIM}板卡加载失败: {exc}{RESET}"

    registry.register(SlashCommand(
        name="board", description="查看板卡列表",
        handler=_board,
    ))

    # /knowledge
    def _knowledge(args: str) -> str:
        if not args.strip():
            # 列出类别
            try:
                from agent.memory.knowledge_base import KnowledgeBase
                project_kb_dir = Path(__file__).resolve().parent.parent.parent / "knowledge"
                user_kb_dir = Path.home() / ".sinan" / "knowledge"
                kb = KnowledgeBase(kb_dir=project_kb_dir, user_kb_dir=user_kb_dir)
                cats = kb.list_categories()
                lines = ["", f"  {BRAND_PRIMARY}{BOLD}知识库类别{RESET}", ""]
                for c in cats:
                    entries = kb.list_entries(c)
                    lines.append(
                        f"    {FG_CYAN}{c}{RESET}"
                        f" {DIM}({len(entries)} 条目){RESET}"
                    )
                lines.append("")
                lines.append(f"  {DIM}用法: /knowledge <关键词>{RESET}")
                lines.append("")
                return "\n".join(lines)
            except Exception as exc:
                return f"  {DIM}知识库加载失败: {exc}{RESET}"

        # 搜索
        try:
            from agent.memory.knowledge_base import KnowledgeBase
            project_kb_dir = Path(__file__).resolve().parent.parent.parent / "knowledge"
            user_kb_dir = Path.home() / ".sinan" / "knowledge"
            kb = KnowledgeBase(kb_dir=project_kb_dir, user_kb_dir=user_kb_dir)
            results = kb.semantic_search(args.strip())
            lines = ["", f"  {BRAND_PRIMARY}搜索{RESET} \"{BRAND_ACCENT}{args.strip()}{RESET}\"", ""]
            if results:
                for r in results[:5]:
                    name = r.get("_name", "?")
                    cat = r.get("_category", "?")
                    score = r.get("_score", 0)
                    desc = str(r.get("description", r.get("name", "")))[:60]
                    lines.append(
                        f"    {DIM}[{cat}]{RESET} {FG_CYAN}{name}{RESET}"
                        f" {DIM}({score}){RESET} — {desc}"
                    )
            else:
                lines.append(f"    {DIM}(无匹配结果){RESET}")
            lines.append("")
            return "\n".join(lines)
        except Exception as exc:
            return f"  {DIM}搜索失败: {exc}{RESET}"

    registry.register(SlashCommand(
        name="knowledge", description="搜索知识库",
        handler=_knowledge,
    ))

    # /distill — 由 REPL 动态注入 handler
    registry.register(SlashCommand(
        name="distill", description="从当前会话提炼技能/知识",
    ))

    # /model — 由 REPL 动态注入 handler
    registry.register(SlashCommand(
        name="model", description="切换 LLM 模型",
    ))

    # /clear — 由 REPL 动态注入 handler
    registry.register(SlashCommand(
        name="clear", description="清空当前输入",
    ))

    # /quit
    def _quit(_args: str) -> str:
        return "__QUIT__"

    registry.register(SlashCommand(
        name="quit", description="退出",
        handler=_quit, hidden=True,
    ))

    # /settings — 查看/编辑配置
    def _settings(args: str) -> str:
        from agent.config import load_settings, SETTINGS_FILE
        
        args = args.strip()
        if not args:
            # 显示当前配置
            settings = load_settings()
            available = settings.get('availableModels', [])
            default_entry = available[0] if available else {}
            model_name = default_entry.get('model', 'N/A')
            provider = default_entry.get('provider', 'N/A')
            lines = [
                "",
                f"  {BRAND_PRIMARY}{BOLD}当前配置{RESET}",
                "",
                f"  配置文件: {FG_CYAN}{SETTINGS_FILE}{RESET}",
                f"  Provider  : {FG_GREEN}{provider}{RESET}",
                f"  Model     : {FG_GREEN}{model_name}{RESET}",
                "",
                f"  {DIM}编辑配置: nano {SETTINGS_FILE}{RESET}",
                f"  {DIM}查看示例: cat settings.json.example{RESET}",
                "",
            ]
            return "\n".join(lines)
        else:
            return f"\n  {DIM}用法: /settings （无参数查看配置）{RESET}\n"

    registry.register(SlashCommand(
        name="settings", description="查看/编辑配置",
        handler=_settings,
    ))

    return registry
