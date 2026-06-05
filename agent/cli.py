"""司南 CLI 入口。

提供命令行接口来访问记忆系统、知识库、板卡管理和硬件工具。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from agent.config import get_sinan_home

logger = logging.getLogger(__name__)

SINAN_HOME = get_sinan_home()

# ── Banner（复用 REPL 主题）──────────────────────────
def show_banner() -> None:
    """显示司南彩色像素风启动 banner。"""
    from agent.repl.theme import render_banner
    print(render_banner())


def _cli_confirm(tool_name: str, danger_level: str, arguments: dict) -> bool:
    """CLI 交互式确认回调 — 危险工具执行前请求用户确认。"""
    print(f"\n⚠  危险工具: {tool_name} (等级: {danger_level})")
    if arguments:
        print(f"   参数: {arguments}")
    answer = input("   是否执行? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def setup_dirs() -> None:
    """确保司南数据目录存在。"""
    global SINAN_HOME
    SINAN_HOME = get_sinan_home()
    dirs = [
        SINAN_HOME / "memories",
        SINAN_HOME / "sessions",
        SINAN_HOME / "knowledge",
        SINAN_HOME / "skills",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def cmd_memory(args: argparse.Namespace) -> int:
    """管理核心记忆。"""
    from agent.memory.core_memory import MemoryStore

    store = MemoryStore()
    store.load_from_disk(SINAN_HOME / "memories")

    if args.memory_action == "list":
        print("── MEMORY.md ──")
        for i, fact in enumerate(store.get_facts()):
            print(f"  [{i}] {fact}")
        print(f"\n{store.get_capacity()}")
        print("\n── USER.md ──")
        for i, pref in enumerate(store.get_user_prefs()):
            print(f"  [{i}] {pref}")

    elif args.memory_action == "add":
        ok = store.add_user_pref(args.text) if args.user else store.add_fact(args.text)
        if ok:
            store.flush_to_disk(SINAN_HOME / "memories")
            print(f"✅ 已添加记忆")
            print(store.get_capacity())
        else:
            print("❌ 添加失败（内容未通过安全扫描）")
            return 1

    elif args.memory_action == "remove":
        idx = args.index
        ok = store.remove_fact(idx)
        if ok:
            store.flush_to_disk(SINAN_HOME / "memories")
            print(f"✅ 已移除记忆 [{idx}]")
        else:
            print(f"❌ 索引 {idx} 无效")
            return 1

    return 0


def cmd_board(args: argparse.Namespace) -> int:
    """管理板卡配置。"""
    from agent.board_knowledge.manager import BoardKnowledgeBase

    kb = BoardKnowledgeBase()
    board_dir = Path(__file__).resolve().parent.parent / "board_knowledge" / "boards"
    kb._boards_dir = board_dir

    if args.board_action == "list":
        boards = kb.list_boards()
        if boards:
            print("已注册板卡:")
            for b in boards:
                profile = kb.get_profile(b)
                if profile:
                    mcu = profile.get("mcu", {})
                    print(f"  • {b} — {profile.get('display_name', '')} ({mcu.get('arch', '')}, {mcu.get('clock', '')})")
        else:
            print("（无已注册板卡）")

    elif args.board_action == "show":
        profile = kb.get_profile(args.board_id)
        if profile:
            import json
            print(json.dumps(profile, indent=2, ensure_ascii=False))
        else:
            print(f"❌ 板卡 '{args.board_id}' 不存在")
            return 1

    elif args.board_action == "ports":
        ports = kb.get_ports(args.board_id)
        if ports:
            for p in ports:
                print(f"  {p['name']:20s} {p.get('type',''):10s} {p.get('connector',''):10s}")
        else:
            print(f"❌ 板卡 '{args.board_id}' 不存在")

    elif args.board_action == "pitfalls":
        profile = kb.get_profile(args.board_id)
        if profile:
            pitfalls = profile.get("pitfalls", [])
            if pitfalls:
                print(f"⚠️ {args.board_id} 已知坑点:")
                for i, p in enumerate(pitfalls):
                    print(f"  {i+1}. {p}")
            else:
                print("（无已知坑点）")
        else:
            print(f"❌ 板卡 '{args.board_id}' 不存在")
            return 1

    return 0


def cmd_knowledge(args: argparse.Namespace) -> int:
    """查询知识库。"""
    from agent.memory.knowledge_base import KnowledgeBase

    project_kb_dir = Path(__file__).resolve().parent.parent / "knowledge"
    user_kb_dir = SINAN_HOME / "knowledge"
    kb = KnowledgeBase(kb_dir=project_kb_dir, user_kb_dir=user_kb_dir)

    if args.kb_action == "categories":
        cats = kb.list_categories()
        print("知识库类别:")
        for c in cats:
            entries = kb.list_entries(c)
            print(f"  {c} ({len(entries)} 条目)")

    elif args.kb_action == "search":
        results = kb.semantic_search(args.query)
        if results:
            for r in results[:5]:
                name = r.get("_name", "?")
                cat = r.get("_category", "?")
                score = r.get("_score", 0)
                desc = str(r.get("description", r.get("name", "")))[:80]
                print(f"  [{cat}] {name} (相关度: {score}) — {desc}")
        else:
            print(f"❌ 未找到与 '{args.query}' 相关的内容")

    elif args.kb_action == "show":
        entry = kb.get_entry(args.category, args.entry)
        if entry:
            import yaml
            print(yaml.dump(entry, allow_unicode=True, default_flow_style=False))
        else:
            print(f"❌ 条目 '{args.entry}' 不存在于类别 '{args.category}'")
            return 1

    return 0


def cmd_session(args: argparse.Namespace) -> int:
    """查询会话记忆。"""
    from agent.memory.session_db import SessionDB

    db = SessionDB(SINAN_HOME / "sessions")

    try:
        if args.session_action == "list":
            project = args.project or db.detect_project()
            sessions = db.list_sessions(project=project)
            if sessions:
                print(f"项目 {project} 的会话记录:")
                for s in sessions:
                    print(f"  {s['id'][:20]}...  {s['created_at']}  {s.get('token_count',0)}t")
            else:
                print("（无会话记录）")

        elif args.session_action == "search":
            results = db.session_search(args.query, limit=5)
            if results:
                for r in results:
                    content = (r.get("content") or "")[:100]
                    print(f"  [{r.get('session_id','')[:12]}] {r.get('role','')}: {content}...")
            else:
                print(f"❌ 未找到与 '{args.query}' 相关的会话")
    finally:
        db.close()

    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    """列出可用硬件工具和记忆工具。"""
    from agent.tools import get_registry

    registry = get_registry()

    # 注册记忆工具（CLI 模式下也需要展示）
    from agent.memory.core_memory import MemoryStore
    from agent.memory.knowledge_base import KnowledgeBase
    from agent.memory.session_db import SessionDB

    project_kb_dir = Path(__file__).resolve().parent.parent / "knowledge"
    user_kb_dir = SINAN_HOME / "knowledge"
    store = MemoryStore()
    store.load_from_disk(SINAN_HOME / "memories")
    kb = KnowledgeBase(kb_dir=project_kb_dir, user_kb_dir=user_kb_dir)
    db = SessionDB(SINAN_HOME / "sessions")
    registry.set_memory_context(store, kb, db, SINAN_HOME)

    tools = registry.list_tools()

    if not tools:
        print("（无可用硬件工具，部分依赖可能未安装）")
        return 0

    print(f"已注册 {len(tools)} 个硬件工具:")
    for t in tools:
        name = t.get("name", "?")
        desc = t.get("description", "")[:80]
        print(f"  • {name} — {desc}")

    return 0


def cmd_rebuild_index(args: argparse.Namespace) -> int:
    """重建知识库索引。"""
    from agent.memory import KnowledgeIndex

    knowledge_dir = Path(args.knowledge_dir)
    if not knowledge_dir.exists():
        print(f"❌ 知识库目录不存在: {knowledge_dir}")
        return 1

    index_dir = SINAN_HOME / "knowledge_index"
    print("正在重建索引...")

    try:
        index = KnowledgeIndex(index_dir=index_dir)
        count = index.rebuild_index(knowledge_dir)
        print(f"✓ 索引重建完成，共索引 {count} 个文档")
        return 0
    except Exception as e:
        print(f"❌ 索引重建失败: {e}")
        return 1


def cmd_build(args: argparse.Namespace) -> int:
    """执行固件编译。"""
    from agent.tools import get_registry

    registry = get_registry()
    registry.set_confirm_callback(None if args.force else _cli_confirm)
    registry.set_danger_confirm(not args.force)

    result = registry.call_tool("build_firmware", {
        "project_path": args.project_path,
        "target": args.target,
        "env": args.env,
        "platform": args.platform,
        "chip": args.chip,
    })
    if result.get("success"):
        print("✓ 编译成功")
        if result.get("output"):
            print(result["output"])
        return 0
    else:
        print(f"❌ 编译失败: {result.get('error', '未知错误')}")
        if result.get("errors"):
            for e in result["errors"]:
                print(f"   {e}")
        return 1


def cmd_flash(args: argparse.Namespace) -> int:
    """执行固件烧录。"""
    from agent.tools import get_registry

    if not args.port and not (args.chip and args.firmware):
        print("❌ 缺少参数: --port，或使用 --chip + --firmware 走 pyOCD 烧录")
        return 1

    registry = get_registry()
    registry.set_confirm_callback(None if args.force else _cli_confirm)
    registry.set_danger_confirm(not args.force)

    if args.chip and args.firmware and args.method in ("auto", "pyocd"):
        result = registry.call_tool("pyocd_flash", {
            "firmware_path": args.firmware,
            "chip_model": args.chip,
        })
    else:
        result = registry.call_tool("flash_firmware", {
            "project_path": args.project_path,
            "port": args.port,
            "method": args.method,
            "platform": args.platform,
            "chip": args.chip,
        })
    if result.get("success"):
        print("✓ 烧录成功")
        if result.get("output"):
            print(result["output"])
        return 0
    else:
        print(f"❌ 烧录失败: {result.get('error', '未知错误')}")
        if result.get("errors"):
            for e in result["errors"]:
                print(f"   {e}")
        return 1


def cmd_demo(args: argparse.Namespace) -> int:
    """运行无硬件 demo smoke test。"""
    from agent.diagnostics import collect_demo_status, render_demo

    status = collect_demo_status(SINAN_HOME, Path(args.project_path).resolve())
    print(render_demo(status), end="")
    return 0 if status.get("success") else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    """运行环境诊断。"""
    from agent.diagnostics import collect_doctor_status, render_doctor

    status = collect_doctor_status(
        SINAN_HOME,
        Path(args.project_path).resolve(),
        scan_hardware=args.scan_hardware,
    )
    print(render_doctor(status), end="")
    return 0 if status.get("success") else 1


def cmd_report(args: argparse.Namespace) -> int:
    """生成脱敏诊断报告。"""
    from agent.diagnostics import collect_doctor_status, default_report_path, write_report

    status = collect_doctor_status(
        SINAN_HOME,
        Path(args.project_path).resolve(),
        scan_hardware=args.scan_hardware,
    )
    output = Path(args.output).expanduser() if args.output else default_report_path(SINAN_HOME)
    path = write_report(status, output)
    print(f"✓ 诊断报告已写入: {path}")
    return 0 if status.get("success") else 1


def cmd_run(args: argparse.Namespace) -> int:
    """运行可见的 6 阶段 agent loop。"""
    from agent.run_loop import SinanRunController, format_run_event

    def _print_event(event: dict) -> None:
        line = format_run_event(event)
        if line:
            print(line)

    llm_client = None
    if args.llm:
        from agent.llm.client import create_client

        llm_client = create_client(provider=args.provider, model=args.model)

    controller = SinanRunController(
        sinan_home=SINAN_HOME,
        project_path=Path(args.project_path).resolve(),
        event_callback=_print_event,
        confirm_dangerous=args.yes,
        output_dir=Path(args.output_dir).expanduser() if args.output_dir else None,
        llm_client=llm_client,
    )
    from agent.config import get_tools_config
    controller.max_tool_depth = int(get_tools_config().get("max_tool_depth", 25))
    result = controller.run(args.goal)
    return 0 if result.get("success") else 1


def cmd_diagnose_log(args: argparse.Namespace) -> int:
    """分析嵌入式串口/崩溃日志。"""
    import json
    from agent.tools.log_diagnostics import diagnose_log

    if args.file:
        try:
            log_text = Path(args.file).expanduser().read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"❌ 读取日志文件失败: {exc}")
            return 1
    else:
        log_text = " ".join(args.log or [])

    result = diagnose_log(log_text, platform=args.platform)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="sinan",
        description="司南 (Sinán) 嵌入式智能体工作台",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # memory
    mem = sub.add_parser("memory", help="管理核心记忆")
    mem.add_argument("memory_action", choices=["list", "add", "remove"])
    mem.add_argument("text", nargs="?", help="要添加的文本")
    mem.add_argument("--user", action="store_true", help="添加到 USER.md")
    mem.add_argument("--index", type=int, help="要移除的索引")

    # board
    board = sub.add_parser("board", help="管理板卡配置")
    board.add_argument("board_action", choices=["list", "show", "ports", "pitfalls"])
    board.add_argument("board_id", nargs="?", help="板卡 ID")

    # knowledge
    kb = sub.add_parser("knowledge", help="查询知识库")
    kb.add_argument("kb_action", choices=["categories", "search", "show"])
    kb.add_argument("query", nargs="?", help="搜索关键词")
    kb.add_argument("--category", help="知识库类别")
    kb.add_argument("--entry", help="条目名称")

    # session
    sess = sub.add_parser("session", help="查询会话记忆")
    sess.add_argument("session_action", choices=["list", "search"])
    sess.add_argument("query", nargs="?", help="搜索关键词")
    sess.add_argument("--project", help="项目名称")

    # build
    build = sub.add_parser("build", help="编译固件")
    build.add_argument("--project-path", default=".", help="固件项目根目录路径")
    build.add_argument("--platform", help="目标平台，如 nordic/stm32/esp32")
    build.add_argument("--chip", help="目标芯片型号，如 nRF52840")
    build.add_argument("--target", help="编译目标名 (cmake/make)")
    build.add_argument("--env", help="PlatformIO 环境名")
    build.add_argument("--force", "-f", action="store_true", help="跳过危险工具确认")

    # flash
    flash = sub.add_parser("flash", help="烧录固件到设备")
    flash.add_argument("--project-path", default=".", help="固件项目根目录路径")
    flash.add_argument("--port", "-p", help="目标串口/调试端口路径")
    flash.add_argument("--platform", help="目标平台，如 nordic/stm32/esp32")
    flash.add_argument("--chip", help="目标芯片型号，如 nRF52840")
    flash.add_argument("--firmware", help="固件文件路径；与 --chip 搭配时使用 pyOCD")
    flash.add_argument("--method", "-m", default="auto", help="烧写方法 (auto/pyocd/platformio/esptool/stm32cubeprog/openocd/jlink/arduino)")
    flash.add_argument("--force", "-f", action="store_true", help="跳过危险工具确认")

    # demo
    demo = sub.add_parser("demo", help="运行无硬件 smoke test")
    demo.add_argument("--project-path", default=".", help="用于检测构建系统的项目根目录")

    # doctor
    doctor = sub.add_parser("doctor", help="检查本机司南运行环境")
    doctor.add_argument("--project-path", default=".", help="用于检测构建系统的项目根目录")
    doctor.add_argument("--scan-hardware", action="store_true", help="额外执行只读 USB/串口扫描")

    # report
    report = sub.add_parser("report", help="生成脱敏诊断报告")
    report.add_argument("--project-path", default=".", help="用于检测构建系统的项目根目录")
    report.add_argument("--output", "-o", help="报告输出路径，默认写入 SINAN_HOME/reports/")
    report.add_argument("--scan-hardware", action="store_true", help="额外执行只读 USB/串口扫描")

    # run
    run = sub.add_parser("run", help="运行可见的 6 阶段 Agent loop")
    run.add_argument("goal", help="要交给司南执行/分析的目标")
    run.add_argument("--project-path", default=".", help="目标项目根目录")
    run.add_argument("--output-dir", help="trace 输出目录；默认写入 SINAN_HOME/runs/<run-id>/")
    run.add_argument("--yes", action="store_true", help="允许执行 MEDIUM/HIGH 危险工具")
    run.add_argument("--llm", action="store_true", help="使用已配置的 LLM 生成计划和验证结果")
    run.add_argument("--provider", help="LLM provider，如 claude/openai/ollama/generic")
    run.add_argument("--model", help="LLM 模型名称")

    # diagnose-log
    diagnose = sub.add_parser("diagnose-log", help="分析嵌入式串口/崩溃日志")
    diagnose.add_argument("log", nargs="*", help="直接传入的日志文本")
    diagnose.add_argument("--file", "-f", help="日志文件路径")
    diagnose.add_argument("--platform", help="可选平台名 esp32/stm32/nordic")

    # tools
    sub.add_parser("tools", help="列出可用硬件工具")

    # rebuild-index
    rebuild = sub.add_parser("rebuild-index", help="重建知识库索引")
    rebuild.add_argument("--knowledge-dir", default="knowledge", help="知识库目录")

    return parser


def main(argv: Optional[list] = None) -> int:
    """司南 CLI 主入口。

    无子命令时进入交互式 REPL 聊天界面。
    """
    setup_dirs()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "memory":
        return cmd_memory(args)
    elif args.command == "board":
        return cmd_board(args)
    elif args.command == "knowledge":
        return cmd_knowledge(args)
    elif args.command == "session":
        return cmd_session(args)
    elif args.command == "build":
        return cmd_build(args)
    elif args.command == "flash":
        return cmd_flash(args)
    elif args.command == "demo":
        return cmd_demo(args)
    elif args.command == "doctor":
        return cmd_doctor(args)
    elif args.command == "report":
        return cmd_report(args)
    elif args.command == "run":
        return cmd_run(args)
    elif args.command == "diagnose-log":
        return cmd_diagnose_log(args)
    elif args.command == "tools":
        return cmd_tools(args)
    elif args.command == "rebuild-index":
        return cmd_rebuild_index(args)
    else:
        # 无子命令 -> 进入交互式 REPL
        from agent.repl.repl import start_repl
        return start_repl()


if __name__ == "__main__":
    sys.exit(main())
