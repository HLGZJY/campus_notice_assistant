"""校园通知助手 - 统一 Streamlit 应用。

运行：
    streamlit run app.py

功能模块：
- 📊 总览：紧急待办、最新通知、未处理通知、快速分析入口
- 📬 通知中心：URL 分析 / 全部通知浏览 / 未处理筛选
- 🎯 待办事项：按紧急程度分组（已过期 / 本周 / 更晚 / 已完成）
- ⚙️ 设置与导出：抓取管理、批量提取、日志、数据导出
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from core.analyze import analyze_notice_url
from core.models import ACTION_NOTICE_TYPES
from core.todo import generate_todos_for_notice
from crawler.base import ListPageConfig
from crawler.web_crawler import WebCrawler
from storage.db import (
    count_notices_by_status,
    delete_notice,
    delete_notices_bulk,
    delete_todo,
    get_connection,
    get_crawl_logs,
    get_notice,
    get_notice_stats,
    get_notices_by_status,
    get_todos,
    get_urgent_todos,
    search_notices,
    set_todo_status,
    update_notice_fields,
    update_todo,
)

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


def _db():
    return get_connection()


def load_config():
    with open("config/scuec.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config: dict):
    with open("config/scuec.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


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
        col_title, col_type = st.columns([5, 1])
        with col_title:
            st.markdown(f"### #{notice['id']} {notice['title']}")
        with col_type:
            if has_extraction:
                st.markdown(badge_html(extraction_fields["notice_type"]), unsafe_allow_html=True)

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
            rows = []

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

            if extraction_fields["target_audience"]:
                rows.append(
                    f'<div class="field-row"><span class="field-label">面向对象</span>'
                    f'<span class="field-value">{extraction_fields["target_audience"]}</span></div>'
                )

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

            if extraction_fields["location"]:
                loc_type = extraction_fields["location_type"] or ""
                rows.append(
                    f'<div class="field-row"><span class="field-label">地点</span>'
                    f'<span class="field-value">{extraction_fields["location"]} {f"({loc_type})" if loc_type else ""}</span></div>'
                )

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

            if extraction_fields["summary"]:
                rows.append(
                    f'<div class="field-row"><span class="field-label">摘要</span>'
                    f'<span class="field-value">{extraction_fields["summary"]}</span></div>'
                )

            if rows:
                st.markdown("".join(rows), unsafe_allow_html=True)

        with st.expander("📄 查看原文", expanded=False):
            st.text_area(
                "原文内容",
                value=notice.get("raw_content") or "（无内容）",
                height=200,
                disabled=True,
                label_visibility="collapsed",
                key=f"{key_prefix}_raw_{notice['id']}",
            )

        if show_actions and has_extraction:
            st.divider()
            btn_cols = st.columns([1, 1, 3])
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

            if btn_cols[1].button("🔗 打开原文", key=f"{key_prefix}_open_{notice['id']}", use_container_width=True):
                st.markdown(f"[在新标签页打开]({notice['url']})")

            if btn_cols[2].button("🔄 重新提取", key=f"{key_prefix}_reextract_{notice['id']}", use_container_width=True):
                with st.spinner("重新提取中..."):
                    result = analyze_notice_url(notice["url"], source_name=notice["source"], force=True)
                if result.status in ("ok", "cached"):
                    st.success("重新提取完成")
                    st.rerun()
                else:
                    st.error(f"重新提取失败: {result.error}")


def _render_todo_item(todo, key_prefix):
    """渲染单条待办项。"""
    today = datetime.now().date()
    expired = False
    due_soon = False
    if todo["due_at"]:
        try:
            due_date = datetime.fromisoformat(todo["due_at"]).date()
            expired = due_date < today
            due_soon = not expired and (due_date - today).days <= 7
        except ValueError:
            pass

    priority_cls = "high" if todo["priority"] == "high" else ""
    status_cls = todo["status"]

    due_display = (todo["due_at"] or "-")[:16].replace("T", " ")
    badge = ""
    if expired and todo["status"] == "pending":
        badge = " 🟥 **已过期**"
    elif due_soon:
        badge = " 🟨 **即将截止**"

    source_info = todo.get("notice_title") or f"#{todo.get('notice_id', '?')}"

    c1, c2, c3 = st.columns([6, 1, 1])
    c1.markdown(
        f'<div class="todo-item {priority_cls} {status_cls}">'
        f"<strong>{todo['action']}</strong><br>"
        f"<small>截止: {due_display}{badge} · 优先级: {todo['priority']} · 来源: {source_info}</small>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if todo["status"] == "pending":
        if c2.button("✅", key=f"{key_prefix}_done_{todo['id']}", help="标记完成"):
            set_todo_status(_db(), todo["id"], "done")
            st.rerun()
        if c3.button("⏭️", key=f"{key_prefix}_skip_{todo['id']}", help="跳过"):
            set_todo_status(_db(), todo["id"], "skipped")
            st.rerun()
    else:
        c2.markdown(f"`{todo['status']}`")
        if c3.button("🔄", key=f"{key_prefix}_reopen_{todo['id']}", help="恢复为待办"):
            set_todo_status(_db(), todo["id"], "pending")
            st.rerun()


# ---------- 页面：总览 ----------


def page_dashboard():
    st.header("📊 总览")

    conn = _db()
    stats = get_notice_stats(conn)
    pending_todos = get_todos(conn, status="pending")
    urgent = get_urgent_todos(conn, days=7)
    recent = search_notices(conn, limit=5)
    unprocessed = search_notices(conn, status="raw", limit=5)
    conn.close()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("通知总数", stats["total"])
    c2.metric("待处理待办", len(pending_todos))
    c3.metric("紧急待办", len(urgent))
    c4.metric("未处理通知", stats["by_status"].get("raw", 0) + stats["by_status"].get("failed", 0))

    st.divider()

    if urgent:
        st.subheader(f"🔴 紧急待办（{len(urgent)} 条）")
        for t in urgent[:5]:
            _render_todo_item(t, "dash_urgent")
        if len(pending_todos) > len(urgent):
            st.caption(f"还有 {len(pending_todos) - len(urgent)} 条非紧急待办 → 前往「待办事项」查看")
    else:
        st.info("🎉 没有紧急待办")

    st.divider()
    st.subheader("📰 最新通知")
    if recent:
        for n in recent:
            render_notice_card(n, key_prefix="dash_recent")
    else:
        st.info("暂无通知，前往「通知中心」分析链接或抓取数据")

    if unprocessed:
        st.divider()
        st.subheader(f"⚠️ 未处理通知（{stats['by_status'].get('raw', 0) + stats['by_status'].get('failed', 0)} 条）")
        for n in unprocessed:
            with st.container(border=True):
                st.write(f"**{n['title']}**")
                st.caption(f"{n['source']} · {n.get('published_at', '未知')[:10]}")
        st.caption("前往「设置与导出 → 批量提取」处理这些通知")


# ---------- 页面：通知中心 ----------


def page_notifications():
    st.header("📬 通知中心")

    tab_analyze, tab_browse, tab_unprocessed = st.tabs(["🔍 分析链接", "📋 全部通知", "⚠️ 未处理"])

    with tab_analyze:
        st.subheader("粘贴通知链接，自动提取结构化信息")
        col_url, col_opt = st.columns([4, 1])
        with col_url:
            url = st.text_input(
                "URL",
                placeholder="https://www.scuec.edu.cn/.../xxx.htm",
                label_visibility="collapsed",
            )
        with col_opt:
            force = st.checkbox("强制重新提取", value=False)

        if st.button("🔍 分析", type="primary", disabled=not url, use_container_width=True):
            with st.spinner("正在抓取与提取..."):
                result = analyze_notice_url(url, force=force)
            st.session_state["last_analysis"] = result

        result = st.session_state.get("last_analysis")
        if result:
            if result.status == "failed":
                st.error(f"❌ 分析失败: {result.error}")
            elif result.status == "cached":
                st.info('📋 显示缓存结果（勾选「强制重新提取」可重新分析）')
                notice = get_notice(_db(), result.notice_id)
                if notice:
                    render_notice_card(notice, key_prefix="nc_single")
            else:
                st.success("✅ 分析完成")
                notice = get_notice(_db(), result.notice_id)
                if notice:
                    render_notice_card(notice, key_prefix="nc_single")

    with tab_browse:
        conn = _db()
        stats = get_notice_stats(conn)

        c1, c2, c3 = st.columns(3)
        c1.metric("总计", stats["total"])
        c2.metric("已提取", stats["by_status"].get("extracted", 0))
        c3.metric("未处理", stats["by_status"].get("raw", 0) + stats["by_status"].get("failed", 0))

        with st.expander("🔍 筛选", expanded=True):
            fc1, fc2, fc3, fc4 = st.columns(4)
            keyword = fc1.text_input("关键词", placeholder="搜索标题/内容")
            notice_type = fc2.selectbox(
                "类型",
                ["全部"] + list(ACTION_NOTICE_TYPES) + ["policy", "result", "news", "other"],
            )
            status = fc3.selectbox("状态", ["全部", "extracted", "partial", "raw", "failed"])
            limit = fc4.number_input("条数", 10, 500, 50, step=10)

        notices = search_notices(
            conn,
            keyword=keyword or None,
            notice_type=notice_type if notice_type != "全部" else None,
            status=status if status != "全部" else None,
            limit=limit,
        )
        conn.close()

        if not notices:
            st.info("没有符合条件的通知")
        else:
            st.write(f"共 {len(notices)} 条")
            for n in notices:
                render_notice_card(n, key_prefix="nc_browse")

    with tab_unprocessed:
        conn = _db()
        raw_notices = search_notices(conn, status="raw", limit=100)
        failed_notices = search_notices(conn, status="failed", limit=100)
        conn.close()

        all_unprocessed = raw_notices + failed_notices
        if not all_unprocessed:
            st.info("🎉 所有通知均已处理")
        else:
            st.write(f"共 {len(all_unprocessed)} 条未处理通知")
            for n in all_unprocessed:
                with st.container(border=True):
                    st.write(f"**{n['title']}**")
                    st.caption(f"{n['source']} · {n.get('published_at', '未知')[:10]} · 状态: {n['status']}")
                    if st.button("🔄 重新提取", key=f"nc_reproc_{n['id']}"):
                        with st.spinner("提取中..."):
                            analyze_notice_url(n["url"], source_name=n["source"], force=True)
                        st.success("完成")
                        st.rerun()


# ---------- 页面：待办事项 ----------


def page_action_items():
    st.header("🎯 待办事项")

    conn = _db()
    all_todos = get_todos(conn)
    pending = [t for t in all_todos if t["status"] == "pending"]
    done = [t for t in all_todos if t["status"] in ("done", "skipped")]
    conn.close()

    today = datetime.now().date()
    week_later = today + timedelta(days=7)

    overdue = []
    this_week = []
    upcoming = []
    for t in pending:
        if not t["due_at"]:
            upcoming.append(t)
            continue
        try:
            due_date = datetime.fromisoformat(t["due_at"]).date()
            if due_date < today:
                overdue.append(t)
            elif due_date <= week_later:
                this_week.append(t)
            else:
                upcoming.append(t)
        except ValueError:
            upcoming.append(t)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("待处理", len(pending))
    c2.metric("已过期", len(overdue))
    c3.metric("本周截止", len(this_week))
    c4.metric("已完成/跳过", len(done))

    st.divider()

    if overdue:
        st.subheader(f"🔴 已过期（{len(overdue)}）")
        for t in overdue:
            _render_todo_item(t, "ov")
        st.divider()

    if this_week:
        st.subheader(f"🟡 本周截止（{len(this_week)}）")
        for t in this_week:
            _render_todo_item(t, "tw")
        st.divider()

    if upcoming:
        st.subheader(f"🔵 更晚 / 无截止日期（{len(upcoming)}）")
        for t in upcoming:
            _render_todo_item(t, "up")
        st.divider()

    if not pending:
        st.info("🎉 没有待处理事项")

    if done:
        with st.expander(f"✅ 已完成 / 已跳过（{len(done)}）"):
            for t in done:
                _render_todo_item(t, "dn")


# ---------- 页面：设置与导出 ----------


def page_settings():
    st.header("⚙️ 设置与导出")

    tab_sources, tab_data, tab_extract, tab_logs, tab_export = st.tabs(
        ["📡 抓取源管理", "🗃️ 数据管理", "🤖 批量提取", "📜 抓取日志", "📤 导出数据"]
    )

    # --- Tab 1: 抓取源管理 ---
    with tab_sources:
        st.subheader("抓取源配置")
        config = load_config()
        sources = config.get("sources", [])

        if sources:
            for idx, src in enumerate(sources):
                with st.container(border=True):
                    c1, c2, c3 = st.columns([4, 1, 1])
                    c1.write(f"**{src['name']}**")
                    c1.caption(src["list_url"])

                    if c2.button("编辑", key=f"edit_src_{idx}"):
                        st.session_state[f"editing_src_{idx}"] = True

                    if c3.button("删除", key=f"del_src_{idx}"):
                        st.session_state[f"confirm_del_src_{idx}"] = True

                    if st.session_state.get(f"confirm_del_src_{idx}"):
                        st.warning(f"确认删除「{src['name']}」？")
                        c_yes, c_no, _ = st.columns([1, 1, 4])
                        if c_yes.button("确认删除", key=f"yes_del_src_{idx}"):
                            config["sources"].pop(idx)
                            save_config(config)
                            st.session_state.pop(f"confirm_del_src_{idx}", None)
                            st.success("已删除")
                            st.rerun()
                        if c_no.button("取消", key=f"no_del_src_{idx}"):
                            st.session_state.pop(f"confirm_del_src_{idx}", None)
                            st.rerun()

                    if st.session_state.get(f"editing_src_{idx}"):
                        with st.form(key=f"form_edit_src_{idx}"):
                            new_name = st.text_input("名称", value=src["name"])
                            new_url = st.text_input("列表页 URL", value=src["list_url"])
                            new_pattern = st.text_input("URL 正则（可选）", value=src.get("url_pattern") or "")
                            new_max = st.number_input("最大页数", value=src.get("max_pages", 20), min_value=1, max_value=100)
                            fc1, fc2 = st.columns(2)
                            if fc1.form_submit_button("保存"):
                                config["sources"][idx] = {
                                    "name": new_name,
                                    "type": src.get("type", "web"),
                                    "list_url": new_url,
                                    "max_pages": new_max,
                                }
                                if new_pattern:
                                    config["sources"][idx]["url_pattern"] = new_pattern
                                save_config(config)
                                st.session_state.pop(f"editing_src_{idx}", None)
                                st.success("已保存")
                                st.rerun()
                            if fc2.form_submit_button("取消"):
                                st.session_state.pop(f"editing_src_{idx}", None)
                                st.rerun()

                    c_crawl, c_preview, _ = st.columns([1, 1, 4])
                    if c_crawl.button("开始抓取", key=f"crawl_{idx}", use_container_width=True):
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
                    if c_preview.button("预览(不入库)", key=f"preview_{idx}", use_container_width=True):
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
        else:
            st.info("暂无抓取源")

        st.divider()
        st.subheader("新增抓取源")
        with st.form(key="form_add_source"):
            add_name = st.text_input("名称", placeholder="如：计算机学院通知")
            add_url = st.text_input("列表页 URL", placeholder="https://...")
            add_pattern = st.text_input("URL 正则（可选）", placeholder="info/\\d+/\\d+\\.htm")
            add_max = st.number_input("最大页数", value=20, min_value=1, max_value=100)
            if st.form_submit_button("➕ 添加", type="primary"):
                if not add_name or not add_url:
                    st.error("名称和 URL 不能为空")
                else:
                    new_source = {
                        "name": add_name,
                        "type": "web",
                        "list_url": add_url,
                        "max_pages": add_max,
                    }
                    if add_pattern:
                        new_source["url_pattern"] = add_pattern
                    config.setdefault("sources", []).append(new_source)
                    save_config(config)
                    st.success(f"已添加「{add_name}」")
                    st.rerun()

    # --- Tab 2: 数据管理 ---
    with tab_data:
        st.subheader("通知管理")
        conn = _db()

        fc1, fc2, fc3 = st.columns(3)
        filter_source = fc1.selectbox("来源", ["全部"] + [r[0] for r in conn.execute("SELECT DISTINCT source FROM notices ORDER BY source").fetchall()])
        filter_status = fc2.selectbox("状态", ["全部", "extracted", "partial", "raw", "failed"])
        filter_limit = fc3.number_input("条数", 10, 500, 50, step=10)

        notices = search_notices(
            conn,
            notice_type=None,
            status=filter_status if filter_status != "全部" else None,
            limit=filter_limit,
        )
        if filter_source != "全部":
            notices = [n for n in notices if n["source"] == filter_source]

        st.write(f"共 {len(notices)} 条通知")

        for n in notices[:20]:
            with st.container(border=True):
                nc1, nc2, nc3 = st.columns([5, 1, 1])
                nc1.write(f"**#{n['id']} {n['title']}**")
                nc1.caption(f"{n['source']} · {n.get('published_at', '未知')[:10]} · {n['status']}")

                if nc2.button("编辑", key=f"edit_n_{n['id']}"):
                    st.session_state[f"editing_n_{n['id']}"] = True
                if nc3.button("删除", key=f"del_n_{n['id']}"):
                    st.session_state[f"confirm_del_n_{n['id']}"] = True

                if st.session_state.get(f"confirm_del_n_{n['id']}"):
                    st.warning("确认删除此通知？（关联待办也会删除）")
                    yc, nc, _ = st.columns([1, 1, 4])
                    if yc.button("确认删除", key=f"yes_del_n_{n['id']}"):
                        delete_notice(conn, n["id"])
                        st.session_state.pop(f"confirm_del_n_{n['id']}", None)
                        st.success("已删除")
                        st.rerun()
                    if nc.button("取消", key=f"no_del_n_{n['id']}"):
                        st.session_state.pop(f"confirm_del_n_{n['id']}", None)
                        st.rerun()

                if st.session_state.get(f"editing_n_{n['id']}"):
                    with st.form(key=f"form_edit_n_{n['id']}"):
                        new_title = st.text_input("标题", value=n["title"])
                        new_source = st.text_input("来源", value=n["source"])
                        new_summary = st.text_area("摘要", value=n.get("summary") or "")
                        new_status = st.selectbox("状态", ["raw", "extracted", "partial", "failed"], index=["raw", "extracted", "partial", "failed"].index(n["status"]))
                        fsc1, fsc2 = st.columns(2)
                        if fsc1.form_submit_button("保存"):
                            update_notice_fields(conn, n["id"], {
                                "title": new_title,
                                "source": new_source,
                                "summary": new_summary,
                                "status": new_status,
                            })
                            st.session_state.pop(f"editing_n_{n['id']}", None)
                            st.success("已保存")
                            st.rerun()
                        if fsc2.form_submit_button("取消"):
                            st.session_state.pop(f"editing_n_{n['id']}", None)
                            st.rerun()

        if len(notices) > 20:
            st.caption(f"仅显示前 20 条，共 {len(notices)} 条")

        st.divider()
        st.subheader("批量删除")
        bc1, bc2 = st.columns(2)
        bulk_source = bc1.selectbox("按来源删除", ["不选择"] + [r[0] for r in conn.execute("SELECT DISTINCT source FROM notices ORDER BY source").fetchall()])
        bulk_status = bc2.selectbox("按状态删除", ["不选择", "raw", "failed", "partial"])

        if bulk_source != "不选择" or bulk_status != "不选择":
            if st.button("🗑️ 执行批量删除", type="secondary"):
                st.session_state["confirm_bulk_delete"] = True

            if st.session_state.get("confirm_bulk_delete"):
                st.warning(f"确认删除？来源={bulk_source}，状态={bulk_status}")
                byc, bnc, _ = st.columns([1, 1, 4])
                if byc.button("确认", key="yes_bulk"):
                    count = delete_notices_bulk(
                        conn,
                        source=bulk_source if bulk_source != "不选择" else None,
                        status=bulk_status if bulk_status != "不选择" else None,
                    )
                    st.session_state.pop("confirm_bulk_delete", None)
                    st.success(f"已删除 {count} 条通知")
                    st.rerun()
                if bnc.button("取消", key="no_bulk"):
                    st.session_state.pop("confirm_bulk_delete", None)
                    st.rerun()

        conn.close()

        st.divider()
        st.subheader("待办管理")
        conn = _db()
        todos = get_todos(conn)
        conn.close()

        if not todos:
            st.info("暂无待办")
        else:
            st.write(f"共 {len(todos)} 条待办")
            for t in todos[:20]:
                with st.container(border=True):
                    tc1, tc2, tc3 = st.columns([5, 1, 1])
                    tc1.write(f"**{t['action']}**")
                    tc1.caption(f"截止: {(t['due_at'] or '-')[:16]} · 优先级: {t['priority']} · 状态: {t['status']}")

                    if tc2.button("编辑", key=f"edit_t_{t['id']}"):
                        st.session_state[f"editing_t_{t['id']}"] = True
                    if tc3.button("删除", key=f"del_t_{t['id']}"):
                        st.session_state[f"confirm_del_t_{t['id']}"] = True

                    if st.session_state.get(f"confirm_del_t_{t['id']}"):
                        st.warning("确认删除此待办？")
                        tyc, tnc, _ = st.columns([1, 1, 4])
                        if tyc.button("确认删除", key=f"yes_del_t_{t['id']}"):
                            conn = _db()
                            delete_todo(conn, t["id"])
                            conn.close()
                            st.session_state.pop(f"confirm_del_t_{t['id']}", None)
                            st.success("已删除")
                            st.rerun()
                        if tnc.button("取消", key=f"no_del_t_{t['id']}"):
                            st.session_state.pop(f"confirm_del_t_{t['id']}", None)
                            st.rerun()

                    if st.session_state.get(f"editing_t_{t['id']}"):
                        with st.form(key=f"form_edit_t_{t['id']}"):
                            new_action = st.text_input("待办内容", value=t["action"])
                            new_due = st.text_input("截止时间 (ISO格式)", value=t["due_at"] or "")
                            new_priority = st.selectbox("优先级", ["low", "normal", "high"], index=["low", "normal", "high"].index(t["priority"]))
                            ftc1, ftc2 = st.columns(2)
                            if ftc1.form_submit_button("保存"):
                                conn = _db()
                                update_todo(
                                    conn,
                                    t["id"],
                                    action=new_action,
                                    due_at=new_due if new_due else None,
                                    priority=new_priority,
                                )
                                conn.close()
                                st.session_state.pop(f"editing_t_{t['id']}", None)
                                st.success("已保存")
                                st.rerun()
                            if ftc2.form_submit_button("取消"):
                                st.session_state.pop(f"editing_t_{t['id']}", None)
                                st.rerun()

            if len(todos) > 20:
                st.caption(f"仅显示前 20 条，共 {len(todos)} 条")

    # --- Tab 3: 批量提取 ---
    with tab_extract:
        st.subheader("批量结构化提取")
        conn = _db()
        counts = count_notices_by_status(conn)
        conn.close()
        st.write(f"当前状态分布：{counts}")
        pending_raw = counts.get("raw", 0) + counts.get("failed", 0) + counts.get("partial", 0)
        if pending_raw > 0:
            limit = st.number_input("最多处理条数", 10, 200, 50, step=10)
            if st.button("🚀 开始批量提取", type="primary", use_container_width=True):
                with st.spinner("批量提取中...（每条约 3-8 秒）"):
                    conn = _db()
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

    # --- Tab 4: 抓取日志 ---
    with tab_logs:
        st.subheader("最近抓取日志")
        logs = get_crawl_logs(_db(), limit=20)
        if logs:
            for log in logs:
                with st.expander(
                    f"{log['source']} · {log['crawled_at'][:19]} · 新增 {log['total_new']} · 失败 {log['total_failed']}"
                ):
                    st.write(f"发现: {log['total_discovered']}")
                    st.write(f"新增: {log['total_new']}")
                    st.write(f"跳过: {log['total_skipped']}")
                    st.write(f"更新: {log.get('total_updated', 0)}")
                    st.write(f"失败: {log['total_failed']}")
                    if log.get("errors"):
                        st.text(log["errors"])
        else:
            st.info("暂无抓取日志")

    # --- Tab 5: 导出数据 ---
    with tab_export:
        st.subheader("导出通知数据")
        conn = _db()
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
            import csv
            import io
            import json

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
            else:
                output = io.StringIO()
                output.write("# 校园通知导出\n\n")
                output.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                output.write(f"共 {len(rows)} 条通知\n\n")
                output.write("---\n\n")

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

    page = st.sidebar.radio(
        "导航",
        [
            "📊 总览",
            "📬 通知中心",
            "🎯 待办事项",
            "⚙️ 设置与导出",
        ],
    )

    if page == "📊 总览":
        page_dashboard()
    elif page == "📬 通知中心":
        page_notifications()
    elif page == "🎯 待办事项":
        page_action_items()
    elif page == "⚙️ 设置与导出":
        page_settings()

    st.sidebar.divider()
    st.sidebar.caption("数据来源: 中南民族大学配置源")


if __name__ == "__main__":
    main()
