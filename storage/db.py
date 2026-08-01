"""SQLite 存储层。"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import NoticeRecord

DB_PATH = Path(__file__).parent.parent / "data" / "notices.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    raw_content TEXT,
    published_at TEXT,
    crawled_at TEXT NOT NULL,
    status TEXT DEFAULT 'raw'
);
CREATE INDEX IF NOT EXISTS idx_notices_status ON notices(status);
CREATE INDEX IF NOT EXISTS idx_notices_source ON notices(source);

CREATE TABLE IF NOT EXISTS crawl_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    total_discovered INTEGER,
    total_new INTEGER,
    total_skipped INTEGER,
    total_failed INTEGER,
    errors TEXT,
    crawled_at TEXT NOT NULL
);
"""


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """获取 SQLite 连接，自动建库建表。"""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def url_exists(conn: sqlite3.Connection, url: str) -> bool:
    """检查 URL 是否已存在（去重依据）。"""
    row = conn.execute("SELECT 1 FROM notices WHERE url = ?", (url,)).fetchone()
    return row is not None


def insert_notice(conn: sqlite3.Connection, record: NoticeRecord) -> bool:
    """插入一条通知，返回是否新增（False 表示已存在）。"""
    try:
        conn.execute(
            """INSERT INTO notices (url, source, title, raw_content, published_at, crawled_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                record.url,
                record.source,
                record.title,
                record.raw_content,
                record.published_at,
                record.crawled_at,
                record.status,
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # URL 已存在，跳过
        return False


def get_notices_by_status(conn: sqlite3.Connection, status: str, limit: int = 100) -> list[dict]:
    """按状态查询通知。"""
    rows = conn.execute(
        "SELECT * FROM notices WHERE status = ? ORDER BY crawled_at DESC LIMIT ?",
        (status, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def log_crawl(
    conn: sqlite3.Connection,
    source: str,
    total_discovered: int,
    total_new: int,
    total_skipped: int,
    total_failed: int,
    errors: list[str],
) -> None:
    """记录抓取日志。"""
    conn.execute(
        """INSERT INTO crawl_log (source, total_discovered, total_new, total_skipped, total_failed, errors, crawled_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            source,
            total_discovered,
            total_new,
            total_skipped,
            total_failed,
            "\n".join(errors),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()