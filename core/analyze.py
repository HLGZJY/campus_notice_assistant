"""单链接分析管道：URL -> 抓取正文 -> LLM 结构化提取 -> 入库。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from core.extractor import NoticeExtractor
from core.models import NoticeExtraction
from crawler.web_crawler import fetch_notice_detail
from storage.db import get_connection, get_notice, save_notice_analysis

logger = logging.getLogger(__name__)


@dataclass
class AnalyzeOutcome:
    """单链接分析的结果。"""

    status: str  # "ok" / "cached" / "failed"
    notice_id: Optional[int]
    extraction: Optional[NoticeExtraction]
    is_new: bool
    error: Optional[str] = None


def analyze_notice_url(
    url: str,
    source_name: str = "手动分析",
    force: bool = False,
) -> AnalyzeOutcome:
    """抓取单条通知链接 -> LLM 结构化提取 -> 入库。

    Args:
        url: 通知详情页 URL
        source_name: 来源名称（存入 DB，默认"手动分析"）
        force: 是否强制重新提取（忽略缓存）

    Returns:
        AnalyzeOutcome
    """
    conn = get_connection()
    try:
        # 1. 查库：URL 已存在且有提取结果 -> 直接返回缓存
        existing = conn.execute("SELECT id, status FROM notices WHERE url = ?", (url,)).fetchone()
        if existing and not force:
            notice_id = existing["id"]
            if existing["status"] in ("extracted", "partial"):
                # 已有结构化结果，直接读取
                notice = get_notice(conn, notice_id)
                extraction = _load_extraction_from_row(notice)
                return AnalyzeOutcome(
                    status="cached",
                    notice_id=notice_id,
                    extraction=extraction,
                    is_new=False,
                    error=None,
                )

        # 2. 抓取正文
        record = fetch_notice_detail(url, source_name)
        if record is None:
            return AnalyzeOutcome(
                status="failed",
                notice_id=None,
                extraction=None,
                is_new=False,
                error="抓取正文失败",
            )

        # 3. LLM 结构化提取
        extractor = NoticeExtractor()
        try:
            outcome = asyncio.run(
                extractor.extract_one(
                    title=record.title,
                    content=record.raw_content or "",
                    published_at=record.published_at,
                    crawled_at=record.crawled_at,
                )
            )
        except Exception as e:
            logger.warning("LLM 提取异常: %s", e)
            # 入库 raw 状态
            save_notice_analysis(conn, record, extraction=None, status="failed")
            return AnalyzeOutcome(
                status="failed",
                notice_id=None,
                extraction=None,
                is_new=False,
                error=f"LLM 提取失败: {e}",
            )

        # 4. 确定状态
        if outcome.status == "failed":
            status = "failed"
            extraction = outcome.extraction
        elif outcome.status == "extracted":
            status = "extracted"
            extraction = outcome.extraction
        else:  # partial
            status = "partial"
            extraction = outcome.extraction

        # 5. 入库（insert 或 update）
        extraction_dict = extraction.model_dump() if extraction else None
        notice_id, is_new = save_notice_analysis(conn, record, extraction_dict, status)

        return AnalyzeOutcome(
            status="ok",
            notice_id=notice_id,
            extraction=extraction,
            is_new=is_new,
            error=outcome.error,
        )
    finally:
        conn.close()


def _load_extraction_from_row(row: dict) -> Optional[NoticeExtraction]:
    """从 DB 行恢复 NoticeExtraction 对象。"""
    if not row or not row.get("notice_type"):
        return None
    import json

    key_dates = []
    if row.get("key_dates_json"):
        try:
            key_dates = json.loads(row["key_dates_json"])
        except json.JSONDecodeError:
            pass

    from core.models import KeyDate

    return NoticeExtraction(
        notice_type=row["notice_type"],
        title=row["title"],
        target_audience=row["target_audience"],
        signup_method=row["signup_method"],
        signup_url=row["signup_url"],
        location=row["location"],
        location_type=row["location_type"],
        deadline_raw=row["deadline_raw"],
        deadline=row["deadline"],
        key_dates=[KeyDate(**kd) for kd in key_dates],
        summary=row["summary"],
    )