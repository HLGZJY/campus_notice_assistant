"""校园通知助手 v0.1 - M1 阶段成果

交互式菜单界面，支持抓取通知、查看列表、统计信息。

用法：
    python main.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from crawler.base import ListPageConfig
from crawler.web_crawler import WebCrawler
from storage.db import get_connection
import yaml

CONFIG_PATH = Path(__file__).parent / "config" / "scuec.yaml"

BANNER = """
====================================
    校园通知助手 v0.1 (M1)
====================================
 数据源: 创新创业学院 / 教务处管理文件
"""

MENU = """
1. 抓取通知
2. 查看通知列表
3. 查看统计信息
0. 退出
"""


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def do_crawl():
    config = load_config()
    sources = config.get("sources", [])
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
        )
        print(f"  > {name} ...", end=" ", flush=True)
        result = WebCrawler(cfg).crawl()
        print(f"新增 {result.total_new}，跳过 {result.total_skipped}，失败 {result.total_failed}")
        total_new += result.total_new
        total_failed += result.total_failed

    print(f"\n抓取完成！共新增 {total_new} 条，失败 {total_failed} 条")


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
            print(f"  {i}. [{date}] {title[:35]}")
        if cnt > 10:
            print(f"  ... 还有 {cnt - 10} 条")

    conn.close()


def do_stats():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM notices")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT source, COUNT(*) FROM notices GROUP BY source ORDER BY COUNT(*) DESC")
    by_source = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM crawl_log")
    log_count = cursor.fetchone()[0]

    print(f"\n统计信息:")
    print(f"  通知总数: {total}")
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


def main():
    print(BANNER)

    actions = {
        "1": do_crawl,
        "2": do_list,
        "3": do_stats,
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
            print("无效选择，请输入 0-3")


if __name__ == "__main__":
    main()
