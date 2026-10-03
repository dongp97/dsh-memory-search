"""CLI 入口 — 子命令分发"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .database import Database
from .indexer import Indexer
from .search_engine import search, get_stats, get_by_id

# 默认路径
DEFAULT_WORKSPACE = Path(r"D:\dsh\workspaces")
DEFAULT_DB = Path(__file__).parent.parent / "data" / "memory.db"


def _resolve_db(args_db: str | None) -> Path:
    """解析数据库路径"""
    return Path(args_db) if args_db else DEFAULT_DB


def _resolve_path(args_path: str | None) -> Path:
    """解析工作区路径"""
    return Path(args_path) if args_path else DEFAULT_WORKSPACE


def cmd_index(args: argparse.Namespace) -> None:
    """index 子命令"""
    db_path = _resolve_db(args.db)
    workspace = _resolve_path(args.path)

    if not workspace.exists():
        print(f"错误：工作区路径不存在 — {workspace}", file=sys.stderr)
        sys.exit(1)

    with Database(db_path) as db:
        indexer = Indexer(db, workspace, verbose=True)
        stats = indexer.index(force=args.force)

    print(f"\n索引完成：插入 {stats['inserted']}，更新 {stats['updated']}，"
          f"未变 {stats['unchanged']}，清理 {stats['removed']}，失败 {stats['errors']}")


def cmd_search(args: argparse.Namespace) -> None:
    """search 子命令"""
    db_path = _resolve_db(args.db)
    if not db_path.exists():
        print(f"错误：数据库不存在 — {db_path}，请先运行 'index' 命令", file=sys.stderr)
        sys.exit(1)

    db = Database(db_path)
    results = search(db, args.query, limit=args.limit)
    db.close()

    if args.json:
        output = [
            {
                "session_id": r.session_id,
                "session_date": r.session_date,
                "title": r.title,
                "file_path": r.file_path,
                "rank": round(r.rank, 4),
                "snippet": r.snippet,
            }
            for r in results
        ]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        if not results:
            print("未找到匹配结果")
            return
        print(f"\n找到 {len(results)} 条结果：\n")
        for i, r in enumerate(results, 1):
            title = r.title or "(无标题)"
            print(f"  [{i}] {r.session_date} | {title}")
            print(f"      ID: {r.session_id}")
            if r.snippet:
                print(f"      摘要: {r.snippet}")
            print(f"      相关性: {r.rank:.2f}")
            print()


def cmd_stats(args: argparse.Namespace) -> None:
    """stats 子命令"""
    db_path = _resolve_db(args.db)
    if not db_path.exists():
        print(f"错误：数据库不存在 — {db_path}，请先运行 'index' 命令", file=sys.stderr)
        sys.exit(1)

    db = Database(db_path)
    stats = get_stats(db)
    db.close()

    size_mb = db_path.stat().st_size / (1024 * 1024)

    print(f"数据库：{db_path} ({size_mb:.1f} MB)")
    print(f"索引会话数：{stats['total_sessions']}")
    print(f"覆盖日期数：{stats['total_dates']}")
    print(f"总内容量：{stats['total_chars']:,} 字符")
    if stats['earliest_indexed']:
        earliest = datetime.fromtimestamp(stats['earliest_indexed'])
        print(f"最早索引：{earliest:%Y-%m-%d %H:%M}")
    if stats['latest_indexed']:
        latest = datetime.fromtimestamp(stats['latest_indexed'])
        print(f"最近更新：{latest:%Y-%m-%d %H:%M}")


def cmd_show(args: argparse.Namespace) -> None:
    """show 子命令"""
    db_path = _resolve_db(args.db)
    db = Database(db_path)
    record = get_by_id(db, args.session_id)
    db.close()

    if not record:
        print(f"未找到会话：{args.session_id}", file=sys.stderr)
        sys.exit(1)

    print(f"会话 ID：{record['session_id']}")
    print(f"日期：{record['session_date']}")
    print(f"标题：{record['title'] or '(无标题)'}")
    print(f"路径：{record['file_path']}")
    print(f"索引时间：{datetime.fromtimestamp(record['indexed_at']):%Y-%m-%d %H:%M}")
    print("-" * 60)
    print(record['content'][:2000])
    if len(record['content']) > 2000:
        print(f"\n... (共 {len(record['content']):,} 字符)")


def cmd_clean(args: argparse.Namespace) -> None:
    """clean 子命令"""
    db_path = _resolve_db(args.db)

    with Database(db_path) as db:
        indexer = Indexer(db, _resolve_path(args.path), verbose=False)
        removed = indexer.clean()

    print(f"清理完成：移除 {removed} 条不存在的记录")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dsh-memory",
        description="DSH 会话记忆智能检索工具",
    )
    parser.add_argument("-d", "--db", help="数据库路径")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # index
    p_index = subparsers.add_parser("index", help="扫描并索引会话文件")
    p_index.add_argument("-p", "--path", help="工作区路径")
    p_index.add_argument("-f", "--force", action="store_true", help="强制全量重建")
    p_index.set_defaults(func=cmd_index)

    # search
    p_search = subparsers.add_parser("search", help="全文检索")
    p_search.add_argument("query", help="搜索关键词")
    p_search.add_argument("-n", "--limit", type=int, default=10, help="返回条数")
    p_search.add_argument("--json", action="store_true", help="JSON 输出")
    p_search.set_defaults(func=cmd_search)

    # stats
    p_stats = subparsers.add_parser("stats", help="索引统计")
    p_stats.set_defaults(func=cmd_stats)

    # show
    p_show = subparsers.add_parser("show", help="查看单条会话")
    p_show.add_argument("session_id", help="会话 ID")
    p_show.set_defaults(func=cmd_show)

    # clean
    p_clean = subparsers.add_parser("clean", help="清理已删除的记录")
    p_clean.add_argument("-p", "--path", help="工作区路径")
    p_clean.set_defaults(func=cmd_clean)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
