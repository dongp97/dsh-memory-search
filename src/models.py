"""数据模型"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Session:
    """会话记录数据模型"""
    session_id: str
    session_date: str
    file_path: str
    content: str
    content_hash: str
    file_mtime: float
    indexed_at: float
    title: str | None = None
    id: int | None = None
    created_at: float | None = None

    @classmethod
    def from_row(cls, row: dict) -> "Session":
        """从数据库行构造 Session"""
        return cls(
            id=row.get("id"),
            session_id=row["session_id"],
            session_date=row["session_date"],
            title=row.get("title"),
            file_path=row["file_path"],
            content=row["content"],
            content_hash=row["content_hash"],
            file_mtime=row["file_mtime"],
            indexed_at=row["indexed_at"],
            created_at=row.get("created_at"),
        )


@dataclass
class SearchResult:
    """搜索结果数据模型"""
    session_id: str
    session_date: str
    title: str | None
    file_path: str
    rank: float
    snippet: str | None = None
