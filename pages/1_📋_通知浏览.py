"""通知浏览页面：M1 爬取 + M2 提取的 UI 入口。"""
from __future__ import annotations

import streamlit as st

from core.models import ACTION_NOTICE_TYPES
from services.admin_service import delete_notice, re_extract_notice
from services.notice_service import (
    crawl_all_sources,
    extract_batch,
    extract_notice,
    get_notice_detail,
    get_notices,
    get_notice_types,
    get_sources,
    get_status_counts,
)
from services.todo_service import generate_todos

st.set_page_config(page_title="通知浏览", page_icon="📋", layout="wide")

st.title("📋 通知浏览")

# 顶部操作按钮
st.subheader("操作")
action_cols = st.columns([1, 1, 2])

with action_cols[0]:
    crawl_clicked = st.button("🕷️ 抓取全部数据源", use_container_width=True, type="primary")
with action_cols[1]:
    extract_clicked = st.button("🔍 批量提取未处理通知", use_container_width=True)

# 状态反馈
if crawl_clicked:
    with st.spinner("正在抓取，请稍候..."):
        try:
            results = crawl_all_sources()
            total_new = sum(r["new"] for r in results.values())
            st.success(f"抓取完成！共 {len(results)} 个数据源，新增 {total_new} 条通知。")
            for name, r in results.items():
                st.caption(f"{name}: 发现 {r['discovered']} / 新增 {r['new']} / 跳过 {r['skipped']} / 失败 {r['failed']}")
            if any(r["errors"] for r in results.values()):
                with st.expander("查看错误详情"):
                    for name, r in results.items():
                        for err in r["errors"]:
                            st.error(f"{name}: {err}")
        except Exception as e:
            st.error(f"抓取失败: {type(e).__name__}: {e}")
    st.rerun()

if extract_clicked:
    with st.spinner("正在提取结构化信息，请稍候..."):
        try:
            result = extract_batch(limit=50, auto_index=True)
            st.success(
                f"批量提取完成！处理 {result['processed']} 条，"
                f"成功 {result['summary'].get('extracted', 0)}，部分 {result['summary'].get('partial', 0)}，"
                f"失败 {result['summary'].get('failed', 0)}"
            )
        except Exception as e:
            st.error(f"提取失败: {type(e).__name__}: {e}")
    st.rerun()

st.divider()

# 筛选器
st.subheader("筛选")
statuses = ["", "raw", "extracted", "partial", "failed"]
sources = [""] + get_sources()
types = [""] + get_notice_types()

filter_cols = st.columns([1, 1, 1, 2, 1])
with filter_cols[0]:
    selected_status = st.selectbox("状态", statuses, format_func=lambda x: x if x else "全部")
with filter_cols[1]:
    selected_source = st.selectbox("来源", sources, format_func=lambda x: x if x else "全部")
with filter_cols[2]:
    selected_type = st.selectbox("类型", types, format_func=lambda x: x if x else "全部")
with filter_cols[3]:
    keyword = st.text_input("标题关键词", placeholder="输入关键词搜索标题")
with filter_cols[4]:
    is_action = st.checkbox("仅行动型", value=False)

notices = get_notices(
    status=selected_status or None,
    source=selected_source or None,
    notice_type=selected_type or None,
    keyword=keyword or None,
    is_action=is_action if is_action else None,
    limit=200,
)

st.subheader(f"通知列表（共 {len(notices)} 条）")

counts = get_status_counts()
st.caption(f"数据库状态：raw {counts.get('raw', 0)} / extracted {counts.get('extracted', 0)} / partial {counts.get('partial', 0)} / failed {counts.get('failed', 0)}")

if not notices:
    st.info('没有符合条件的通知。请先点击"抓取全部数据源"。')
    st.stop()

