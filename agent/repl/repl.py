"""
司南交互式 REPL —— 类 Claude Code 的聊天界面。

功能:
- 彩色像素风 logo 启动画面
- 富文本面板 + 快捷提示
- prompt_toolkit 输入框 (/ 自动补全、多行、历史)
- 多轮对话 + 流式输出
- LLM 工具调用 (Tool Calling)
- rich Markdown 渲染 + 主题系统
- /model 切换模型、/clear 清空对话
- L1 核心记忆注入 + L2 会话持久化 + L3 知识库检索 + Skills 注入
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML

from agent.llm.client import LLMClient, StreamChunk, ToolCall, create_client, detect_provider
from agent.config import apply_settings, get_model_config, create_default_config
from agent.repl.commands import CommandRegistry, SlashCompleter, build_default_commands
from agent.repl.tool_bridge import (
    build_tool_call_message,
    tools_to_openai_format,
)
from agent.repl.theme import (
    get_console,
    render_banner,
    print_welcome_panel,
    print_divider,
    print_user_header,
    print_assistant_header,
    print_tool_status,
    print_tool_panel,
    print_error,
    print_info,
    print_goodbye,
    print_command_result,
    print_thinking_panel,
    create_bottom_toolbar,
    create_rprompt,
    BRAND_PRIMARY, BRAND_ACCENT, DIM, RESET, FG_GRAY,
)
from agent.tasks import TaskManager, TaskExecutor, TaskScheduler, TaskType
from agent.context import ContextManager, MessageCompactor, ThinkingChain
from agent.repl.thinking_renderer import ThinkingRenderer
from agent.repl.widgets import TaskCard, TaskStatus

logger = logging.getLogger(__name__)

# ── 系统提示词基础模板 ─────────────────────────────────────────────
_BASE_SYSTEM_PROMPT = """\
# 角色

你是嵌入式开发助手。回答简洁、准确、可操作。不编造参数，不确定时明确说明。

# 回答格式

- 默认简体中文
- 先给结论，再给步骤，最后给代码
- 代码块标注语言（c、python、cmake、yaml 等）
- 错误诊断：现象 → 可能原因 → 排查步骤

# 领域知识

