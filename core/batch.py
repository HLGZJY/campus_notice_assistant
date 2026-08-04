"""批量提取逻辑（供 CLI 和 UI 复用）。"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Optional

from core.extractor import NoticeExtractor
from storage.db import count_notices_by_status, get_connection, get_notices_by_status, mark_failed, update_extraction

logger = logging.getLogger(__name__)


async def run_batch(
    conn: sqlite3.Connection,
    notices: list[dict],
    dry_run: bool = False,
    limit: int = 50,
) -> dict:
    """批量结构化提取。

    Args:
        conn: SQLite 连接
        notices: 待提取的通知列表（来自 get_notices_by_status）
        dry_run: 只跑不写库
        limit: 最多处理条数

    Returns:
        统计字典，包含明细
    """
    extractor = NoticeExtractor()
    counter = {"成功(extracted)": 0, "部分(partial)": 0, "失败(failed)": 0}
    samples: list[dict] = []

    for i, n in enumerate(notices[:limit], start=1):
        logger.info("[%d/%d] 提取: %s", i, len(notices[:limit]), n["title"])
        outcome = await extractor.extract_one(
            title=n["title"],
            content=n["raw_content"] or "",
            published_at=n["published_at"],
            crawled_at=n["crawled_at"],
        )
        key = {"extracted": "成功(extracted)", "partial": "部分(partial)", "failed": "失败(failed)"}[
            outcome.status
        ]
        counter[key] += 1
        samples.append(
            {
                "id": n["id"],
                "title": n["title"],
                "status": outcome.status,
                "notice_type": outcome.extraction.notice_type if outcome.extraction else None,
                "deadline": outcome.extraction.deadline if outcome.extraction else None,
                "error": outcome.error,
            }
        )

        if not dry_run:
            if outcome.status == "failed":
                mark_failed(conn, n["id"], outcome.error or "")
            elif outcome.extraction is not None:
                update_extraction(
                    conn,
                    n["id"],
                    outcome.extraction.model_dump(),
                    outcome.status,
                )

        if outcome.error:
            logger.warning("  注意: %s", outcome.error)

    return {"明细": samples, **counter}


def run_batch_sync(
    notices: list[dict],
    dry_run: bool = False,
    limit: int = 50,
) -> dict:
    """同步包装器（UI 调用用，避免在 Streamlit 里管理事件循环）。"""
    conn = get_connection()
    try:
        return asyncio.run(run_batch(conn, notices, dry_run=dry_run, limit=limit))
    finally:
        conn.close()