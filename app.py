"""校园通知助手 - 统一 Streamlit 应用（M1+M2+M3 整合）。

运行：
    streamlit run app.py

功能模块：
- 📥 单链接分析：粘贴通知详情链接 → 自动抓取正文 → LLM 结构化提取 → 结构化卡片展示 → 一键生成待办
- 📋 通知浏览：查看所有已抓取通知，支持类型/状态/关键词筛选，点开详情卡片
- ✅ 待办清单：按截止时间排序，过期/即将到期高亮，完成/跳过管理
- 🔄 数据管理：手动刷新抓取配置源、批量提取待处理通知、查看抓取日志
- 📤 导出：CSV / JSON / Markdown 导出通知数据
"""
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# 确保能导入项目模块
sys.path.insert(0, str(Path(__file__).parent))

from core.analyze import analyze_notice_url
from core.batch import run_batch_sync
from core.models import ACTION_NOTICE_TYPES, NoticeExtraction
from core.todo import generate_todos_for_notice
from crawler.web_crawler import WebCrawler
from crawler.base import ListPageConfig
from storage.db import (
    count_notices_by_status,
    get_connection,
    get_crawl_logs,
    get_notice,
    get_notice_stats,
    get_notices_by_status,
    search_notices,
)
import yaml

st.set_page_config(page_title="校园通知助手", layout="wide", initial_sidebar_state="expanded")

# ---------- 样式 ----------
st.markdown(
    """
<style>
.notice-card {
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
    background: #fafafa;
}
.notice-card h3 { margin-top: 0; margin-bottom: 8px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
.badge-competition { background: #e3f2fd; color: #1565c0; }
.badge-lecture { background: #f3e5f5; color: #7b1fa2; }
.badge-registration { background: #e8f5e9; color: #2e7d32; }
.badge-scholarship { background: #fff8e1; color: #f57f17; }
.badge-administrative { background: #fce4ec; color: #c2185b; }
.badge-recruitment { background: #e0f2f1; color: #00695c; }
.badge-policy { background: #eeeeee; color: #424242; }
.badge-result { background: #f1f8e9; color: #33691e; }
.badge-news { background: #e8eaf6; color: #283593; }
.badge-other { background: #eceff1; color: #546e7a; }
.field-row { display: flex; gap: 16px; margin-bottom: 8px; }
.field-label { font-weight: 600; color: #555; min-width: 80px; }
.field-value { color: #333; }
.deadline-soon { color: #d32f2f; font-weight: 600; }
.deadline-expired { color: #9e9e9e; text-decoration: line-through; }
.todo-item { padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; border-left: 4px solid #1976d2; background: #f5f5f5; }
.todo-item.high { border-left-color: #d32f2f; }
.todo-item.pending { background: #fff3e0; }
.todo-item.done { background: #e8f5e9; border-left-color: #2e7d32; opacity: 0.7; }
.todo-item.skipped { background: #eceff1; border-left-color: #78909c; opacity: 0.7; }
.expander-header { cursor: pointer; }
</style>
""",
    unsafe_allow_html=True,
)

# ---------- 工具函数 ----------