- 代码示例优先 STM32 HAL + ESP-IDF，可选 Arduino
- 芯片参数标注来源（如：RM0090 §12.3 / 实测）
- 涉及 I2C/SPI/UART/CAN 时提示上拉电阻、终端电阻、波特率容差
"""


# ---------------------------------------------------------------------------
# 键绑定
# ---------------------------------------------------------------------------


def _build_keybindings() -> KeyBindings:
    """构建自定义键绑定。"""
    kb = KeyBindings()

    @kb.add("c-c")
    def _exit(event: Any) -> None:
        """Ctrl+C 退出。"""
        event.app.exit(result="__QUIT__")

    @kb.add("c-d")
    def _clear(event: Any) -> None:
        """Ctrl+D 清空当前输入。"""
        event.current_buffer.reset()

    return kb


# ---------------------------------------------------------------------------
# REPL 主类
# ---------------------------------------------------------------------------


class SinanREPL:
    """司南交互式 REPL。"""

    # 工具调用最大递归深度
    MAX_TOOL_DEPTH = 10

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        # 加载配置
        create_default_config()
        settings = apply_settings()
        
        # 命令行参数优先于配置文件
        if provider and model:
            self.provider = provider
            model_params = get_model_config(settings).get("params")
            self.client: LLMClient = create_client(provider, model, params=model_params)
        else:
            # 从配置文件加载
            model_config = get_model_config(settings)
            self.provider = provider or model_config.get("provider", detect_provider())
            model_name = model or model_config.get("name")
            model_params = model_config.get("params")
            self.client: LLMClient = create_client(self.provider, model_name, params=model_params)

        # ── 子系统初始化 ──
        self._sinan_home = Path.home() / ".sinan"
        self._memory_store = self._init_memory_store()
        self._skill_loader = self._init_skill_loader()
        self._knowledge_base = self._init_knowledge_base()
        self._session_db, self._session_id = self._init_session_db()

        # 任务系统
        self.task_manager = TaskManager()
        self.task_executor = TaskExecutor(self.task_manager, max_workers=4)
        self.task_scheduler = TaskScheduler(self.task_manager, self.task_executor)

        # 上下文管理
        self.context_manager = ContextManager(max_tokens=100000, window_size=20)
        self.message_compactor = MessageCompactor()

        # 思维链系统
        self.thinking_chain: Optional[ThinkingChain] = None
        self.thinking_renderer = ThinkingRenderer()

        # 工具（必须在构建系统提示之前初始化，因为 _build_runtime_context 需要读取工具列表）
        self._init_tools()

        # 构建动态系统提示（基础 + 运行时上下文 + L1 记忆 + Skills）
        system_prompt = self._build_system_prompt()
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]
        self.console = get_console()

        # 蒸馏计数器
        self._session_tool_calls = 0
        self._distilled = False

        # 命令系统
        self.cmd_registry = build_default_commands()
        self._inject_dynamic_commands()

        # 可变引用 — 供底部状态栏动态刷新
        self._model_ref: list[str] = [self.client.model]
        self._provider_ref: list[str] = [self.provider]
        self._thinking_ref: list[str] = [self._read_thinking_level()]

        # prompt_toolkit 输入框（底部栏仿 Claude Code 风格）
        self.session: PromptSession = PromptSession(
            history=InMemoryHistory(),
            completer=SlashCompleter(self.cmd_registry),
            key_bindings=_build_keybindings(),
            complete_while_typing=True,
            placeholder=HTML(
                "<ansibrightblack>输入消息与司南对话… (Ctrl+C 退出)</ansibrightblack>"
            ),
            bottom_toolbar=create_bottom_toolbar(
                self._model_ref, self._provider_ref, self._thinking_ref,
            ),
            rprompt=create_rprompt(self._model_ref),
        )

    def _read_thinking_level(self) -> str:
        """从当前 client params 读取思考强度。
        
        Claude 模型用 thinking dict, 其余用 reasoning_effort 字符串。
        """
        p = getattr(self, 'client', None)
        if p is None:
            return "off"
        params = getattr(p, 'params', {}) or {}
        # Anthropic 格式: {"type": "enabled", "budget_tokens": N}
        thinking = params.get("thinking")
        if isinstance(thinking, dict) and thinking.get("type") == "enabled":
            budget = thinking.get("budget_tokens", 0)
            if budget >= 12000: return "high"
            if budget >= 6000:  return "medium"
            return "low"
        # OpenAI / DeepSeek 格式: "low"|"medium"|"high"
        effort = params.get("reasoning_effort")
        if effort in ("low", "medium", "high"):
            return effort
        return "off"

    def _init_memory_store(self):
        """初始化 L1 核心记忆。"""
        from agent.memory.core_memory import MemoryStore
        store = MemoryStore()
        store.load_from_disk(self._sinan_home / "memories")
        logger.info("L1 核心记忆已加载 (%d 条)", store.fact_count)
        return store

    def _init_skill_loader(self):
        """初始化技能加载器。"""
        from agent.skills import get_skill_loader
        loader = get_skill_loader()
        logger.info("Skills 已加载: %d 个", len(loader.load_all()))
        return loader

    def _init_knowledge_base(self):
        """初始化 L3 知识库（项目知识 + 用户知识双路径）。"""
        from agent.memory.knowledge_base import KnowledgeBase
        project_kb_dir = Path(__file__).resolve().parent.parent.parent / "knowledge"
        user_kb_dir = self._sinan_home / "knowledge"
        kb = KnowledgeBase(kb_dir=project_kb_dir, user_kb_dir=user_kb_dir)
        logger.info("L3 知识库已初始化 (project=%s, user=%s)", project_kb_dir, user_kb_dir)
        return kb

    def _init_session_db(self):
        """初始化 L2 会话数据库并创建新会话。"""
        from agent.memory.session_db import SessionDB
        db = SessionDB(self._sinan_home / "sessions")
        session_id = db.create_session(
            project=db.detect_project(),
            model=self.client.model,
        )
        logger.info("L2 会话已创建: %s", session_id)
        return db, session_id

    def _build_system_prompt(self) -> str:
        """构建动态系统提示：基础人设 + 运行时上下文 + L1 记忆 + Skills。"""
        parts = [_BASE_SYSTEM_PROMPT]

        # 运行时上下文
        runtime_ctx = self._build_runtime_context()
        if runtime_ctx:
            parts.append(runtime_ctx)

        # L1 核心记忆
        if self._memory_store:
            try:
                mem_ctx = self._memory_store.build_context()
                if mem_ctx and mem_ctx.strip():
                    parts.append(mem_ctx)
            except Exception as exc:
                logger.warning("L1 记忆上下文构建失败: %s", exc)

        # Skills
        if self._skill_loader:
            try:
                skills_section = self._skill_loader.build_system_prompt_section()
                if skills_section:
                    parts.append(skills_section)
            except Exception as exc:
                logger.warning("Skills 上下文构建失败: %s", exc)

        return "\n\n".join(parts)

    def _build_runtime_context(self) -> str:
        """构建运行时上下文：日期、目录、模型、工具。"""
        lines = [
            "# 运行时",
            f"日期: {datetime.now().strftime('%Y-%m-%d')}",
        ]
        with suppress(Exception):
            lines.append(f"目录: {os.getcwd()}")
        lines.append(f"模型: {self.client.model}")
        if hasattr(self, 'openai_tools') and self.openai_tools:
            tool_names = [t['function']['name'] for t in self.openai_tools]
            lines.append(f"可用工具 ({len(tool_names)}): {', '.join(tool_names)}")
        return "\n".join(lines)

    def _inject_knowledge_context(self, user_input: str) -> None:
        """基于用户输入检索 L3 知识库，临时注入上下文。

        在 messages 中 user 消息之前插入一条 system 消息，
        调用 _remove_knowledge_context() 清理。
        """
        if not self._knowledge_base:
            return
        try:
            context = self._knowledge_base.build_context(
                query=user_input, max_chars=2000
            )
            if context:
                # 找到最后一条 user 消息的位置
                insert_idx = len(self.messages)
                for i in range(len(self.messages) - 1, -1, -1):
                    if self.messages[i].get("role") == "user":
                        insert_idx = i
                        break
                self.messages.insert(insert_idx, {
                    "role": "system",
                    "content": f"以下是与用户问题相关的知识库内容，请参考回答：\n\n{context}",
                })
                self._knowledge_injected = True
        except Exception as exc:
            logger.warning("L3 知识注入失败: %s", exc)

    def _remove_knowledge_context(self) -> None:
        """清理临时注入的知识上下文消息。"""
        if getattr(self, "_knowledge_injected", False):
            self.messages = [
                m for m in self.messages
                if not (m.get("role") == "system"
                        and "以下是与用户问题相关的知识库内容" in m.get("content", ""))
            ]
            self._knowledge_injected = False

    def _persist_message(self, role: str, content: str) -> None:
        """将消息持久化到 L2 会话数据库。"""
        if not self._session_db or not self._session_id:
            return
        try:
            self._session_db.add_message(
                self._session_id, role, content=content
            )
        except Exception as exc:
            logger.warning("L2 消息持久化失败: %s", exc)

    def _inject_dynamic_commands(self) -> None:
        """注入需要 REPL 状态的动态命令 handler。"""
        # /distill
        distill_cmd = self.cmd_registry.get("distill")
        if distill_cmd:
            distill_cmd.handler = self._cmd_distill

        # /model
        model_cmd = self.cmd_registry.get("model")
        if model_cmd:
            model_cmd.handler = self._cmd_model

        # /clear
        clear_cmd = self.cmd_registry.get("clear")
        if clear_cmd:
            clear_cmd.handler = self._cmd_clear

    def _init_tools(self) -> None:
        """初始化工具并转换为 OpenAI format。"""
        try:
            from agent.tools import get_registry
            self.tool_registry = get_registry()

            # 绑定记忆子系统，注册记忆工具 (remember_fact/add_knowledge/recall)
            self.tool_registry.set_memory_context(
                self._memory_store,
                self._knowledge_base,
                self._session_db,
                self._sinan_home,
            )

            # 重新获取工具列表（包含新注册的记忆工具）
            raw_tools = self.tool_registry.list_tools()
            self.openai_tools = tools_to_openai_format(raw_tools) if raw_tools else None
        except Exception as exc:
            logger.warning("工具初始化失败: %s", exc)
            self.tool_registry = None
            self.openai_tools = None

    # ------------------------------------------------------------------
    # 动态命令 handler
    # ------------------------------------------------------------------

    # ── 模型目录 (从 settings.json availableModels 读取) ───────────

    _THINKING_BUDGETS = {"low": 4000, "medium": 8000, "high": 16000}

    def _cmd_model(self, args: str) -> str:
        """切换模型 — 无参数时进入交互式选择器。"""
        args = args.strip()
        if args:
            return self._switch_model(args)
        return self._interactive_model_selector()

    def _interactive_model_selector(self) -> str:
        """交互式模型选择器 — ↑↓ 选模型 · ←→ 调思考强度 · Enter 确认 · q 取消。"""
        from agent.config import load_settings

        settings = load_settings()
        catalog = settings.get("availableModels", [])
        if not catalog:
            return f"\n  {DIM}⚠ settings.json 中没有配置 availableModels，请先添加模型{RESET}\n"

        # 定位当前模型
        current_model = self.client.model
        current_provider = self.provider
        start_idx = 0
        for i, entry in enumerate(catalog):
            if entry.get("model") == current_model and entry.get("provider") == current_provider:
                start_idx = i
                break

        EFFORT_LABELS = ["关闭", "低  ", "中  ", "高  "]
        EFFORT_VALS   = ["off",  "low",  "medium", "high"]

        # 初始思考强度 — 从当前状态读取
        current_level = self._thinking_ref[0]
        try:
            effort_init = EFFORT_VALS.index(current_level)
        except ValueError:
            effort_init = 0

        # 可变状态
        state = {"sel": start_idx, "effort": effort_init, "done": False, "cancel": False}

        # ── 渲染函数 ─────────────────────────────────────────
        def _render():
            """构建模型列表的 HTML（prompt_toolkit 格式）。"""
            sel = state["sel"]
            eff = state["effort"]
            lines = [
                "\n",
                "<ansicyan><b>  ◆ 选择模型  </b></ansicyan>"
                "<ansibrightblack>(↑↓ 切换  ←→ 思考强度  Enter 确认  q 取消)</ansibrightblack>",
                "<ansibrightblack>  " + "─" * 52 + "</ansibrightblack>",
            ]
            for i, entry in enumerate(catalog):
                label = entry.get("label", entry["model"])
                provider = entry["provider"]
                if i == sel:
                    # 选中行：高亮模型名 + 思考强度指示条
                    dots = " ●" * eff + " ○" * (3 - eff)
                    effort_label = EFFORT_LABELS[eff]
                    lines.append(
                        f"  <ansicyan><b>▶ {label}</b></ansicyan>"
                        f"  <ansibrightblack>← [{dots} ] →</ansibrightblack>"
                        f"  <ansicyan>{effort_label}</ansicyan>"
                    )
                else:
                    lines.append(
                        f"    <ansibrightblack>{label}</ansibrightblack>"
                        f"  <ansibrightblack>({provider})</ansibrightblack>"
                    )
            lines.append("<ansibrightblack>  " + "─" * 52 + "</ansibrightblack>")
            lines.append("<ansibrightblack>  按 Enter 确认，q 取消</ansibrightblack>")
            return HTML("\n".join(lines))

        # ── 键绑定 ───────────────────────────────────────────
        kb = KeyBindings()

        @kb.add("up")
        def _up(event: Any) -> None:
            state["sel"] = (state["sel"] - 1) % len(catalog)
            event.app.invalidate()

        @kb.add("down")
        def _down(event: Any) -> None:
            state["sel"] = (state["sel"] + 1) % len(catalog)
            event.app.invalidate()

        @kb.add("left")
        def _left(event: Any) -> None:
            state["effort"] = max(0, state["effort"] - 1)
            event.app.invalidate()

        @kb.add("right")
        def _right(event: Any) -> None:
            state["effort"] = min(len(EFFORT_VALS) - 1, state["effort"] + 1)
            event.app.invalidate()

        @kb.add("enter")
        def _enter(event: Any) -> None:
            state["done"] = True
            event.app.exit()

        @kb.add("q")
        @kb.add("escape")
        @kb.add("c-c")
        def _cancel(event: Any) -> None:
            state["cancel"] = True
            event.app.exit()

        # ── 启动 Application ─────────────────────────────────
        from prompt_toolkit.application import Application
        from prompt_toolkit.layout import Layout, HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl

        app = Application(
            layout=Layout(
                HSplit([Window(FormattedTextControl(_render, show_cursor=False))])
            ),
            key_bindings=kb,
            full_screen=True,
            erase_when_done=True,
        )
        app.run()

        if state["cancel"]:
            return "\n  已取消\n"

        entry = catalog[state["sel"]]
        effort = EFFORT_VALS[state["effort"]]
        return self._switch_model(
            f"{entry['model']}",
            effort,
        )

    def _switch_model(self, args: str, thinking_level: str = "off") -> str:
        """执行模型切换。thinking 机制根据模型名自动判定。"""
        parts = args.split(None, 1)

        try:
            settings = apply_settings()
            model_config = get_model_config(settings)
            available = model_config.get("availableModels", [])
            if len(parts) == 1:
                model_name = parts[0]
                new_provider = self._provider_for_configured_model(model_name, available)
                if not new_provider:
                    new_provider = self._detect_provider_for_model(model_name)
            else:
                new_provider = parts[0]
                model_name = parts[1]

            params = dict(model_config.get("params", {}))
            model_lower = model_name.lower()

            # 思考深度参数 — 根据模型名自动判定 thinking 格式
            # Anthropic 原生模型用 thinking dict，其余用 reasoning_effort
            if thinking_level != "off":
                if new_provider in ("claude", "anthropic") or model_lower.startswith(("claude-", "anthropic")):
                    # 先清理 reasoning_effort 残余，再设置 thinking
                    params.pop("reasoning_effort", None)
                    budget = self._THINKING_BUDGETS.get(thinking_level, 8000)
                    params["thinking"] = {"type": "enabled", "budget_tokens": budget}
                else:
                    # deepseek / openai / generic 等都用 reasoning_effort
                    # 先清理 thinking 残余，再设置 reasoning_effort
                    params.pop("thinking", None)
                    params["reasoning_effort"] = thinking_level
            else:
                params["thinking"] = None
                params["reasoning_effort"] = None

            self.client = create_client(new_provider, model_name, params=params)
            self.provider = new_provider

            # 同步底部状态栏引用
            self._model_ref[0] = model_name
            self._provider_ref[0] = new_provider
            self._thinking_ref[0] = thinking_level

            # 更新系统提示词中的运行时上下文（模型名等）
            self.messages[0]["content"] = self._build_system_prompt()

            thinking_tag = f"  思考: {thinking_level}" if thinking_level != "off" else ""
            return f"\n  {BRAND_PRIMARY}✓ 已切换{RESET} → {model_name} ({new_provider}){thinking_tag}\n"
        except Exception as exc:
            return f"\n  {DIM}✗ 切换失败: {exc}{RESET}\n"

    @staticmethod
    def _detect_provider_for_model(model_name: str) -> str:
        """根据模型名自动推断 provider。"""
        m = model_name.lower()
        if m.startswith(("claude-", "anthropic")):
            return "claude"
        if m.startswith(("gpt-", "o1-", "o3-", "o4-")):
            return "openai"
        if m.startswith("deepseek"):
            return "deepseek"
        if m.startswith(("qwen", "llama", "mistral", "codellama", "phi", "gemma")):
            return "ollama"
        if m.startswith(("glm", "chatglm")):
            return "zhipu"
        return "generic"

    @staticmethod
    def _provider_for_configured_model(model_name: str, available_models: list[dict]) -> str:
        """Return the provider explicitly configured for a model, if present."""
        for entry in available_models:
            if entry.get("model") == model_name and entry.get("provider"):
                return str(entry["provider"])
        return ""

    def _cmd_clear(self, _args: str) -> str:
        """清空当前输入行（快捷键 Ctrl+D）。"""
        return ""

    # ------------------------------------------------------------------
    # 技能蒸馏 (/distill + 退出钩子)
    # ------------------------------------------------------------------

    def _cmd_distill(self, _args: str) -> str:
        """手动触发技能蒸馏。"""
        return self._run_distillation()

    def _run_distillation(self) -> str:
        """执行蒸馏流程：转录 → LLM 提炼 → 报告 → 确认 → 写入。"""
        from agent.distill.distiller import SkillDistiller
        from agent.distill.writer import SkillWriter
        from agent.distill.report import DistillReport

        # 排除系统消息，构建转录
        transcript = [
            m for m in self.messages
            if m.get("role") in ("user", "assistant", "tool")
        ]

        if len(transcript) < 2:
            return "\n  会话太短，无可提炼内容\n"

        # 已有技能清单
        existing_skills = []
        if self._skill_loader:
            for s in self._skill_loader.load_all():
                existing_skills.append({"name": s.name, "description": s.description})

        # 提炼
        distiller = SkillDistiller()
        print_info(self.console, f"正在分析对话 ({len(transcript)} 条消息)...")
        proposals = distiller.analyze(transcript, self.client, existing_skills)

        if not proposals:
            return "\n  本次会话无可提炼内容\n"

        # 报告
        report = DistillReport(proposals)
        print_command_result(self.console, report.render())

        # 逐项确认
        writer = SkillWriter()
        for i, p in report.iter_proposals():
            print(report.render_proposal(i, p))
            try:
                answer = input(
                    f"  应用? [y / N / a=应用全部 / q=停止] "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if answer == "q":
                report.skip_all()
                break
            elif answer == "a":
                report.confirm_all()
                break
            elif answer in ("y", "yes"):
                report.confirm(i)
            else:
                report.skip(i)

        # 写入确认项
        applied = 0
        for p in report.confirmed:
            try:
                if p.type == "new_skill":
                    result = writer.write_skill(p.name, p.description, p.content)
                    if result:
                        applied += 1
                elif p.type == "new_knowledge":
                    if self._knowledge_base:
                        self._knowledge_base.add_entry(
                            category=p.category,
                            name=p.title,
                            content=p.content,
                        )
                        applied += 1
                elif p.type == "skill_update":
                    result = writer.update_skill(p.target, p.section, p.content)
                    if result:
                        applied += 1
            except Exception as exc:
                logger.warning("提案应用失败: %s", exc)

        self._distilled = True
        # 重新加载技能（新蒸馏的技能下次启动可用）
        if applied > 0 and self._skill_loader:
            self._skill_loader.load_all(reload=True)
            # 重建系统提示（让新技能即刻注入）
            self.messages[0]["content"] = self._build_system_prompt()

        return report.summary()

    def _handle_exit(self) -> bool:
        """处理退出前蒸馏提议。

        Returns:
            False 表示继续运行（用户选择了蒸馏且希望看到结果），
            True 表示真正退出。
        """
        threshold = 5
        if (
            not self._distilled
            and self._session_tool_calls >= threshold
        ):
            try:
                answer = input(
                    f"\n  {BRAND_ACCENT}本次会话有 {self._session_tool_calls}"
                    f" 次工具调用，是否提炼? [Y/n]{RESET} "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print_goodbye(self.console)
                return True

            if answer in ("", "y", "yes"):
                print_command_result(self.console, self._run_distillation())
                return False  # 蒸馏后不退出，让用户看到结果再手动 /quit

        print_goodbye(self.console)
        return True

    # ------------------------------------------------------------------
    # 流式输出
    # ------------------------------------------------------------------

    def _stream_response(self) -> str:
        """流式获取 LLM 响应并实时显示。

        Returns:
            完整的 assistant 回复文本。
        """
        full_text = ""
        all_tool_calls: list[ToolCall] = []
        tool_call_buffer: list[ToolCall] = []

        try:
            # 显示思考动画
            with print_thinking_panel(self.console) as anim:
                anim_started = True
                for chunk in self.client.chat_stream(
                    self.messages, tools=self.openai_tools
                ):
                    # 收到第一个 chunk（任意类型）时立即停动画
                    if anim_started:
                        anim.stop()
                        anim_started = False
                    
                    if chunk.type == "text":
                        print(chunk.content, end="", flush=True)
                        full_text += chunk.content
                    elif chunk.type == "tool_call" and chunk.tool_call:
                        tool_call_buffer.append(chunk.tool_call)
                    elif chunk.type == "done":
                        break
        except Exception as exc:
            print_error(self.console, f"LLM 调用失败: {exc}")
            return full_text

        # 如果输出以换行结尾则不加额外换行
        if full_text and not full_text.endswith("\n"):
            print()

        all_tool_calls = tool_call_buffer
        self._pending_tool_calls = all_tool_calls
        self._pending_text = full_text

        return full_text

    # ------------------------------------------------------------------
    # 工具调用处理 (迭代式，带深度上限)
    # ------------------------------------------------------------------

    def _handle_tool_calls(self, text: str, tool_calls: list[ToolCall]) -> None:
        """处理 LLM 返回的工具调用，执行并将结果回传。

        使用迭代代替递归，防止工具调用链无限增长。
        最大深度由 MAX_TOOL_DEPTH 控制。
        """
        depth = 0

        # 计数工具调用（用于退出时蒸馏提议阈值判断）
        self._session_tool_calls += len(tool_calls)

        while tool_calls and depth < self.MAX_TOOL_DEPTH:
            depth += 1

            if not self.tool_registry:
                break

            # 将 assistant 消息 (含 tool_calls) 加入历史
            self.messages.append(build_tool_call_message(text, tool_calls))

            # 状态回调
            def _status(name: str, status: str) -> None:
                # 使用 TaskCard 显示工具状态
                if status == "running":
                    card = TaskCard(
                        name=name,
                        status=TaskStatus.RUNNING,
                        description=f"执行 {name}..."
                    )
                    print(card.render())
                else:
                    print_tool_status(self.console, name, status)

            # 审批回调：危险工具需要用户确认
            def _approval(name: str, args: dict) -> bool:
                import json as _json
                args_str = _json.dumps(args, ensure_ascii=False, indent=2)
                print(f"\n  {BRAND_ACCENT}⚠ 危险工具{RESET}: {name}")
                print(f"  {DIM}参数: {args_str}{RESET}")
                try:
                    answer = input(f"  {BRAND_ACCENT}是否执行? [y/N]{RESET} ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    return False
                return answer in ("y", "yes")

            # 执行所有工具调用（直接调用，不经过任务系统以避免 dict→str 转换）
            for tool_call in tool_calls:
                msg = self._execute_single_tool(tool_call, _status, _approval)
                self.messages.append(msg)

            # 继续获取 LLM 的后续回复 (tool -> assistant)
            print_assistant_header(self.console)
            followup_text = self._stream_response()

            # 获取新一轮的 tool_calls
            next_tool_calls = (
                self._pending_tool_calls
                if hasattr(self, "_pending_tool_calls") and self._pending_tool_calls
                else []
            )

            if next_tool_calls:
                # followup 含后续工具调用 → 文本作为下一轮的 assistant content
                text = followup_text
                tool_calls = next_tool_calls
            else:
                # 无后续工具调用 → 将最终文本加入历史
                if followup_text:
                    self.messages.append({"role": "assistant", "content": followup_text})
                    self._persist_message("assistant", followup_text)
                return

        # 达到深度上限
        if tool_calls and depth >= self.MAX_TOOL_DEPTH:
            print_info(
                self.console,
                f"工具调用轮次已达上限 ({self.MAX_TOOL_DEPTH})，已终止递归。",
            )

    def _execute_single_tool(self, tool_call: ToolCall, status_callback, approval_callback) -> dict:
        """执行单个工具调用并返回结果消息。"""
        name = tool_call.name
        args = tool_call.arguments
        start_time = __import__("time").time()
        danger = self.tool_registry.get_danger_level(name).value

        # 发射 ToolStartEvent
        self._emit_tool_event("start", name, danger, args)

        # 状态回调
        status_callback(name, "running")

        # 执行工具
        approved = {"value": None}
        prev_callback = getattr(self.tool_registry, "_confirm_callback", None)
        prev_danger_confirm = getattr(self.tool_registry, "_danger_confirm", True)

        def _confirm(tool_name: str, _level: str, arguments: dict) -> bool:
            ok = approval_callback(tool_name, arguments)
            approved["value"] = ok
            return ok

        try:
            if self.tool_registry.is_dangerous(name):
                self.tool_registry.set_confirm_callback(_confirm)
                self.tool_registry.set_danger_confirm(True)
                # 发射 ApprovalRequiredEvent
                from agent.orchestration.events import ApprovalRequiredEvent
                self._emit_tool_event_raw(ApprovalRequiredEvent(
                    tool_name=name,
                    danger_level=self.tool_registry.get_danger_level(name).value,
                    arguments=args,
                ))
            result = self.tool_registry.call_tool(name, args)
            status_callback(name, "rejected" if approved["value"] is False else "done")
            # 发射 ToolDoneEvent
            duration = (__import__("time").time() - start_time) * 1000.0
            success = result.get("success", False)
            self._emit_tool_event("done", name, danger, args,
                                  success=success, duration=duration,
                                  summary="ok" if success else result.get("error", "failed"))
            # 压缩工具输出
            output = self.message_compactor.compress_tool_result(
                name, str(result), max_chars=400
            )
            return {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": name,
                "content": output,
            }
        except Exception as exc:
            status_callback(name, "error")
            # 发射 ToolErrorEvent
            self._emit_tool_event("error", name, "safe", args,
                                  error=str(exc))
            logger.exception("工具执行失败: %s", name)
            output = self.message_compactor.compress_tool_result(
                name, f"错误: {exc}", max_chars=200
            )
            return {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": name,
                "content": output,
            }
        finally:
            if hasattr(self.tool_registry, "set_confirm_callback"):
                self.tool_registry.set_confirm_callback(prev_callback)
            if hasattr(self.tool_registry, "set_danger_confirm"):
                self.tool_registry.set_danger_confirm(prev_danger_confirm)

    def _emit_tool_event(self, kind: str, name: str, danger: str,
                         args: dict, **extra):
        """Emit SinanEvent to event writer if available."""
        e = None
        if kind == "start":
            from agent.orchestration.events import ToolStartEvent
            e = ToolStartEvent(tool_name=name, danger_level=danger, arguments=args)
        elif kind == "done":
            from agent.orchestration.events import ToolDoneEvent
            e = ToolDoneEvent(tool_name=name, danger_level=danger,
                              success=extra.get("success", False),
                              duration_ms=extra.get("duration", 0),
                              result_summary=extra.get("summary", ""))
        elif kind == "error":
            from agent.orchestration.events import ToolErrorEvent
            e = ToolErrorEvent(tool_name=name, error=extra.get("error", "unknown"))
        if e:
            self._write_event(e)

    def _emit_tool_event_raw(self, event):
        self._write_event(event)

    def _write_event(self, event):
        """Write SinanEvent to ~/.sinan/repl_events/event.jsonl."""
        try:
            from dataclasses import asdict
            from pathlib import Path
            from agent.orchestration.events import sanitize_event_payload
            log_dir = Path.home() / ".sinan" / "repl_events"
            log_dir.mkdir(parents=True, exist_ok=True)
            d = sanitize_event_payload(asdict(event))
            d.setdefault("timestamp", __import__("time").time())
            with open(log_dir / "event.jsonl", "a") as f:
                f.write(__import__("json").dumps(d, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def run(self) -> None:
        """启动 REPL 主循环。"""
        # 显示彩色 banner
        print(render_banner())
        # 显示欢迎面板
        tools_count = len(self.openai_tools) if self.openai_tools else 0
        print_welcome_panel(
            self.console,
            model=self.client.model,
            provider=self.provider,
            tools_count=tools_count,
        )

        while True:
            # 彻底刷新 stdout，确保 prompt_toolkit 拿到干净的终端状态
            sys.stdout.flush()
            try:
                user_input = self.session.prompt(
                    HTML("<b><ansicyan>❯</ansicyan></b> "),
                )
            except KeyboardInterrupt:
                if self._handle_exit():
                    break
            except EOFError:
                continue
        
            if user_input == "__QUIT__" and self._handle_exit():
                break
        
            user_input = user_input.strip()
            if not user_input:
                continue

            # 处理斜杠命令
            if user_input.startswith("/"):
                result = self.cmd_registry.execute(user_input)
                if result == "__QUIT__" and self._handle_exit():
                    break
                if result is not None:
                    print_command_result(self.console, result)
                else:
                    print_error(
                        self.console,
                        f"未知命令: {user_input}，输入 /help 查看帮助"
                    )
                continue

            # L3 知识注入（临时，本轮有效）
            self._inject_knowledge_context(user_input)

            # 上下文压缩（在添加新消息前）
            self.messages = self.context_manager.compact(self.messages)

            # 用户消息加入历史
            self.messages.append({"role": "user", "content": user_input})
            self._persist_message("user", user_input)

            # 启动思维会话
            session_id = f"session-{datetime.now().timestamp()}"
            self.thinking_chain = ThinkingChain(session_id=session_id)

            # 消息间分隔 + 助手标签（仅在有实质内容时渲染）
            print_divider(self.console)
            print_assistant_header(self.console)

            self._pending_tool_calls = []
            self._pending_text = ""

            try:
                text = self._stream_response()
            except Exception as exc:
                print_error(self.console, str(exc))
                self.messages.pop()  # 移除失败的用户消息
                self._remove_knowledge_context()
                continue

            # 清理临时知识上下文
            self._remove_knowledge_context()

            # 处理工具调用
            tool_calls = self._pending_tool_calls
            if tool_calls:
                self._handle_tool_calls(text, tool_calls)
            else:
                # 纯文本回复，加入历史
                if text:
                    self.messages.append({"role": "assistant", "content": text})
                    self._persist_message("assistant", text)


# ---------------------------------------------------------------------------
# 入口函数
# ---------------------------------------------------------------------------


def start_repl(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> int:
    """启动交互式 REPL。

    Args:
        provider: LLM 后端名称。
        model: 模型名称。

    Returns:
        退出码。
    """
    try:
        repl = SinanREPL(provider=provider, model=model)
        repl.run()
        return 0
    except Exception as exc:
        print(f"\n  启动失败: {exc}")
        logger.exception("REPL 启动失败")
        return 1
