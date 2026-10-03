"""文件扫描与索引逻辑"""

import hashlib
import re
import sys
import time
from pathlib import Path

try:
    from .database import Database
    from .models import Session
except ImportError:
    from database import Database
    from models import Session

# DSH 会话文件相对路径模式
SESSION_FILE_NAME = "session.md"

# 严格日期格式：YYYY-MM-DD
_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def compute_hash(content: bytes) -> str:
    """计算内容的 SHA-256 指纹"""
    return hashlib.sha256(content).hexdigest()


def extract_title(content: str) -> str | None:
    """从 Markdown 内容中提取第一个 H1 标题"""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def extract_events(content: str) -> list[str]:
    """从 session.md 中提取所有 ## 事件主题"""
    events = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            events.append(stripped[3:].strip())
    return events


def scan_sessions(workspace_path: Path) -> list[Path]:
    """扫描工作区下所有 session.md 文件路径"""
    results = []
    for date_dir in sorted(workspace_path.iterdir()):
        if not date_dir.is_dir():
            continue
        if not _DATE_RE.match(date_dir.name):
            continue
        for session_dir in sorted(date_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            session_file = session_dir / SESSION_FILE_NAME
            if session_file.is_file():
                results.append(session_file)
    return results


def read_session_file(file_path: Path) -> tuple[str, str, float]:
    """读取会话文件，返回 (content, hash, mtime)"""
    content_bytes = file_path.read_bytes()
    content = content_bytes.decode("utf-8", errors="replace")
    content_hash = compute_hash(content_bytes)
    file_mtime = file_path.stat().st_mtime
    return content, content_hash, file_mtime


def parse_session_id(file_path: Path) -> str:
    """从文件路径解析 session_id（取父目录名）"""
    return file_path.parent.name


def parse_session_date(file_path: Path) -> str:
    """从文件路径解析日期（取祖父目录名）"""
    return file_path.parent.parent.name


class Indexer:
    """会话索引器 — 负责文件扫描、hash 比对、增量入库"""

    def __init__(self, db: Database, workspace_path: Path, verbose: bool = True):
        self.db = db
        self.workspace_path = workspace_path
        self.verbose = verbose
        self.stats = {"inserted": 0, "updated": 0, "unchanged": 0, "removed": 0, "errors": 0}

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"  {msg}", file=sys.stderr)

    def _get_existing(self) -> dict[str, dict]:
        """获取已索引记录 {file_path: {hash, id}}"""
        rows = self.db.execute(
            "SELECT id, file_path, content_hash FROM sessions"
        ).fetchall()
        return {row["file_path"]: {"id": row["id"], "hash": row["content_hash"]} for row in rows}

    def index(self, force: bool = False) -> dict:
        """
        执行索引
        :param force: True 则忽略 hash 比对，全量重建
        :return: 统计字典
        """
        self.stats = {"inserted": 0, "updated": 0, "unchanged": 0, "removed": 0, "errors": 0}
        existing = self._get_existing()
        all_files = scan_sessions(self.workspace_path)
        scanned_files: set[str] = set()
        now = time.time()

        self._log(f"扫描到 {len(all_files)} 个会话文件")

        # 批量提交：每 50 条 commit 一次
        batch_count = 0
        BATCH_SIZE = 50

        for file_path in all_files:
            file_path_str = str(file_path)
            scanned_files.add(file_path_str)

            try:
                content, content_hash, file_mtime = read_session_file(file_path)
            except OSError as e:
                self._log(f"⚠ 读取失败 {file_path.name}: {e}")
                self.stats["errors"] += 1
                continue

            title = extract_title(content)
            session_id = parse_session_id(file_path)
            session_date = parse_session_date(file_path)

            if not force and file_path_str in existing:
                if existing[file_path_str]["hash"] == content_hash:
                    self.stats["unchanged"] += 1
                    continue
                # 更新
                self.db.execute(
                    """UPDATE sessions SET
                        session_id=?, session_date=?, title=?,
                        content=?, content_hash=?, file_mtime=?, indexed_at=?
                    WHERE id=?""",
                    (session_id, session_date, title, content,
                     content_hash, file_mtime, now, existing[file_path_str]["id"])
                )
                self.stats["updated"] += 1
            else:
                # 插入
                self.db.execute(
                    """INSERT INTO sessions
                    (session_id, session_date, title, file_path, content,
                     content_hash, file_mtime, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (session_id, session_date, title, file_path_str,
                     content, content_hash, file_mtime, now)
                )
                self.stats["inserted"] += 1

            batch_count += 1
            if batch_count >= BATCH_SIZE:
                self.db.commit()
                batch_count = 0

        # 清理已删除文件
        for file_path_str, meta in existing.items():
            if file_path_str not in scanned_files:
                self.db.execute("DELETE FROM sessions WHERE id=?", (meta["id"],))
                self.stats["removed"] += 1

        self.db.commit()
        return self.stats

    def clean(self) -> int:
        """清理文件已不存在的记录，返回清理条数"""
        self.stats = {"inserted": 0, "updated": 0, "unchanged": 0, "removed": 0, "errors": 0}
        existing = self._get_existing()
        removed = 0
        for file_path_str, meta in existing.items():
            if not Path(file_path_str).exists():
                self.db.execute("DELETE FROM sessions WHERE id=?", (meta["id"],))
                removed += 1
        self.db.commit()
        return removed
