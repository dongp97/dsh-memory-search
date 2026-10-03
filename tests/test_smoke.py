"""冒烟测试：验证数据库 schema、FTS 全文检索、增量逻辑"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.database import Database
from src.indexer import Indexer, compute_hash, extract_title
from src.search_engine import search


def test_database_schema():
    """测试 schema 创建 + 触发器同步"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmpdb = f.name

    try:
        db = Database(tmpdb)
        db.init_schema()
        now = time.time()

        # 插入一条记录
        db.execute(
            """INSERT INTO sessions
            (session_id, session_date, title, file_path, content, content_hash, file_mtime, indexed_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            ("sess-001", "2026-10-03", "测试标题",
             r"D:\dsh\workspaces\2026-10-03\sess-001\session.md",
             "这是一条测试内容，包含记忆检索关键词",
             "hash001", now, now)
        )
        db.commit()

        # 验证主表
        row = db.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()
        assert row["c"] == 1, f"主表应为 1 条，实际 {row['c']}"

        # 验证 FTS 同步（触发器生效）
        fts_row = db.execute(
            "SELECT COUNT(*) AS c FROM sessions_fts WHERE sessions_fts MATCH ?",
            ("记忆检索",)
        ).fetchone()
        assert fts_row["c"] == 1, f"FTS 应命中 1 条，实际 {fts_row['c']}"

        # 验证 2 字符查询在 FTS 中返回 0（trigram 最小粒度=3）
        fts_row2 = db.execute(
            "SELECT COUNT(*) AS c FROM sessions_fts WHERE sessions_fts MATCH ?",
            ("记忆",)
        ).fetchone()
        assert fts_row2["c"] == 0, f"trigram 对 2 字符应返回 0，实际 {fts_row2['c']}"

        db.close()
        print("[PASS] test_database_schema")
    finally:
        os.unlink(tmpdb)


def test_search():
    """测试全文检索 + BM25 排序"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmpdb = f.name

    try:
        db = Database(tmpdb)
        db.init_schema()
        now = time.time()

        records = [
            ("s1", "2026-10-02", "Python 开发笔记", "Python 代码编写规范"),
            ("s2", "2026-10-03", "数据库优化", "SQLite 索引优化与 FTS5"),
            ("s3", "2026-10-03", "会议纪要", "讨论 Python 项目架构设计"),
        ]

        for sid, date, title, content in records:
            db.execute(
                """INSERT INTO sessions
                (session_id, session_date, title, file_path, content, content_hash, file_mtime, indexed_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (sid, date, title, rf"D:\dsh\workspaces\{date}\{sid}\session.md",
                 content, compute_hash(content.encode()), now, now)
            )
        db.commit()

        results = search(db, "Python", limit=10)
        assert len(results) == 2, f"搜索 'Python' 应返回 2 条，实际 {len(results)}"

        # 2 字符查询触发 LIKE 回退
        results_fst = search(db, "索引", limit=5)
        assert len(results_fst) == 1, f"搜索 '索引'（LIKE 回退）应返回 1 条，实际 {len(results_fst)}"

        db.close()
        print("[PASS] test_search")
    finally:
        os.unlink(tmpdb)


def test_extract_title():
    """测试标题提取"""
    assert extract_title("# 主标题\n正文") == "主标题"
    assert extract_title("正文无标题") is None
    assert extract_title("## 二级\n# 一级") == "一级"
    print("[PASS] test_extract_title")


def test_compute_hash():
    """测试 hash 计算"""
    h1 = compute_hash(b"hello world")
    h2 = compute_hash(b"hello world")
    h3 = compute_hash(b"different")
    assert h1 == h2, "相同内容 hash 一致"
    assert h1 != h3, "不同内容 hash 不同"
    assert len(h1) == 64, "SHA-256 应为 64 位十六进制"
    print("[PASS] test_compute_hash")


if __name__ == "__main__":
    test_extract_title()
    test_compute_hash()
    test_database_schema()
    test_search()
    print("\n所有测试通过！")
