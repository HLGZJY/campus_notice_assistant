"""SQLite 存储层。"""
import json
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

# M2 结构化提取新增列（对已存在的库做 ALTER 迁移）
_MIGRATIONS = [
    "ALTER TABLE notices ADD COLUMN notice_type TEXT",
    "ALTER TABLE notices ADD COLUMN target_audience TEXT",
    "ALTER TABLE notices ADD COLUMN signup_method TEXT",
    "ALTER TABLE notices ADD COLUMN signup_url TEXT",
    "ALTER TABLE notices ADD COLUMN location TEXT",
    "ALTER TABLE notices ADD COLUMN location_type TEXT",
    "ALTER TABLE notices ADD COLUMN deadline TEXT",
    "ALTER TABLE notices ADD COLUMN deadline_raw TEXT",
    "ALTER TABLE notices ADD COLUMN key_dates_json TEXT",
    "ALTER TABLE notices ADD COLUMN summary TEXT",
    "ALTER TABLE notices ADD COLUMN extracted_at TEXT",
]


def _migrate(conn: sqlite3.Connection) -> None:
    """对已存在的库补齐 M2 新增列（幂等）。"""
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(notices)").fetchall()
    }
    for stmt in _MIGRATIONS:
        col = stmt.split("ADD COLUMN ")[1].split(" ")[0]
        if col not in existing:
            conn.execute(stmt)
    conn.commit()


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """获取 SQLite 连接，自动建库建表 + 迁移。"""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def url_exists(conn: sqlite3.Connection, url: str) -> bool:
    """检查 URL 是否已存在（去重依据）。"""
    row = conn.execute("SELECT 1 FROM notices WHERE url = ?", (url,)).fetchone()
    return row is not None


def get_notice_by_url(conn: sqlite3.Connection, url: str) -> Optional[dict]:
    """按 URL 查询已有记录，返回 dict 或 None。"""
    row = conn.execute("SELECT published_at FROM notices WHERE url = ?", (url,)).fetchone()
    return dict(row) if row else None


def update_notice_date(conn: sqlite3.Connection, url: str, published_at: str) -> bool:
    """更新已有记录的 published_at 字段。"""
    conn.execute("UPDATE notices SET published_at = ? WHERE url = ?", (published_at, url))
    conn.commit()
    return True


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


def update_extraction(
    conn: sqlite3.Connection,
    notice_id: int,
    extraction: dict,
    status: str,
) -> None:
    """更新通知的结构化提取结果。extraction 为 NoticeExtraction 的 dict。"""
    key_dates = extraction.get("key_dates") or []
    conn.execute(
        """UPDATE notices SET
               notice_type = ?,
               target_audience = ?,
               signup_method = ?,
               signup_url = ?,
               location = ?,
               location_type = ?,
               deadline = ?,
               deadline_raw = ?,
               key_dates_json = ?,
               summary = ?,
               status = ?,
               extracted_at = ?
           WHERE id = ?""",
        (
            extraction.get("notice_type"),
            extraction.get("target_audience"),
            extraction.get("signup_method"),
            extraction.get("signup_url"),
            extraction.get("location"),
            extraction.get("location_type"),
            extraction.get("deadline"),
            extraction.get("deadline_raw"),
            json.dumps(key_dates, ensure_ascii=False) if key_dates else None,
            extraction.get("summary"),
            status,
            datetime.now().isoformat(),
            notice_id,
        ),
    )
    conn.commit()


def mark_failed(conn: sqlite3.Connection, notice_id: int, error: str) -> None:
    """把通知标记为提取失败。"""
    conn.execute(
        "UPDATE notices SET status = 'failed', extracted_at = ? WHERE id = ?",
        (datetime.now().isoformat(), notice_id),
    )
    conn.commit()


def count_notices_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    """按状态统计通知数量。"""
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM notices GROUP BY status"
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


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