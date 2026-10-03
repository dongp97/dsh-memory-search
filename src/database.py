"""数据库连接管理与 Schema 初始化"""

import sqlite3
from pathlib import Path

# Schema 定义 — 使用 FTS5 external content 模式
# FTS 表 rowid = sessions.id，触发器自动同步
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL UNIQUE,
    session_date TEXT NOT NULL,
    title       TEXT,
    file_path   TEXT NOT NULL UNIQUE,
    content     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_mtime  REAL NOT NULL,
    indexed_at  REAL NOT NULL,
    created_at  REAL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(session_date);
CREATE INDEX IF NOT EXISTS idx_sessions_hash ON sessions(content_hash);

-- external content FTS5：rowid 直接引用 sessions.id
CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    title,
    content,
    session_id,
    tokenize='trigram',
    content='sessions',
    content_rowid='id'
);

-- 插入同步
CREATE TRIGGER IF NOT EXISTS sessions_ai AFTER INSERT ON sessions BEGIN
    INSERT INTO sessions_fts(rowid, title, content, session_id)
    VALUES (new.id, new.title, new.content, new.session_id);
END;

-- 删除同步
CREATE TRIGGER IF NOT EXISTS sessions_ad AFTER DELETE ON sessions BEGIN
    INSERT INTO sessions_fts(sessions_fts, rowid, title, content, session_id)
    VALUES ('delete', old.id, old.title, old.content, old.session_id);
END;

-- 更新同步
CREATE TRIGGER IF NOT EXISTS sessions_au AFTER UPDATE ON sessions BEGIN
    INSERT INTO sessions_fts(sessions_fts, rowid, title, content, session_id)
    VALUES ('delete', old.id, old.title, old.content, old.session_id);
    INSERT INTO sessions_fts(rowid, title, content, session_id)
    VALUES (new.id, new.title, new.content, new.session_id);
END;

CREATE TABLE IF NOT EXISTS index_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    """SQLite 数据库连接管理"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self) -> None:
        """初始化数据库 schema"""
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params: list) -> sqlite3.Cursor:
        return self.conn.executemany(sql, params)

    def commit(self) -> None:
        self.conn.commit()

    def begin_batch(self) -> None:
        """开启批量模式"""
        self.conn.execute("BEGIN")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        self.init_schema()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.close()
