"""司南 CLI 入口。

提供命令行接口来访问记忆系统、知识库、板卡管理和硬件工具。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SINAN_HOME = Path.home() / ".sinan"

# ── Banner（复用 REPL 主题）──────────────────────────
def show_banner() -> None:
    """显示司南彩色像素风启动 banner。"""
    from agent.repl.theme import render_banner
    print(render_banner())


def setup_dirs() -> None:
    """确保司南数据目录存在。"""
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
        if args.user:
            ok = store.add_user_pref(args.text)
        else:
            ok = store.add_fact(args.text)
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
    try:
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
    except Exception:
        pass  # 记忆工具注册失败不影响硬件工具显示

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