# 通知列表
for n in notices:
    with st.container(border=True):
        header_cols = st.columns([4, 2])
        with header_cols[0]:
            st.markdown(f"**{n['title']}**")
        with header_cols[1]:
            badges = []
            if n.get("status"):
                status_label = {
                    "raw": "🔴 未提取",
                    "extracted": "🟢 已提取",
                    "partial": "🟡 部分提取",
                    "failed": "⚫ 失败",
                }.get(n["status"], n["status"])
                badges.append(status_label)
            if n.get("notice_type"):
                badges.append(n["notice_type"])
            if n.get("source"):
                badges.append(n["source"])
            st.markdown(" · ".join(badges))

        meta_cols = st.columns([1, 1, 1, 2])
        with meta_cols[0]:
            st.caption(f"发布时间：{n.get('published_at') or '-'}")
        with meta_cols[1]:
            st.caption(f"截止时间：{n.get('deadline') or '-'}")
        with meta_cols[2]:
            st.caption(f"抓取：{n.get('crawled_at') or '-'}")
        with meta_cols[3]:
            btn_cols = st.columns([1, 1, 1, 1, 1])
            with btn_cols[0]:
                if n.get("status") == "raw":
                    if st.button("🔍 提取", key=f"extract_{n['id']}", use_container_width=True):
                        with st.spinner("提取中..."):
                            try:
                                result = extract_notice(n["id"], auto_index=True)
                                if result["success"]:
                                    st.success("提取成功")
                                else:
                                    st.error(f"提取失败: {result.get('error')}")
                            except Exception as e:
                                st.error(f"提取失败: {type(e).__name__}: {e}")
                        st.rerun()
                elif n.get("status") in ("extracted", "partial", "failed"):
                    if st.button("🔄 重提", key=f"reextract_{n['id']}", use_container_width=True):
                        with st.spinner("重新提取中..."):
                            try:
                                result = re_extract_notice(n["id"], auto_index=True)
                                if result["success"]:
                                    st.success("重新提取成功")
                                else:
                                    st.error(f"重新提取失败: {result.get('error')}")
                            except Exception as e:
                                st.error(f"重新提取失败: {type(e).__name__}: {e}")
                        st.rerun()
            with btn_cols[1]:
                if n.get("notice_type") in ACTION_NOTICE_TYPES:
                    if st.button("✅ 生成待办", key=f"todo_{n['id']}", use_container_width=True):
                        with st.spinner("生成待办中..."):
                            result = generate_todos(n["id"])
                            if result["success"]:
                                st.success("已生成待办")
                            else:
                                st.error(f"生成失败: {result.get('error')}")
                        st.rerun()
            with btn_cols[2]:
                if n.get("url"):
                    st.link_button("🔗 原文", url=n["url"], use_container_width=True)
            with btn_cols[3]:
                with st.popover("🗑️ 删除", use_container_width=True):
                    st.warning("删除将同时清理该通知的待办和向量索引 chunk。")
                    c1, c2 = st.columns(2)
                    if c1.button("确认", key=f"confirm_yes_{n['id']}", use_container_width=True):
                        with st.spinner("删除中..."):
                            result = delete_notice(n["id"])
                        if result["ok"]:
                            st.success("已删除")
                        else:
                            st.error(f"删除失败: {result.get('error')}")
                        st.rerun()
                    if c2.button("取消", key=f"confirm_no_{n['id']}", use_container_width=True):
                        pass

        with st.expander("查看详情 / 原文"):
            detail = get_notice_detail(n["id"])
            if detail:
                st.markdown("**结构化字段**")
                st.json(
                    {
                        "notice_type": detail.get("notice_type"),
                        "target_audience": detail.get("target_audience"),
                        "signup_method": detail.get("signup_method"),
                        "signup_url": detail.get("signup_url"),
                        "location": detail.get("location"),
                        "location_type": detail.get("location_type"),
                        "deadline_raw": detail.get("deadline_raw"),
                        "deadline": detail.get("deadline"),
                        "key_dates": detail.get("key_dates", []),
                        "summary": detail.get("summary"),
                    }
                )
                st.markdown("**原文内容**")
                st.text_area("正文", detail.get("raw_content", "")[:5000], height=300, label_visibility="collapsed")
            else:
                st.error("通知详情加载失败")
