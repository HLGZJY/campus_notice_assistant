"""网页爬虫：列表页遍历 + 详情页提取。"""
import logging
from typing import Optional

import newspaper

try:
    from ..storage.db import get_connection, insert_notice, log_crawl, url_exists
    from ..storage.models import CrawlResult, NoticeItem, NoticeRecord
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from storage.db import get_connection, insert_notice, log_crawl, url_exists
    from storage.models import CrawlResult, NoticeItem, NoticeRecord

from .base import ListPageConfig, ListPageParser, PageFetcher

logger = logging.getLogger(__name__)


class WebCrawler:
    """网页爬虫：抓取列表页所有通知，存入 SQLite。

    工作流程：
    1. 抓取列表页第一页
    2. 自动发现通知链接 + 翻页链接
    3. 遍历所有翻页，收集全部通知链接
    4. 对每个通知链接，用 newspaper4k 提取详情
    5. 存入 SQLite（URL 去重）
    """

    def __init__(self, config: ListPageConfig):
        self.config = config
        self.fetcher = PageFetcher()

    def crawl(self) -> CrawlResult:
        """执行完整抓取流程。"""
        result = CrawlResult(source=self.config.source_name or self.config.list_url)
        all_notices: dict[str, NoticeItem] = {}  # url -> NoticeItem（去重）

        # 1. 抓取第一页，发现通知链接和翻页
        try:
            html = self.fetcher.fetch(self.config.list_url)
        except Exception as e:
            result.errors.append(f"列表页抓取失败: {type(e).__name__}: {e}")
            return result

        parser = ListPageParser(html, self.config.list_url)

        # 发现第一页的通知链接
        notices = parser.discover_notice_links(self.config.url_pattern)
        for n in notices:
            all_notices[n.url] = n
        result.total_discovered = len(all_notices)

        # 2. 发现并遍历翻页
        pagination = parser.discover_pagination()
        pages_to_crawl = pagination.page_urls[: self.config.max_pages - 1]

        for page_url in pages_to_crawl:
            try:
                page_html = self.fetcher.fetch(page_url)
                page_parser = ListPageParser(page_html, page_url)
                page_notices = page_parser.discover_notice_links(
                    self.config.url_pattern
                )
                for n in page_notices:
                    if n.url not in all_notices:
                        all_notices[n.url] = n
            except Exception as e:
                result.errors.append(f"翻页抓取失败 {page_url}: {e}")

        result.total_discovered = len(all_notices)
        logger.info(
            f"[{result.source}] 共发现 {result.total_discovered} 条通知，"
            f"来自 {len(pages_to_crawl) + 1} 页"
        )

        # 3. 抓取详情页，存入 SQLite
        conn = get_connection()
        try:
            for url, item in all_notices.items():
                if url_exists(conn, url):
                    result.total_skipped += 1
                    continue

                try:
                    record = self._fetch_detail(url, item.title, item.published_at)
                    if record:
                        insert_notice(conn, record)
                        result.total_new += 1
                    else:
                        result.total_failed += 1
                except Exception as e:
                    result.total_failed += 1
                    result.errors.append(f"详情页失败 {url}: {e}")
                    logger.warning(f"详情页失败 {url}: {e}")
        finally:
            log_crawl(
                conn,
                result.source,
                result.total_discovered,
                result.total_new,
                result.total_skipped,
                result.total_failed,
                result.errors,
            )
            conn.close()

        return result

    def _fetch_detail(
        self, url: str, fallback_title: str, list_page_date: Optional[str] = None
    ) -> Optional[NoticeRecord]:
        """用 newspaper4k 抓取详情页，返回 NoticeRecord。

        Args:
            url: 详情页 URL
            fallback_title: 列表页提取的标题（newspaper4k 失败时使用）
            list_page_date: 列表页提取的日期（newspaper4k 失败时使用）
        """
        try:
            article = newspaper.article(url, language="zh")
            title = article.title or fallback_title
            content = article.text or ""

            if not content:
                # newspaper4k 提取失败，用 fallback
                content = self._fallback_extract(url)

            # newspaper4k 日期优先，列表页日期作为 fallback
            published_at = None
            if article.publish_date:
                published_at = article.publish_date.isoformat()
            elif list_page_date:
                published_at = list_page_date

            return NoticeRecord(
                url=url,
                source=self.config.source_name,
                title=title,
                raw_content=content,
                published_at=published_at,
            )
        except Exception as e:
            logger.warning(f"newspaper4k 提取失败 {url}: {e}")
            # fallback：用 BeautifulSoup 提取
            try:
                html = self.fetcher.fetch(url)
                content = self._fallback_extract_from_html(html)
                return NoticeRecord(
                    url=url,
                    source=self.config.source_name,
                    title=fallback_title,
                    raw_content=content,
                    published_at=list_page_date,
                )
            except Exception:
                return None

    def _fallback_extract(self, url: str) -> str:
        """newspaper4k 失败时的 fallback 提取。"""
        html = self.fetcher.fetch(url)
        return self._fallback_extract_from_html(html)

    def _fallback_extract_from_html(self, html: str) -> str:
        """从 HTML 提取纯文本（fallback）。"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # 移除不需要的标签
        for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)