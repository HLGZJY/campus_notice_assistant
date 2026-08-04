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

CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id INTEGER NOT NULL,          -- 关联通知
    action TEXT NOT NULL,                -- 待办内容，如"在 X 前完成报名"
    due_at TEXT,                         -- 截止时间（复用 notice.deadline）
    priority TEXT DEFAULT 'normal',      -- high/normal/low
    status TEXT DEFAULT 'pending',       -- pending/done/skipped
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (notice_id) REFERENCES notices(id)
);
CREATE INDEX IF NOT EXISTS idx_todos_notice ON todos(notice_id);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(due_at);
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


# ---------- todos（M3 待办） ----------


def insert_todo(
    conn: sqlite3.Connection,
    notice_id: int,
    action: str,
    due_at: Optional[str] = None,
    priority: str = "normal",
) -> int:
    """插入一条待办，返回新 id。"""
    cur = conn.execute(
        """INSERT INTO todos (notice_id, action, due_at, priority, status, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?)""",
        (notice_id, action, due_at, priority, datetime.now().isoformat()),
    )
    conn.commit()
    return cur.lastrowid


def get_todos(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    notice_id: Optional[int] = None,
) -> list[dict]:
    """查询待办，按截止时间升序（无截止的排在最后）。带通知标题。"""
    where: list[str] = []
    params: list = []
    if status:
        where.append("t.status = ?")
        params.append(status)
    if notice_id is not None:
        where.append("t.notice_id = ?")
        params.append(notice_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"""SELECT t.*, n.title AS notice_title, n.notice_type
            FROM todos t
            LEFT JOIN notices n ON n.id = t.notice_id
            {w}
            ORDER BY t.due_at IS NULL, t.due_at ASC, t.id ASC""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def set_todo_status(conn: sqlite3.Connection, todo_id: int, status: str) -> bool:
    """更新待办状态（pending/done/skipped）。done 时记录 completed_at。"""
    cur = conn.execute(
        """UPDATE todos SET status = ?,
               completed_at = CASE WHEN ? = 'done' THEN ? ELSE NULL END
           WHERE id = ?""",
        (status, status, datetime.now().isoformat(), todo_id),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_todos_for_notice(
    conn: sqlite3.Connection,
    notice_id: int,
    status: Optional[str] = None,
) -> int:
    """删除某通知的待办（按需重新生成前调用，防重复）。返回删除条数。"""
    if status:
        cur = conn.execute(
            "DELETE FROM todos WHERE notice_id = ? AND status = ?",
            (notice_id, status),
        )
    else:
        cur = conn.execute("DELETE FROM todos WHERE notice_id = ?", (notice_id,))
    conn.commit()
    return cur.rowcount


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


# ---------- 单链接分析 & 浏览辅助 ----------


def get_notice(conn: sqlite3.Connection, notice_id: int) -> Optional[dict]:
    """按 ID 获取完整通知记录。"""
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
    return dict(row) if row else None


def save_notice_analysis(
    conn: sqlite3.Connection,
    record: NoticeRecord,
    extraction: Optional[dict] = None,
    status: str = "raw",
) -> tuple[int, bool]:
    """Insert 或 Update 通知（按 URL 去重），同时写入结构化提取结果。

    Returns:
        (notice_id, is_new) — is_new=True 表示新插入，False 表示更新已有记录
    """
    # 先查是否存在
    existing = conn.execute("SELECT id FROM notices WHERE url = ?", (record.url,)).fetchone()
    if existing:
        notice_id = existing["id"]
        # 更新 raw_content/published_at（若为空则补全）
        conn.execute(
            """UPDATE notices SET
                   raw_content = COALESCE(?, raw_content),
                   published_at = COALESCE(?, published_at),
                   source = ?,
                   title = ?,
                   crawled_at = ?
               WHERE id = ?""",
            (
                record.raw_content,
                record.published_at,
                record.source,
                record.title,
                record.crawled_at,
                notice_id,
            ),
        )
        is_new = False
    else:
        cur = conn.execute(
            """INSERT INTO notices (url, source, title, raw_content, published_at, crawled_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                record.url,
                record.source,
                record.title,
                record.raw_content,
                record.published_at,
                record.crawled_at,
                status,
            ),
        )
        notice_id = cur.lastrowid
        is_new = True

    # 写入结构化提取结果
    if extraction:
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
    else:
        # 无提取结果时，仅更新 status（如 raw/failed）
        conn.execute(
            "UPDATE notices SET status = ?, extracted_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(), notice_id),
        )

    conn.commit()
    return notice_id, is_new