def load_config():
    with open("config/scuec.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def badge_html(notice_type: str) -> str:
    return f'<span class="badge badge-{notice_type}">{notice_type}</span>'


def render_notice_card(notice: dict, show_actions: bool = True, key_prefix: str = ""):
    """渲染结构化通知卡片。"""
    extraction_fields = {
        "notice_type": notice.get("notice_type"),
        "deadline": notice.get("deadline"),
        "deadline_raw": notice.get("deadline_raw"),
        "target_audience": notice.get("target_audience"),
        "signup_method": notice.get("signup_method"),
        "signup_url": notice.get("signup_url"),
        "location": notice.get("location"),
        "location_type": notice.get("location_type"),
        "key_dates_json": notice.get("key_dates_json"),
        "summary": notice.get("summary"),
    }

    has_extraction = extraction_fields["notice_type"] is not None

    with st.container(border=True):
        # 标题行
        col_title, col_type = st.columns([5, 1])
        with col_title:
            st.markdown(f"### #{notice['id']} {notice['title']}")
        with col_type:
            if has_extraction:
                st.markdown(badge_html(extraction_fields["notice_type"]), unsafe_allow_html=True)

        # 元信息行
        meta_cols = st.columns(3)
        with meta_cols[0]:
            st.caption(f"来源: {notice['source']}")
        with meta_cols[1]:
            pub = notice.get("published_at") or "未知"
            st.caption(f"发布: {pub[:10] if pub != '未知' else pub}")
        with meta_cols[2]:
            st.caption(f"状态: {notice['status']}")

        if has_extraction:
            st.divider()
            # 结构化字段展示
            rows = []

            # 截止时间
            deadline = extraction_fields["deadline"]
            deadline_raw = extraction_fields["deadline_raw"]
            if deadline:
                deadline_display = deadline[:16].replace("T", " ")
                try:
                    deadline_date = datetime.fromisoformat(deadline).date()
                    today = datetime.now().date()
                    if deadline_date < today:
                        deadline_cls = "deadline-expired"
                        deadline_display += " （已过期）"
                    elif (deadline_date - today).days <= 7:
                        deadline_cls = "deadline-soon"
                        deadline_display += f" （{(deadline_date - today).days} 天后截止）"
                    else:
                        deadline_cls = ""
                except ValueError:
                    deadline_cls = ""
                rows.append(
                    f'<div class="field-row"><span class="field-label">截止时间</span>'
                    f'<span class="field-value {deadline_cls}">{deadline_display}</span></div>'
                )
                if deadline_raw and deadline_raw != deadline:
                    rows.append(
                        f'<div class="field-row"><span class="field-label">原文片段</span>'
                        f'<span class="field-value">{deadline_raw}</span></div>'
                    )

            # 面向对象
            if extraction_fields["target_audience"]:
                rows.append(
                    f'<div class="field-row"><span class="field-label">面向对象</span>'
                    f'<span class="field-value">{extraction_fields["target_audience"]}</span></div>'
                )

            # 报名方式
            if extraction_fields["signup_method"]:
                rows.append(
                    f'<div class="field-row"><span class="field-label">报名方式</span>'
                    f'<span class="field-value">{extraction_fields["signup_method"]}</span></div>'
                )
            if extraction_fields["signup_url"]:
                rows.append(
                    f'<div class="field-row"><span class="field-label">报名链接</span>'
                    f'<span class="field-value"><a href="{extraction_fields["signup_url"]}" target="_blank">{extraction_fields["signup_url"]}</a></span></div>'
                )

            # 地点
            if extraction_fields["location"]:
                loc_type = extraction_fields["location_type"] or ""
                rows.append(
                    f'<div class="field-row"><span class="field-label">地点</span>'
                    f'<span class="field-value">{extraction_fields["location"]} {f"({loc_type})" if loc_type else ""}</span></div>'
                )

            # 关键时间点
            if extraction_fields["key_dates_json"]:
                import json

                try:
                    key_dates = json.loads(extraction_fields["key_dates_json"])
                    if key_dates:
                        kd_html = "、".join(
                            [f"{kd['label']}: {kd['date_raw']}" for kd in key_dates if kd.get("date_raw")]
                        )
                        rows.append(
                            f'<div class="field-row"><span class="field-label">关键时间</span>'
                            f'<span class="field-value">{kd_html}</span></div>'
                        )
                except json.JSONDecodeError:
                    pass

            # 摘要
            if extraction_fields["summary"]:
                rows.append(
                    f'<div class="field-row"><span class="field-label">摘要</span>'
                    f'<span class="field-value">{extraction_fields["summary"]}</span></div>'
                )

            if rows:
                st.markdown("".join(rows), unsafe_allow_html=True)

        # 原文折叠
        with st.expander("📄 查看原文", expanded=False):
            st.text_area(
                "原文内容",
                value=notice.get("raw_content") or "（无内容）",
                height=200,
                disabled=True,
                label_visibility="collapsed",
                key=f"{key_prefix}_raw_{notice['id']}",
            )

        # 动作按钮
        if show_actions and has_extraction:
            st.divider()
            btn_cols = st.columns([1, 1, 3])
            # 生成待办
            if extraction_fields["notice_type"] in ACTION_NOTICE_TYPES:
                if btn_cols[0].button("➕ 生成待办", key=f"{key_prefix}_gen_{notice['id']}", use_container_width=True):
                    with st.spinner("生成待办中..."):
                        outcome = generate_todos_for_notice(notice["id"])
                    if outcome.status == "generated":
                        st.success(f"已生成 {len(outcome.items)} 条待办")
                        for it in outcome.items:
                            st.write(f"- {it.action}")
                        st.rerun()
                    else:
                        st.info(outcome.error or "无需生成待办")
            else:
                btn_cols[0].write("⚪ 非行动型通知，无待办")

            # 原文链接
            if btn_cols[1].button("🔗 打开原文", key=f"{key_prefix}_open_{notice['id']}", use_container_width=True):
                st.markdown(f"[在新标签页打开]({notice['url']})")

            # 强制重新提取
            if btn_cols[2].button("🔄 重新提取", key=f"{key_prefix}_reextract_{notice['id']}", use_container_width=True):
                with st.spinner("重新提取中..."):
                    result = analyze_notice_url(notice["url"], source_name=notice["source"], force=True)
                if result.status in ("ok", "cached"):
                    st.success("重新提取完成")
                    st.rerun()
                else:
                    st.error(f"重新提取失败: {result.error}")


# ---------- 页面：单链接分析 ----------


def page_single_analysis():
    st.header("📥 单链接分析")
    st.caption("粘贴校园通知详情页链接，自动抓取正文并进行结构化提取")

    col_url, col_btn = st.columns([4, 1])
    with col_url:
        url = st.text_input(
            "通知详情页 URL",
            placeholder="https://www.scuec.edu.cn/.../xxx.htm",
            label_visibility="collapsed",
        )
    with col_btn:
        force = st.checkbox("强制重新提取", value=False)

    if st.button("🔍 提取并结构化", type="primary", disabled=not url, use_container_width=True):
        with st.spinner("正在抓取与提取..."):
            result = analyze_notice_url(url, force=force)

        if result.status == "failed":
            st.error(f"❌ 失败: {result.error}")
        elif result.status == "cached":
            st.info("📋 已有缓存结果（未重新提取），如需重新分析请勾选“强制重新提取”")
            notice = get_notice(get_connection(), result.notice_id)
            render_notice_card(notice, key_prefix="single")
        else:  # ok
            st.success("✅ 提取完成")
            notice = get_notice(get_connection(), result.notice_id)
            render_notice_card(notice, key_prefix="single")


# ---------- 页面：通知浏览 ----------


def page_browse():
    st.header("📋 通知浏览")

    # 统计概览
    stats = get_notice_stats(get_connection())
    stat_cols = st.columns(4)
    stat_cols[0].metric("总计", stats["total"])
    stat_cols[1].metric("已提取", stats["by_status"].get("extracted", 0))
    stat_cols[2].metric("部分提取", stats["by_status"].get("partial", 0))
    stat_cols[3].metric("原始/失败", stats["by_status"].get("raw", 0) + stats["by_status"].get("failed", 0))

    # 筛选器
    with st.expander("🔍 筛选条件", expanded=True):
        filter_cols = st.columns(4)
        keyword = filter_cols[0].text_input("关键词搜索", placeholder="标题/内容关键词")
        notice_type = filter_cols[1].selectbox(
            "通知类型",
            ["全部"] + list(ACTION_NOTICE_TYPES) + ["policy", "result", "news", "other"],
        )
        status = filter_cols[2].selectbox(
            "提取状态",
            ["全部", "extracted", "partial", "raw", "failed"],
        )
        limit = filter_cols[3].number_input("显示条数", 10, 500, 50, step=10)

    notices = search_notices(
        get_connection(),
        keyword=keyword or None,
        notice_type=notice_type if notice_type != "全部" else None,
        status=status if status != "全部" else None,
        limit=limit,
    )

    if not notices:
        st.info("没有符合条件的通知")
        return

    st.write(f"共找到 {len(notices)} 条通知")

    for n in notices:
        render_notice_card(n, key_prefix="browse")


# ---------- 页面：待办清单 ----------


def page_todos():
    st.header("✅ 待办清单")

    status_filter = st.radio("状态", ["全部", "pending", "done", "skipped"], horizontal=True, index=0)
    todos = get_todos(
        get_connection(),
        status=status_filter if status_filter != "全部" else None,
    )

    if not todos:
        st.info("暂无待办")
        return

    today = datetime.now().date()
    for t in todos:
        expired = t["due_at"] and t["due_at"][:10] < today.isoformat() and t["status"] == "pending"
        due_soon = t["due_at"] and not expired and (datetime.fromisoformat(t["due_at"]).date() - today).days <= 7
        priority_cls = "high" if t["priority"] == "high" else ""
        status_cls = t["status"]
        if expired:
            status_cls = "pending"

        with st.container():
            cols = st.columns([6, 1, 1, 1])
            due_display = (t["due_at"] or "-")[:16].replace("T", " ")
            badge = ""
            if expired:
                badge = " 🟥 **已过期**"
            elif due_soon:
                badge = " 🟨 **即将截止**"
            cols[0].markdown(
                f'<div class="todo-item {priority_cls} {status_cls}">'
                f"<strong>{t['action']}</strong><br>"
                f"<small>截止: {due_display}{badge} · 优先级: {t['priority']} · 来源: #{t.get('notice_id', '?')}</small>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if t["status"] == "pending":
                if cols[1].button("✅ 完成", key=f"done_{t['id']}", use_container_width=True):
                    set_todo_status(get_connection(), t["id"], "done")
                    st.rerun()
                if cols[2].button("⏭️ 跳过", key=f"skip_{t['id']}", use_container_width=True):
                    set_todo_status(get_connection(), t["id"], "skipped")
                    st.rerun()
            else:
                cols[1].markdown(f"`{t['status']}`")
                if cols[2].button("🔄 恢复", key=f"reopen_{t['id']}", use_container_width=True):
                    set_todo_status(get_connection(), t["id"], "pending")
                    st.rerun()


def get_todos(conn, status=None):
    from storage.db import get_todos as _get_todos

    return _get_todos(conn, status=status)


def set_todo_status(conn, todo_id, status):
    from storage.db import set_todo_status as _set_todo_status

    return _set_todo_status(conn, todo_id, status)


# ---------- 页面：数据管理 ----------


def page_management():
    st.header("🔄 数据管理")

    tab_crawl, tab_extract, tab_logs = st.tabs(["📡 抓取配置源", "🤖 批量提取", "📜 抓取日志"])

    # 抓取配置源
    with tab_crawl:
        st.subheader("手动触发抓取")
        config = load_config()
        sources = config.get("sources", [])
        for src in sources:
            with st.container(border=True):
                cols = st.columns([3, 1, 1])
                cols[0].write(f"**{src['name']}**")
                cols[0].caption(src["list_url"])
                if cols[1].button("开始抓取", key=f"crawl_{src['name']}", use_container_width=True):
                    with st.spinner(f"正在抓取 {src['name']}..."):
                        cfg = ListPageConfig(
                            list_url=src["list_url"],
                            source_name=src["name"],
                            url_pattern=src.get("url_pattern"),
                            max_pages=src.get("max_pages", 20),
                        )
                        result = WebCrawler(cfg).crawl()
                    st.success(
                        f"完成：发现 {result.total_discovered}，新增 {result.total_new}，"
                        f"更新 {result.total_updated}，跳过 {result.total_skipped}，失败 {result.total_failed}"
                    )
                    if result.errors:
                        with st.expander("错误详情"):
                            for e in result.errors[:10]:
                                st.warning(e)
                if cols[2].button("预览(不入库)", key=f"preview_{src['name']}", use_container_width=True):
                    with st.spinner("预览中..."):
                        cfg = ListPageConfig(
                            list_url=src["list_url"],
                            source_name=src["name"],
                            url_pattern=src.get("url_pattern"),
                            max_pages=min(src.get("max_pages", 20), 3),
                        )
                        result = WebCrawler(cfg).crawl()
                    if result.total_new > 0:
                        st.info(f"预览：会新增 {result.total_new} 条，发现 {result.total_discovered} 条")
                    else:
                        st.info("预览：无新增内容")

    # 批量提取
    with tab_extract:
        st.subheader("批量结构化提取")
        conn = get_connection()
        counts = count_notices_by_status(conn)
        conn.close()
        st.write(f"当前状态分布：{counts}")
        pending_raw = counts.get("raw", 0) + counts.get("failed", 0) + counts.get("partial", 0)
        if pending_raw > 0:
            limit = st.number_input("最多处理条数", 10, 200, 50, step=10)
            if st.button("🚀 开始批量提取", type="primary", use_container_width=True):
                with st.spinner("批量提取中...（每条约 3-8 秒）"):
                    conn = get_connection()
                    notices = []
                    for st_status in ["raw", "failed", "partial"]:
                        notices.extend(get_notices_by_status(conn, st_status, limit=limit))
                    conn.close()
                    if not notices:
                        st.info("没有待提取的通知")
                    else:
                        progress = st.progress(0)
                        status_text = st.empty()

                        def progress_callback(done, total):
                            progress.progress(done / total)
                            status_text.text(f"已处理 {done}/{total}")

                        # 用 run_batch_sync 的简化版，带进度回调
                        import asyncio

                        async def run_with_progress():
                            from core.extractor import NoticeExtractor
                            from storage.db import get_connection, mark_failed, update_extraction

                            extractor = NoticeExtractor()
                            conn = get_connection()
                            try:
                                counter = {"extracted": 0, "partial": 0, "failed": 0}
                                for i, n in enumerate(notices[:limit]):
                                    outcome = await extractor.extract_one(
                                        title=n["title"],
                                        content=n["raw_content"] or "",
                                        published_at=n["published_at"],
                                        crawled_at=n["crawled_at"],
                                    )
                                    key = outcome.status
                                    counter[key] = counter.get(key, 0) + 1
                                    if outcome.status == "failed":
                                        mark_failed(conn, n["id"], outcome.error or "")
                                    elif outcome.extraction:
                                        update_extraction(
                                            conn,
                                            n["id"],
                                            outcome.extraction.model_dump(),
                                            outcome.status,
                                        )
                                    progress_callback(i + 1, min(len(notices), limit))
                                return counter
                            finally:
                                conn.close()

                        result = asyncio.run(run_with_progress())
                        st.success(
                            f"完成：extracted {result.get('extracted', 0)}，"
                            f"partial {result.get('partial', 0)}，"
                            f"failed {result.get('failed', 0)}"
                        )
        else:
            st.info("没有待提取的通知（raw/failed/partial 均为 0）")

    # 抓取日志
    with tab_logs:
        st.subheader("最近抓取日志")
        logs = get_crawl_logs(get_connection(), limit=20)
        if logs:
            for log in logs:
                with st.expander(f"{log['source']} · {log['crawled_at'][:19]} · 新增 {log['total_new']} · 失败 {log['total_failed']}"):
                    st.write(f"发现: {log['total_discovered']}")
                    st.write(f"新增: {log['total_new']}")
                    st.write(f"跳过: {log['total_skipped']}")
                    st.write(f"更新: {log.get('total_updated', 0)}")
                    st.write(f"失败: {log['total_failed']}")
                    if log.get("errors"):
                        st.text(log["errors"])
        else:
            st.info("暂无抓取日志")


# ---------- 页面：导出 ----------


def page_export():
    st.header("📤 导出通知数据")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT source FROM notices ORDER BY source")
    sources = [row[0] for row in cursor.fetchall()]

    if not sources:
        st.info("数据库为空，无数据可导出")
        conn.close()
        return

    col_src, col_fmt = st.columns(2)
    source_filter = col_src.selectbox("数据源", ["全部"] + sources)
    export_fmt = col_fmt.selectbox("导出格式", ["CSV (Excel)", "JSON", "Markdown"])

    if source_filter == "全部":
        cursor.execute(
            "SELECT title, source, published_at, raw_content, url FROM notices ORDER BY published_at DESC"
        )
    else:
        cursor.execute(
            "SELECT title, source, published_at, raw_content, url FROM notices WHERE source = ? ORDER BY published_at DESC",
            (source_filter,),
        )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        st.info("没有可导出的数据")
        return

    st.write(f"共 {len(rows)} 条数据")

    if st.button("📥 生成并下载", type="primary", use_container_width=True):
        from datetime import datetime
        import csv
        import json
        import io

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"notices_{timestamp}"

        if export_fmt == "CSV (Excel)":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["标题", "来源", "发布日期", "内容", "链接"])
            for title, source, pub, content, url in rows:
                writer.writerow([title, source, pub or "", content or "", url])
            data = output.getvalue().encode("utf-8-sig")
            st.download_button(
                "下载 CSV",
                data=data,
                file_name=f"{filename_base}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        elif export_fmt == "JSON":
            data_list = []
            for title, source, pub, content, url in rows:
                data_list.append(
                    {"title": title, "source": source, "published_at": pub, "content": content, "url": url}
                )
            data = json.dumps(data_list, ensure_ascii=False, indent=2).encode("utf-8")
            st.download_button(
                "下载 JSON",
                data=data,
                file_name=f"{filename_base}.json",
                mime="application/json",
                use_container_width=True,
            )
        else:  # Markdown
            output = io.StringIO()
            output.write(f"# 校园通知导出\n\n")
            output.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            output.write(f"共 {len(rows)} 条通知\n\n")
            output.write("---\n\n")

            # 按来源分组
            by_source = {}
            for title, source, pub, content, url in rows:
                by_source.setdefault(source, []).append((title, pub, content, url))

            for source, items in by_source.items():
                output.write(f"## {source}\n\n")
                for title, pub, content, url in items:
                    date = pub or "未知日期"
                    output.write(f"### [{date}] {title}\n\n")
                    if content:
                        output.write(f"{content[:500]}\n\n")
                    output.write(f"[原文链接]({url})\n\n")
                    output.write("---\n\n")

            data = output.getvalue().encode("utf-8")
            st.download_button(
                "下载 Markdown",
                data=data,
                file_name=f"{filename_base}.md",
                mime="text/markdown",
                use_container_width=True,
            )


# ---------- 主入口 ----------


def main():
    st.sidebar.title("📚 校园通知助手")
    st.sidebar.caption("M1+M2+M3 整合版")

    page = st.sidebar.radio(
        "功能模块",
        [
            "📥 单链接分析",
            "📋 通知浏览",
            "✅ 待办清单",
            "🔄 数据管理",
            "📤 导出数据",
        ],
    )

    if page == "📥 单链接分析":
        page_single_analysis()
    elif page == "📋 通知浏览":
        page_browse()
    elif page == "✅ 待办清单":
        page_todos()
    elif page == "🔄 数据管理":
        page_management()
    elif page == "📤 导出数据":
        page_export()

    st.sidebar.divider()
    st.sidebar.caption("数据来源: 中南民族大学配置源")
    st.sidebar.caption("LLM: opencode-go (Kimi K2.7 Code)")


if __name__ == "__main__":
    main()