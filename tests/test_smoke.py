"""冒烟测试：验证数据库 schema、FTS 全文检索、增量逻辑、边界情况"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.database import Database
from src.indexer import Indexer, compute_hash, extract_title, extract_events
from src.search_engine import search, escape_fts5_query, get_snippet


# ── helpers ──────────────────────────────────────────────

def _make_db():
    """创建临时数据库并返回路径（Windows 兼容）"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _insert_session(db, sid, date, title, content, now=None):
    """插入一条测试记录"""
    if now is None:
        now = time.time()
    db.execute(
        """INSERT INTO sessions
        (session_id, session_date, title, file_path, content, content_hash, file_mtime, indexed_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (sid, date, title, rf"D:\dsh\workspaces\{date}\{sid}\session.md",
         content, compute_hash(content.encode()), now, now)
    )


# ── tests ────────────────────────────────────────────────

def test_database_schema():
    """schema 创建 + 触发器同步"""
    tmpdb = _make_db()
    try:
        db = Database(tmpdb)
        db.init_schema()
        now = time.time()

        _insert_session(db, "sess-001", "2026-10-03", "测试标题",
                        "这是一条测试内容，包含记忆检索关键词", now)
        db.commit()

        row = db.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()
        assert row["c"] == 1

        fts_row = db.execute(
            "SELECT COUNT(*) AS c FROM sessions_fts WHERE sessions_fts MATCH ?",
            ("记忆检索",)
        ).fetchone()
        assert fts_row["c"] == 1, f"FTS 应命中 1 条，实际 {fts_row['c']}"

        # 2 字符 trigram 返回 0
        fts_row2 = db.execute(
            "SELECT COUNT(*) AS c FROM sessions_fts WHERE sessions_fts MATCH ?",
            ("记忆",)
        ).fetchone()
        assert fts_row2["c"] == 0

        db.close()
        print("[PASS] test_database_schema")
    finally:
        os.unlink(tmpdb)


def test_search_bm25():
    """全文检索 + BM25 排序 + 标题加权"""
    tmpdb = _make_db()
    try:
        db = Database(tmpdb)
        db.init_schema()
        now = time.time()

        records = [
            ("s1", "2026-10-02", "Python 开发笔记", "Python 代码编写规范"),
            ("s2", "2026-10-03", "数据库优化", "SQLite 索引优化与 FTS5"),
            ("s3", "2026-10-03", "Python 会议纪要", "讨论架构设计"),  # 仅标题含 Python
        ]
        for sid, date, title, content in records:
            _insert_session(db, sid, date, title, content, now)
        db.commit()
        db.close()

        # 用新的连接测试 search()
        db2 = Database(tmpdb)
        results = search(db2, "Python", limit=10)
        db2.close()

        assert len(results) == 2, f"应返回 2 条，实际 {len(results)}"

        # 标题命中（s3 仅标题含 Python）应排前面
        assert results[0].session_id == "s3", \
            f"标题命中应排第一，实际 {results[0].session_id} (rank={results[0].rank})"

        print("[PASS] test_search_bm25")
    finally:
        os.unlink(tmpdb)


def test_search_like_fallback():
    """<3 字符查询触发 LIKE 回退"""
    tmpdb = _make_db()
    try:
        db = Database(tmpdb)
        db.init_schema()
        now = time.time()

        _insert_session(db, "s1", "2026-10-03", "标题", "SQLite 索引优化", now)
        db.commit()

        results = search(db, "索引", limit=5)
        assert len(results) == 1, f"LIKE 回退应返回 1 条，实际 {len(results)}"

        db.close()
        print("[PASS] test_search_like_fallback")
    finally:
        os.unlink(tmpdb)


def test_fts5_escape():
    """FTS5 特殊字符转义不报错"""
    tmpdb = _make_db()
    try:
        db = Database(tmpdb)
        db.init_schema()
        now = time.time()

        _insert_session(db, "s1", "2026-10-03", "测试", "包含 hello world 的内容", now)
        db.commit()

        # 含引号、括号、星号的查询不应崩溃
        for q in ['hello "world"', "test*", "a:b", "(foo)"]:
            escaped = escape_fts5_query(q)
            results = search(db, q, limit=5)
            assert isinstance(results, list), f"查询 '{q}' 应返回列表"

        db.close()
        print("[PASS] test_fts5_escape")
    finally:
        os.unlink(tmpdb)


def test_snippet():
    """snippet 摘要生成"""
    tmpdb = _make_db()
    try:
        db = Database(tmpdb)
        db.init_schema()
        now = time.time()

        _insert_session(db, "s1", "2026-10-03", "测试",
                        "这是一段很长的内容，其中包含 SQLite 关键词在中间位置", now)
        db.commit()

        results = search(db, "SQLite", limit=1)
        assert len(results) == 1
        assert results[0].snippet is not None, "应有 snippet"
        assert "SQLite" in results[0].snippet or "【SQLite】" in results[0].snippet

        db.close()
        print("[PASS] test_snippet")
    finally:
        os.unlink(tmpdb)


def test_incremental_index():
    """增量索引：hash 不变则跳过，hash 变化则更新"""
    tmpdb = _make_db()
    tmp_workspace = tempfile.mkdtemp()
    try:
        # 创建临时 workspace 结构
        date_dir = os.path.join(tmp_workspace, "2026-10-03")
        sess_dir = os.path.join(date_dir, "sess-001")
        os.makedirs(sess_dir)
        sess_file = os.path.join(sess_dir, "session.md")

        with open(sess_file, "w", encoding="utf-8") as f:
            f.write("# 原始标题\n原始内容")

        db = Database(tmpdb)
        db.init_schema()
        indexer = Indexer(db, Path(tmp_workspace), verbose=False)

        # 首次索引
        stats1 = indexer.index()
        assert stats1["inserted"] == 1
        assert stats1["unchanged"] == 0

        # 再次索引（未变化）
        stats2 = indexer.index()
        assert stats2["inserted"] == 0
        assert stats2["unchanged"] == 1

        # 修改文件
        time.sleep(0.01)  # 确保 mtime 变化
        with open(sess_file, "w", encoding="utf-8") as f:
            f.write("# 新标题\n新内容含 Python 关键词")

        # 第三次索引（应更新）
        stats3 = indexer.index()
        assert stats3["updated"] == 1
        assert stats3["unchanged"] == 0

        db.close()
        print("[PASS] test_incremental_index")
    finally:
        # 删除可能残留的 WAL/SHM 文件
        for ext in ("", "-wal", "-shm"):
            try:
                os.unlink(tmpdb + ext)
            except OSError:
                pass
        shutil.rmtree(tmp_workspace, ignore_errors=True)


def test_extract_title():
    """标题提取"""
    assert extract_title("# 主标题\n正文") == "主标题"
    assert extract_title("正文无标题") is None
    assert extract_title("## 二级\n# 一级") == "一级"
    print("[PASS] test_extract_title")


def test_extract_events():
    """事件主题提取"""
    content = "# 日期\n## 事件一\n内容A\n## 事件二\n内容B"
    events = extract_events(content)
    assert events == ["事件一", "事件二"]
    assert extract_events("无事件") == []
    print("[PASS] test_extract_events")


def test_compute_hash():
    """hash 计算"""
    h1 = compute_hash(b"hello world")
    h2 = compute_hash(b"hello world")
    h3 = compute_hash(b"different")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64
    print("[PASS] test_compute_hash")


if __name__ == "__main__":
    test_extract_title()
    test_extract_events()
    test_compute_hash()
    test_database_schema()
    test_search_bm25()
    test_search_like_fallback()
    test_fts5_escape()
    test_snippet()
    test_incremental_index()
    print("\n所有测试通过！")
