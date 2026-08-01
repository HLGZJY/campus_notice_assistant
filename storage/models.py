"""数据模型定义。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class NoticeItem:
    """从列表页提取的一条通知链接信息。"""

    url: str
    title: str
    list_source: str  # 来自哪个列表页
    published_at: Optional[str] = None  # 列表页提取的日期


@dataclass
class NoticeRecord:
    """存入 SQLite 的一条通知记录。"""

    url: str
    source: str  # 来源名称，如 "创新创业学院"
    title: str
    raw_content: str
    published_at: Optional[str] = None  # ISO 8601
    crawled_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "raw"  # raw / extracted / failed


@dataclass
class CrawlResult:
    """一次抓取的汇总结果。"""

    source: str
    total_discovered: int = 0
    total_new: int = 0
    total_skipped: int = 0  # 已存在的
    total_failed: int = 0
    errors: list[str] = field(default_factory=list)