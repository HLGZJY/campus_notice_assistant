"""校园通知助手 v0.2 - M1+ 阶段成果

交互式菜单界面，支持抓取、预览、导出通知。

用法：
    python main.py
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from crawler.base import ListPageConfig
from crawler.web_crawler import WebCrawler
from storage.db import get_connection
import yaml

CONFIG_PATH = Path(__file__).parent / "config" / "scuec.yaml"
EXPORT_DIR = Path(__file__).parent / "exports"

BANNER = """
====================================
    校园通知助手 v0.2 (M1+)
====================================
"""

MENU = """
1. 抓取所有数据源
2. 查看通知列表
3. 查看统计信息
4. 手动抓取指定URL（预览模式）
5. 导出通知
0. 退出
"""


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ==================== 抓取功能 ====================

def do_crawl():
    config = load_config()
    sources = [s for s in config.get("sources", []) if s.get("enabled", True)]
    if not sources:
        print("\n没有启用的数据源")
        return

    print(f"\n共有 {len(sources)} 个数据源，开始抓取...\n")

    total_new = 0
    total_failed = 0
    for src in sources:
        name = src.get("name", src["list_url"])
        cfg = ListPageConfig(
            list_url=src["list_url"],
            source_name=name,
            url_pattern=src.get("url_pattern"),
            max_pages=src.get("max_pages", 20),
            timeout=config.get("crawl", {}).get("timeout", 15),
            delay=config.get("crawl", {}).get("delay", 1),
        )
        print(f"  > {name} ...", end=" ", flush=True)
        result = WebCrawler(cfg).crawl()
        parts = []
        if result.total_new:
            parts.append(f"新增 {result.total_new}")
        if result.total_updated:
            parts.append(f"更新 {result.total_updated}")
        if result.total_skipped:
            parts.append(f"跳过 {result.total_skipped}")
        if result.total_failed:
            parts.append(f"失败 {result.total_failed}")
        print("，".join(parts) if parts else "无变化")
        total_new += result.total_new
        total_failed += result.total_failed

    print(f"\n抓取完成！共新增 {total_new} 条，失败 {total_failed} 条")


# ==================== 列表功能 ====================

def do_list():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT source, COUNT(*) as cnt FROM notices GROUP BY source ORDER BY cnt DESC"
    )
    groups = cursor.fetchall()

    if not groups:
        print("\n数据库为空，请先抓取通知（选项1）")
        conn.close()
        return

    for source, cnt in groups:
        print(f"\n--- {source} ({cnt} 条) ---")
        cursor.execute(
            "SELECT title, published_at, url FROM notices WHERE source = ? ORDER BY rowid DESC LIMIT 10",
            (source,),
        )
        for i, (title, pub, url) in enumerate(cursor.fetchall(), 1):
            date = pub or "未知日期"
            print(f"  {i}. [{date}] {title[:40]}")
        if cnt > 10:
            print(f"  ... 还有 {cnt - 10} 条")

    conn.close()


# ==================== 统计功能 ====================

def do_stats():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM notices")
    total = cursor.fetchone()[0]

    cursor.execute(
        "SELECT source, COUNT(*) FROM notices GROUP BY source ORDER BY COUNT(*) DESC"
    )
    by_source = cursor.fetchall()

    cursor.execute(
        "SELECT SUM(CASE WHEN published_at IS NOT NULL THEN 1 ELSE 0 END), COUNT(*) FROM notices"
    )
    date_stats = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM crawl_log")
    log_count = cursor.fetchone()[0]

    print(f"\n统计信息:")
    print(f"  通知总数: {total}")
    print(f"  日期覆盖率: {date_stats[0]}/{date_stats[1]}")
    print(f"  抓取次数: {log_count}")
    if by_source:
        print(f"  各来源数量:")
        for src, cnt in by_source:
            print(f"    - {src}: {cnt}")

    db_path = Path(__file__).parent / "data" / "notices.db"
    if db_path.exists():
        size_kb = db_path.stat().st_size / 1024
        print(f"  数据库大小: {size_kb:.1f} KB")

    conn.close()


# ==================== 手动抓取 + 预览 ====================

def do_manual_crawl():
    print("\n--- 手动抓取（预览模式）---\n")

    url = input("请输入列表页 URL: ").strip()
    if not url:
        print("URL 不能为空")
        return

    source_name = input("来源名称（可选，回车跳过）: ").strip() or url
    max_pages_str = input("最大翻页数（默认 5）: ").strip()
    max_pages = int(max_pages_str) if max_pages_str.isdigit() else 5

    config = load_config()
    cfg = ListPageConfig(
        list_url=url,
        source_name=source_name,
        max_pages=max_pages,
        timeout=config.get("crawl", {}).get("timeout", 15),
        delay=config.get("crawl", {}).get("delay", 1),
    )

    print(f"\n正在抓取: {url} ...")
    crawler = WebCrawler(cfg)
    result = crawler.crawl()

    if result.total_new == 0 and result.total_failed == 0:
        print("没有抓取到新内容")
        return

    # 预览模式：展示抓取结果
    print(f"\n{'='*60}")
    print(f"抓取结果: 发现 {result.total_discovered} 条，新增 {result.total_new} 条")
    print(f"{'='*60}\n")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, title, published_at, raw_content FROM notices WHERE source = ? ORDER BY rowid DESC LIMIT ?",
        (source_name, result.total_new),
    )
    previews = cursor.fetchall()

    for i, (id_, title, pub, content) in enumerate(previews, 1):
        date = pub or "未知日期"
        preview = (content[:80] + "...") if content and len(content) > 80 else content
        print(f"  {i}. [{date}] {title[:45]}")
        if preview:
            print(f"     {preview[:80]}")
        print()

    conn.close()

    # 确认是否保留
    choice = input("是否保留这些抓取结果？(y/n): ").strip().lower()
    if choice != "y":
        # 删除刚抓取的数据
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM notices WHERE source = ?", (source_name,))
        conn.commit()
        conn.close()
        print("已删除抓取结果")
    else:
        print("已保留抓取结果")


# ==================== 导出功能 ====================

def do_export():
    print("\n--- 导出通知 ---\n")

    conn = get_connection()
    cursor = conn.cursor()

    # 选择数据源
    cursor.execute("SELECT DISTINCT source FROM notices ORDER BY source")
    sources = [row[0] for row in cursor.fetchall()]

    if not sources:
        print("数据库为空，请先抓取通知")
        conn.close()
        return

    print("可用数据源:")
    for i, src in enumerate(sources, 1):
        cursor.execute("SELECT COUNT(*) FROM notices WHERE source = ?", (src,))
        cnt = cursor.fetchone()[0]
        print(f"  {i}. {src} ({cnt} 条)")
    print(f"  0. 全部")

    choice = input("\n选择数据源（输入编号）: ").strip()
    if choice == "0" or choice == "":
        source_filter = None
    elif choice.isdigit() and 1 <= int(choice) <= len(sources):
        source_filter = sources[int(choice) - 1]
    else:
        print("无效选择")
        conn.close()
        return

    # 查询数据
    if source_filter:
        cursor.execute(
            "SELECT title, source, published_at, raw_content, url FROM notices WHERE source = ? ORDER BY published_at DESC",
            (source_filter,),
        )
    else:
        cursor.execute(
            "SELECT title, source, published_at, raw_content, url FROM notices ORDER BY published_at DESC"
        )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("没有可导出的数据")
        return

    print(f"\n共 {len(rows)} 条数据")

    # 选择导出格式
    print("\n导出格式:")
    print("  1. CSV（Excel 打开）")
    print("  2. JSON（开发者用）")
    print("  3. Markdown（文档分享）")

    fmt = input("\n选择格式（1/2/3）: ").strip()

    # 准备导出目录
    EXPORT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == "1":
        _export_csv(rows, timestamp)
    elif fmt == "2":
        _export_json(rows, timestamp)
    elif fmt == "3":
        _export_markdown(rows, timestamp)
    else:
        print("无效选择")


def _export_csv(rows, timestamp):
    filename = EXPORT_DIR / f"notices_{timestamp}.csv"
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["标题", "来源", "发布日期", "内容", "链接"])
        for title, source, pub, content, url in rows:
            writer.writerow([title, source, pub or "", content or "", url])
    print(f"\n已导出: {filename}")
    print(f"共 {len(rows)} 条数据")


def _export_json(rows, timestamp):
    filename = EXPORT_DIR / f"notices_{timestamp}.json"
    data = []
    for title, source, pub, content, url in rows:
        data.append({
            "title": title,
            "source": source,
            "published_at": pub,
            "content": content,
            "url": url,
        })
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n已导出: {filename}")
    print(f"共 {len(rows)} 条数据")


def _export_markdown(rows, timestamp):
    filename = EXPORT_DIR / f"notices_{timestamp}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 校园通知导出\n\n")
        f.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"共 {len(rows)} 条通知\n\n")
        f.write("---\n\n")

        # 按来源分组
        by_source = {}
        for title, source, pub, content, url in rows:
            by_source.setdefault(source, []).append((title, pub, content, url))

        for source, items in by_source.items():
            f.write(f"## {source}\n\n")
            for title, pub, content, url in items:
                date = pub or "未知日期"
                f.write(f"### [{date}] {title}\n\n")
                if content:
                    f.write(f"{content[:500]}\n\n")
                f.write(f"[原文链接]({url})\n\n")
                f.write("---\n\n")

    print(f"\n已导出: {filename}")
    print(f"共 {len(rows)} 条数据")


# ==================== 主程序 ====================

def main():
    print(BANNER)

    actions = {
        "1": do_crawl,
        "2": do_list,
        "3": do_stats,
        "4": do_manual_crawl,
        "5": do_export,
    }

    while True:
        print(MENU)
        choice = input("请选择: ").strip()

        if choice == "0":
            print("再见！")
            break
        elif choice in actions:
            actions[choice]()
        else:
            print("无效选择，请输入 0-5")


if __name__ == "__main__":
    main()
