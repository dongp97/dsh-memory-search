"""FTS5 全文检索引擎"""

try:
    from .database import Database
    from .models import SearchResult
except ImportError:
    from database import Database
    from models import SearchResult


def search(db: Database, query: str, limit: int = 10) -> list[SearchResult]:
    """
    执行 FTS5 全文检索，按 BM25 相关性排序。
    查询不足 3 字符时（trigram 最小粒度），自动回退 LIKE 全表扫描。
    """
    # 清理查询，防止 FTS5 语法错误（引号、括号等）
    clean_query = query.strip()

    if len(clean_query) < 3:
        # LIKE 回退：短查询无法使用 trigram 索引
        sql = """
            SELECT session_id, session_date, title, file_path,
                   0.0 AS rank
            FROM sessions
            WHERE content LIKE ? OR title LIKE ?
            LIMIT ?
        """
        like_pattern = f"%{clean_query}%"
        rows = db.execute(sql, (like_pattern, like_pattern, limit)).fetchall()
    else:
        sql = """
            SELECT s.session_id, s.session_date, s.title, s.file_path,
                   bm25(sessions_fts) AS rank
            FROM sessions_fts
            JOIN sessions s ON s.id = sessions_fts.rowid
            WHERE sessions_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        rows = db.execute(sql, (clean_query, limit)).fetchall()

    return [
        SearchResult(
            session_id=row["session_id"],
            session_date=row["session_date"],
            title=row["title"],
            file_path=row["file_path"],
            rank=row["rank"],
        )
        for row in rows
    ]


def get_snippet(db: Database, session_id: str, query: str, width: int = 80) -> str | None:
    """
    使用 FTS5 snippet() 函数获取带高亮的摘要片段
    """
    sql = """
        SELECT snippet(sessions_fts, 2, '<b>', '</b>', '…', 10) AS snip
        FROM sessions_fts
        JOIN sessions s ON s.id = sessions_fts.rowid
        WHERE sessions_fts MATCH ? AND s.session_id = ?
        LIMIT 1
    """
    row = db.execute(sql, (query, session_id)).fetchone()
    return row["snip"] if row else None


def get_stats(db: Database) -> dict:
    """获取索引统计信息"""
    total = db.execute("SELECT COUNT(*) AS cnt FROM sessions").fetchone()["cnt"]
    earliest = db.execute(
        "SELECT MIN(indexed_at) AS ts FROM sessions"
    ).fetchone()["ts"]
    latest = db.execute(
        "SELECT MAX(indexed_at) AS ts FROM sessions"
    ).fetchone()["ts"]
    return {
        "total_sessions": total,
        "earliest_indexed": earliest,
        "latest_indexed": latest,
    }


def get_by_id(db: Database, session_id: str) -> dict | None:
    """按 session_id 获取完整记录"""
    row = db.execute(
        "SELECT * FROM sessions WHERE session_id = ? LIMIT 1", (session_id,)
    ).fetchone()
    return dict(row) if row else None
