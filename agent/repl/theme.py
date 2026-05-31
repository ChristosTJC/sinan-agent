"""
司南视觉主题系统。

统一管理 CLI 界面的颜色、面板、分隔线等视觉元素。
使用 rich 库进行渲染，同时提供 ANSI 回退方案。
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

# ── ANSI 颜色代码 ──────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# 前景色
FG_CYAN = "\033[36m"
FG_GREEN = "\033[32m"
FG_YELLOW = "\033[33m"
FG_BLUE = "\033[34m"
FG_MAGENTA = "\033[35m"
FG_RED = "\033[31m"
FG_WHITE = "\033[37m"
FG_GRAY = "\033[90m"

# 高亮前景
FG_BRIGHT_CYAN = "\033[96m"
FG_BRIGHT_GREEN = "\033[92m"
FG_BRIGHT_YELLOW = "\033[93m"
FG_BRIGHT_BLUE = "\033[94m"
FG_BRIGHT_MAGENTA = "\033[95m"

# ── 主题色 ──────────────────────────────────────────────────

BRAND_PRIMARY = FG_BRIGHT_CYAN       # 司南品牌色：亮青
BRAND_SECONDARY = FG_CYAN            # 辅助色：青
BRAND_ACCENT = FG_BRIGHT_YELLOW      # 强调色：亮黄
TEXT_PRIMARY = FG_WHITE                # 主文本
TEXT_SECONDARY = FG_GRAY               # 次文本
TEXT_SUCCESS = FG_BRIGHT_GREEN         # 成功
TEXT_WARNING = FG_BRIGHT_YELLOW        # 警告
TEXT_ERROR = FG_BRIGHT_MAGENTA         # 错误
TEXT_INFO = FG_BRIGHT_BLUE             # 信息
ROLE_USER = FG_BRIGHT_GREEN            # 用户角色
ROLE_ASSISTANT = FG_BRIGHT_CYAN        # 助手角色
ROLE_TOOL = FG_BRIGHT_YELLOW           # 工具调用
DIVIDER_COLOR = FG_GRAY                # 分隔线

# ── Rich 主题 ───────────────────────────────────────────────

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.columns import Columns
    from rich.box import ROUNDED, HEAVY, DOUBLE, MINIMAL, SIMPLE
    from rich.theme import Theme
    from rich.align import Align
    from rich.rule import Rule

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# rich 自定义主题
SINAN_THEME = {
    "sinan.brand": "bright_cyan",
    "sinan.accent": "bright_yellow",
    "sinan.user": "bright_green",
    "sinan.assistant": "bright_cyan",
    "sinan.tool": "bright_yellow",
    "sinan.dim": "bright_black",
    "sinan.success": "bright_green",
    "sinan.error": "bright_red",
    "sinan.info": "bright_blue",
    "sinan.warning": "bright_yellow",
}


def get_console() -> Any:
    """获取带司南主题的 rich Console。"""
    if not HAS_RICH:
        return None
    return Console(theme=Theme(SINAN_THEME))


# ── 彩色 Banner ─────────────────────────────────────────────

# 像素 logo 行（每行用 ANSI 着色）
BANNER_LOGO = [
    "███████╗██╗███╗   ██╗ █████╗ ███╗   ██╗",
    "██╔════╝██║████╗  ██║██╔══██╗████╗  ██║",
    "███████╗██║██╔██╗ ██║███████║██╔██╗ ██║",
    "╚════██║██║██║╚██╗██║██╔══██║██║╚██╗██║",
    "███████║██║██║ ╚████║██║  ██║██║ ╚████║",
    "╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝",
]

BANNER_TAGLINE = "司南 · 嵌入式智能体工作台"
BANNER_VERSION = "v0.1.0"


def render_banner() -> str:
    """渲染彩色 banner 字符串。"""
    lines: list[str] = []
    lines.append("")
    for line in BANNER_LOGO:
        lines.append(f"  {BRAND_PRIMARY}{BOLD}{line}{RESET}")
    lines.append("")
    lines.append(
        f"  {DIM}─── {RESET}{TEXT_SECONDARY}{BANNER_TAGLINE}{RESET}"
        f"  {DIM}{BANNER_VERSION}{RESET}"
    )
    lines.append("")
    return "\n".join(lines)


# ── Rich 组件辅助 ─────────────────────────────────────────────


def print_welcome_panel(console: Any, model: str, provider: str, tools_count: int) -> None:
    """打印启动欢迎面板。"""
    if not HAS_RICH or console is None:
        # 回退纯文本
        print(f"  模型: {model} ({provider})")
        print(f"  工具: {tools_count} 个")
        print(f"  输入消息开始对话，/ 查看命令，Ctrl+D 退出")
        print()
        return

    # 状态网格 — 使用 DOUBLE 边框更醒目
    table = Table(show_header=False, box=DOUBLE, padding=(0, 2))
    table.add_column("label", style="sinan.dim", width=5)
    table.add_column("value", style="sinan.brand")
    table.add_row("模型", f"{model}")
    table.add_row("后端", f"{provider}")
    table.add_row("工具", f"{tools_count} 个")

    # 快捷提示 — 更紧凑
    hints = Table(show_header=False, box=MINIMAL, padding=(0, 1))
    hints.add_column("key", style="sinan.accent", width=9)
    hints.add_column("desc", style="sinan.dim")
    hints.add_row("/help", "显示所有命令")
    hints.add_row("/skills", "查看可用技能")
    hints.add_row("/tools", "列出硬件工具")
    hints.add_row("/model", "切换模型后端")
    hints.add_row("Ctrl+C", "退出司南")

    from rich.columns import Columns
    from rich.panel import Panel
    from rich.align import Align

    panel = Panel(
        Columns([table, hints], expand=True, equal=True),
        title="[sinan.brand]◆ 快速开始[/]",
        title_align="left",
        border_style="sinan.brand",
        box=ROUNDED,
        padding=(0, 2),
    )
    console.print(panel)
    console.print()


def print_divider(console: Any) -> None:
    """打印消息分隔线。"""
    if HAS_RICH and console is not None:
        console.print(Rule(style="sinan.dim", characters="─"))
    else:
        print(f"{DIVIDER_COLOR}  {'─' * 60}{RESET}")


def print_user_header(console: Any) -> None:
    """打印用户消息标签。"""
    if HAS_RICH and console is not None:
        console.print()
        console.print("[sinan.user]❯ You[/]")
    else:
        print(f"\n{ROLE_USER}❯ You{RESET}")


def print_assistant_header(console: Any) -> None:
    """打印助手消息标签。"""
    if HAS_RICH and console is not None:
        console.print()
        console.print("[sinan.assistant]◈ 司南[/]")
    else:
        print(f"\n{ROLE_ASSISTANT}◈ 司南{RESET}")


def print_tool_status(console: Any, tool_name: str, status: str) -> None:
    """打印工具调用状态。"""
    if status == "calling":
        if HAS_RICH and console is not None:
            console.print(f"[sinan.tool]  ⚙  调用: {tool_name}[/]")
        else:
            print(f"{ROLE_TOOL}  ⚙  调用: {tool_name}...{RESET}")
    elif status == "done":
        if HAS_RICH and console is not None:
            console.print(f"[sinan.success]  ✓  {tool_name} 完成[/]")
        else:
            print(f"{TEXT_SUCCESS}  ✓  {tool_name} 完成{RESET}")


def print_tool_panel(console: Any, tool_name: str, result: str) -> None:
    """将工具调用结果用面板中展示。"""
    if HAS_RICH and console is not None:
        # 截断过长内容
        display = result if len(result) < 500 else result[:500] + "\n... (已截断)"
        panel = Panel(
            display,
            title=f"[sinan.tool] {tool_name}[/]",
            border_style="sinan.tool",
            box=ROUNDED,
            padding=(0, 1),
        )
        console.print(panel)
    else:
        print(f"  ┌─ {tool_name} ─")
        for line in result.splitlines()[:20]:
            print(f"  │ {line}")
        print(f"  └───")


def print_error(console: Any, msg: str) -> None:
    """打印错误信息。"""
    if HAS_RICH and console is not None:
        console.print(f"[sinan.error]  ✗ {msg}[/]")
    else:
        print(f"{TEXT_ERROR}  ✗ {msg}{RESET}")


def print_info(console: Any, msg: str) -> None:
    """打印提示信息。"""
    if HAS_RICH and console is not None:
        console.print(f"[sinan.info]  ℹ {msg}[/]")
    else:
        print(f"{TEXT_INFO}  ℹ {msg}{RESET}")


def print_goodbye(console: Any) -> None:
    """打印退出信息。"""
    if HAS_RICH and console is not None:
        console.print()
        console.print("[sinan.brand]  再见！[/] [sinan.dim]保持好奇，持续探索。[/]")
        console.print()
    else:
        print(f"\n  {BRAND_PRIMARY}再见！{RESET}{TEXT_SECONDARY}保持好奇，持续探索。{RESET}\n")


def print_command_result(console: Any, text: str) -> None:
    """渲染斜杠命令的输出（支持 Markdown 和 ANSI 转义码）。"""
    if HAS_RICH and console is not None:
        from rich.markdown import Markdown
        from rich.text import Text
        # Markdown 检测
        if any(c in text for c in ("#", "*", "|", "```", "- ")):
            console.print(Markdown(text))
        elif "\033" in text or "\x1b" in text:
            # ANSI 转义码 → Rich 格式
            console.print(Text.from_ansi(text))
        else:
            console.print(text, markup=False)
    else:
        print(text)


# ── 思考动画：线程 + stdout 实现，100% 可靠启停 ──────────────

import math as _math
import threading as _threading
import time as _time


_ANIM_WIDTH = 30       # 渐变条宽度
_ANIM_CYCLE = 40       # 振荡周期帧数
_ANIM_SIGMA = 4.0      # 高斯宽度
_ANIM_MARGIN = 4       # 边距
_ANIM_FPS = 12         # 刷新率


# 浅色 ANSI 渐变（256 色 + 24bit RGB 混合）
_ANIM_COLORS: list[tuple[float, str]] = [
    (0.93, "\033[38;2;140;220;255m\033[1m"),   # 亮天蓝
    (0.72, "\033[38;2;100;195;240m"),           # 中亮蓝
    (0.48, "\033[38;2;70;165;220m"),            # 中蓝
    (0.25, "\033[38;2;50;130;200m"),            # 浅中蓝
    (0.08, "\033[38;2;35;90;165m"),             # 暗蓝
    (0.00, "\033[38;2;25;50;120m"),             # 最暗蓝
]


class GradientSlider:
    """OpenCode 风格渐变滑块 — 用 daemon 线程 + stdout 实现。
    
    不依赖 Rich Live，直接在标准输出上用 \\r 覆盖刷新，
    保证 prompt_toolkit 终端状态不受干扰。
    
    用法:
        with GradientSlider() as anim:
            anim.update("司南正在检索知识库...")
            ...  # LLM 流式获取
    """
    
    def __init__(self, console: Any = None, message: str = "司南思考中..."):
        self.console = console   # 忽略，仅保持 API 兼容
        self.message = message
        self._thread: Any = None
        self._event: Any = None
        self._frame = 0
    
    def _render_frame(self) -> str:
        """渲染一帧为 ANSI 字符串。"""
        t = self._frame * 2.0 * _math.pi / _ANIM_CYCLE
        half = _ANIM_WIDTH / 2
        peak = half + (half - _ANIM_MARGIN) * _math.sin(t)
        
        parts = [f"\r  \033[38;2;120;200;240m{self.message}\033[0m "]
        for i in range(_ANIM_WIDTH):
            dist = abs(i - peak) / _ANIM_SIGMA
            alpha = _math.exp(-0.5 * dist * dist)
            for threshold, code in _ANIM_COLORS:
                if alpha > threshold:
                    parts.append(f"{code}█{RESET}")
                    break
        
        return "".join(parts)
    
    def _run(self) -> None:
        """动画线程：循环写入 stdout。"""
        interval = 1.0 / _ANIM_FPS
        while not self._event.is_set():
            sys.stdout.write(self._render_frame())
            sys.stdout.flush()
            self._frame += 1
            self._event.wait(interval)
    
    def __enter__(self) -> "GradientSlider":
        self._event = _threading.Event()
        self._frame = 0
        self._thread = _threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self
    
    def __exit__(self, *args: Any) -> None:
        self._event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        # 清除残留在当前行上的动画文字
        sys.stdout.write("\r" + " " * 70 + "\r")
        sys.stdout.flush()
    
    def stop(self) -> None:
        """提前停止动画（在首段流式文本到达时调用）。"""
        self.__exit__()
    
    def update(self, message: str) -> None:
        """运行时更新动画消息。"""
        self.message = message


def print_thinking_panel(
    console: Any,
    message: str = "司南思考中...",
) -> "GradientSlider":
    """创建 OpenCode 风格渐变滑块（返回上下文管理器）。
    
    用法:
        with print_thinking_panel(console) as anim:
            anim.update("司南正在检索知识库...")
    """
    return GradientSlider(console, message)


# ── 底部状态栏 ───────────────────────────────────────────────


def create_bottom_toolbar(
    model_ref: list[str],
    provider_ref: list[str],
    thinking_ref: list[str] | None = None,
) -> Any:
    """创建 prompt_toolkit 底部状态栏回调 — 仿 Claude Code 风格。
    
    Args:
        model_ref: 可变模型名引用。
        provider_ref: 可变后端名引用。
        thinking_ref: 可变思考强度引用 (\"off\"|\"low\"|\"medium\"|\"high\")。
    """
    _EFFORT_SYMBOL = {
        "off":    "",
        "low":    "◐",
        "medium": "◑",
        "high":   "◕",
    }

    def toolbar() -> Any:
        from prompt_toolkit.formatted_text import HTML
        
        model = model_ref[0] if model_ref else "?"
        provider = provider_ref[0] if provider_ref else "?"
        thinking = (thinking_ref[0] if thinking_ref else "off")

        # 思考强度指示器
        if thinking != "off":
            symbol = _EFFORT_SYMBOL.get(thinking, "◑")
            effort_part = f"<ansiyellow>{symbol} {thinking}</ansiyellow>  "
        else:
            effort_part = ""

        return HTML(
            f"<b><ansicyan>{provider}</ansicyan></b>"
            f"<ansimagenta> {model} </ansimagenta>"
            f"{effort_part}"
            f"<ansibrightblack> /help 帮助  Ctrl+C 退出</ansibrightblack>"
        )
    return toolbar


def create_rprompt(model_ref: list[str]) -> Any:
    """创建右侧提示（显示当前模型名）。
    
    Args:
        model_ref: 可变模型名引用。
    """
    def rprompt() -> Any:
        from prompt_toolkit.formatted_text import HTML
        return HTML(f"<ansibrightblack>[{model_ref[0]}]</ansibrightblack>")
    return rprompt


# ── 装饰辅助函数 ──────────────────────────────────────────────

def print_section_header(console: Any, title: str) -> None:
    """打印带装饰的章节标题。"""
    if HAS_RICH and console is not None:
        from rich.rule import Rule
        console.print()
        console.print(f"[sinan.brand]◆ {title}[/]", justify="center")
        console.print(Rule(style="sinan.dim", characters="─"))
    else:
        print(f"\n  ◆ {title}")
        print(f"  {'─' * 40}")


def print_key_value(console: Any, key: str, value: str, highlight: bool = True) -> None:
    """打印键值对，带颜色。"""
    if HAS_RICH and console is not None:
        style = "sinan.brand" if highlight else "sinan.dim"
        console.print(f"  [{style}]{key}:[/] {value}")
    else:
        print(f"  {key}: {value}")
