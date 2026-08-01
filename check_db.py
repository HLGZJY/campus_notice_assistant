"""检查数据库内容。"""
import sqlite3

conn = sqlite3.connect("data/notices.db")
conn.row_factory = sqlite3.Row

total = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
print(f"总计: {total} 条通知\n")

print("前5条:")
rows = conn.execute("SELECT title, length(raw_content) as content_len, status FROM notices LIMIT 5").fetchall()
for r in rows:
    print(f"  {r['title'][:50]} | {r['content_len']}字 | {r['status']}")

print(f"\n状态分布:")
for r in conn.execute("SELECT status, COUNT(*) as cnt FROM notices GROUP BY status").fetchall():
    print(f"  {r['status']}: {r['cnt']}条")

print(f"\n抓取日志:")
for r in conn.execute("SELECT source, total_discovered, total_new, total_skipped, total_failed FROM crawl_log").fetchall():
    print(f"  {r['source'][:30]} | 发现{r['total_discovered']} | 新增{r['total_new']} | 跳过{r['total_skipped']} | 失败{r['total_failed']}")