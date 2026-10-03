"""FTS5 全文检索引擎"""

import re

try:
    from .database import Database
    from .models import SearchResult
except ImportError:
    from database import Database
    from models import SearchResult


def escape_fts5_query(query: str) -> str:
    """转义 FTS5 特殊字符，防止语法错误

    FTS5 默认 token 中的双引号、*、^、:、() 等有特殊含义。
    策略：将非字母数字中文字符用双引号包裹整个查询为短语搜索。
    """
    stripped = query.strip()
    if not stripped:
        return '""'
    # 如果含 FTS5 操作符特殊字符，整体用双引号包裹做短语匹配
    if re.search(r'["*:^()]', stripped):
        # 内部双引号转义为两个双引号
        escaped = stripped.replace('"', '""')
        return f'"{escaped}"'
    return stripped


def search(db: Database, query: str, limit: int = 10) -> list[SearchResult]:
    """
    执行 FTS5 全文检索，按 BM25 相关性排序。
    标题命中权重提升（title BM25 权重 = 内容 BM25 * 2）。
    查询不足 3 字符时（trigram 最小粒度），自动回退 LIKE 全表扫描。
    """
    clean_query = escape_fts5_query(query.strip())

    if len(query.strip()) < 3:
        # LIKE 回退：短查询无法使用 trigram 索引
        sql = """
            SELECT session_id, session_date, title, file_path,
                   0.0 AS rank
            FROM sessions
            WHERE content LIKE ? OR title LIKE ?
            ORDER BY session_date DESC
            LIMIT ?
        """
        like_pattern = f"%{query.strip()}%"
        rows = db.execute(sql, (like_pattern, like_pattern, limit)).fetchall()
    else:
        # BM25 加权：title 权重 5.0，content 权重 1.0，session_id 权重 0.1
        # title 权重显著提升确保标题命中排名靠前
        sql = """
            SELECT s.session_id, s.session_date, s.title, s.file_path,
                   bm25(sessions_fts, 5.0, 1.0, 0.1) AS rank
            FROM sessions_fts
            JOIN sessions s ON s.id = sessions_fts.rowid
            WHERE sessions_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        rows = db.execute(sql, (clean_query, limit)).fetchall()

    results = [
        SearchResult(
            session_id=row["session_id"],
            session_date=row["session_date"],
            title=row["title"],
            file_path=row["file_path"],
            rank=row["rank"],
        )
        for row in rows
    ]

    # 为每个结果附加 snippet 摘要
    for r in results:
        r.snippet = get_snippet(db, r.session_id, query.strip())

    return results


def get_snippet(db: Database, session_id: str, query: str, width: int = 80) -> str | None:
    """
    使用 FTS5 snippet() 函数获取带高亮的摘要片段。
    返回纯文本（去除 <b></b> 标签，替换为 【】 标记）。
    """
    if len(query.strip()) < 3:
        # 短查询不走 FTS5 snippet，手动截取
        row = db.execute(
            "SELECT content FROM sessions WHERE session_id = ? LIMIT 1",
            (session_id,)
        ).fetchone()
        if not row:
            return None
        content = row["content"]
        idx = content.find(query.strip())
        if idx == -1:
            return content[:width].strip() + "…"
        start = max(0, idx - 20)
        end = min(len(content), idx + len(query.strip()) + 60)
        snippet = content[start:end].replace("\n", " ").strip()
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(content) else ""
        return f"{prefix}{snippet}{suffix}"

    safe_query = escape_fts5_query(query)
    sql = """
        SELECT snippet(sessions_fts, 1, '<b>', '</b>', '…', 10) AS snip
        FROM sessions_fts
        JOIN sessions s ON s.id = sessions_fts.rowid
        WHERE sessions_fts MATCH ? AND s.session_id = ?
        LIMIT 1
    """
    try:
        row = db.execute(sql, (safe_query, session_id)).fetchone()
    except Exception:
        return None
    if not row or not row["snip"]:
        return None
    # 将 <b></b> 转为 【】 纯文本标记（终端友好）
    snip = row["snip"]
    snip = re.sub(r'<b>', '【', snip)
    snip = re.sub(r'</b>', '】', snip)
    return snip


def get_stats(db: Database) -> dict:
    """获取索引统计信息"""
    total = db.execute("SELECT COUNT(*) AS cnt FROM sessions").fetchone()["cnt"]
    earliest = db.execute(
        "SELECT MIN(indexed_at) AS ts FROM sessions"
    ).fetchone()["ts"]
    latest = db.execute(
        "SELECT MAX(indexed_at) AS ts FROM sessions"
    ).fetchone()["ts"]
    total_chars = db.execute(
        "SELECT COALESCE(SUM(LENGTH(content)), 0) AS total FROM sessions"
    ).fetchone()["total"]
    date_count = db.execute(
        "SELECT COUNT(DISTINCT session_date) AS cnt FROM sessions"
    ).fetchone()["cnt"]
    return {
        "total_sessions": total,
        "total_dates": date_count,
        "total_chars": total_chars,
        "earliest_indexed": earliest,
        "latest_indexed": latest,
    }


def get_by_id(db: Database, session_id: str) -> dict | None:
    """按 session_id 获取完整记录"""
    row = db.execute(
        "SELECT * FROM sessions WHERE session_id = ? LIMIT 1", (session_id,)
    ).fetchone()
    return dict(row) if row else None