def search_notices(
    conn: sqlite3.Connection,
    keyword: Optional[str] = None,
    notice_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """带筛选的通知查询（用于浏览页）。"""
    where = []
    params = []
    if keyword:
        where.append("(title LIKE ? OR raw_content LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if notice_type:
        where.append("notice_type = ?")
        params.append(notice_type)
    if status:
        where.append("status = ?")
        params.append(status)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    rows = conn.execute(
        f"""SELECT * FROM notices {w} ORDER BY crawled_at DESC LIMIT ?""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_notice_stats(conn: sqlite3.Connection) -> dict:
    """获取通知统计：按类型、按状态计数。"""
    by_type = conn.execute(
        "SELECT notice_type, COUNT(*) AS n FROM notices WHERE notice_type IS NOT NULL GROUP BY notice_type ORDER BY n DESC"
    ).fetchall()
    by_status = conn.execute(
        "SELECT status, COUNT(*) AS n FROM notices GROUP BY status ORDER BY n DESC"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) AS n FROM notices").fetchone()["n"]
    return {
        "total": total,
        "by_type": {r["notice_type"]: r["n"] for r in by_type},
        "by_status": {r["status"]: r["n"] for r in by_status},
    }


def get_urgent_todos(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    """Get pending todos that are overdue or due within N days."""
    from datetime import datetime, timedelta

    cutoff = (datetime.now() + timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT t.*, n.title AS notice_title, n.notice_type
           FROM todos t
           LEFT JOIN notices n ON n.id = t.notice_id
           WHERE t.status = 'pending'
             AND t.due_at IS NOT NULL
             AND t.due_at <= ?
           ORDER BY t.due_at ASC""",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_crawl_logs(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """获取最近的抓取日志。"""
    rows = conn.execute(
        "SELECT * FROM crawl_log ORDER BY crawled_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- CRUD 操作 ----------


def delete_notice(conn: sqlite3.Connection, notice_id: int) -> bool:
    """删除单条通知（级联删除关联待办）。"""
    conn.execute("DELETE FROM todos WHERE notice_id = ?", (notice_id,))
    cur = conn.execute("DELETE FROM notices WHERE id = ?", (notice_id,))
    conn.commit()
    return cur.rowcount > 0


def update_notice_fields(conn: sqlite3.Connection, notice_id: int, fields: dict) -> bool:
    """更新通知的指定字段。"""
    allowed = {
        "title", "source", "summary", "status", "notice_type",
        "target_audience", "signup_method", "signup_url",
        "location", "location_type", "deadline", "deadline_raw",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [notice_id]
    cur = conn.execute(f"UPDATE notices SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return cur.rowcount > 0


def delete_notices_bulk(
    conn: sqlite3.Connection,
    source: Optional[str] = None,
    status: Optional[str] = None,
) -> int:
    """按来源或状态批量删除通知（级联删除关联待办）。返回删除条数。"""
    where = []
    params = []
    if source:
        where.append("source = ?")
        params.append(source)
    if status:
        where.append("status = ?")
        params.append(status)
    if not where:
        return 0
    w = " AND ".join(where)
    ids = [r["id"] for r in conn.execute(f"SELECT id FROM notices WHERE {w}", params).fetchall()]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM todos WHERE notice_id IN ({placeholders})", ids)
    cur = conn.execute(f"DELETE FROM notices WHERE id IN ({placeholders})", ids)
    conn.commit()
    return cur.rowcount


def update_todo(
    conn: sqlite3.Connection,
    todo_id: int,
    action: Optional[str] = None,
    due_at: Optional[str] = None,
    priority: Optional[str] = None,
) -> bool:
    """更新待办的内容、截止时间或优先级。"""
    updates = []
    params = []
    if action is not None:
        updates.append("action = ?")
        params.append(action)
    if due_at is not None:
        updates.append("due_at = ?")
        params.append(due_at)
    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)
    if not updates:
        return False
    params.append(todo_id)
    cur = conn.execute(f"UPDATE todos SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return cur.rowcount > 0


def delete_todo(conn: sqlite3.Connection, todo_id: int) -> bool:
    """删除单条待办。"""
    cur = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    conn.commit()
    return cur.rowcount > 0