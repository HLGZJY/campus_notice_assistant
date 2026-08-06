"""校园通知智能助手 - M5 仪表盘首页。

运行方式：
    streamlit run app.py

入口页面会自动链接到 pages/ 目录下的子页面。
"""
from __future__ import annotations

import os
from datetime import datetime

import streamlit as st

from services.notice_service import get_notices, get_status_counts
from services.qa_service import get_index_stats
from services.todo_service import get_todo_stats

# 加载 .env（与 CLI 脚本保持一致）
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="校园通知智能助手",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🎓 校园通知智能助手")
st.caption("从爬取 → 提取 → 待办 → 问答的一站式校园通知工作台")

# 状态概览
st.subheader("📊 数据概览")

counts = get_status_counts()
todo_stats = get_todo_stats()
index_stats = get_index_stats()

if index_stats.get("error"):
    st.warning(f"向量索引暂不可用：{index_stats['error']}")

cols = st.columns(4)
cols[0].metric("通知总数", sum(counts.values()) or 0)
cols[1].metric("已提取", counts.get("extracted", 0) + counts.get("partial", 0))
cols[2].metric("待办待处理", todo_stats.get("pending", 0))
cols[3].metric("索引 chunks", index_stats.get("chunks", 0))

# 状态分布
st.divider()
left, right = st.columns(2)

with left:
    st.subheader("通知状态分布")
    if counts:
        status_labels = {
            "raw": "未提取",
            "extracted": "已提取",
            "partial": "部分提取",
            "failed": "提取失败",
        }
        data = {status_labels.get(k, k): v for k, v in sorted(counts.items())}
        st.bar_chart(data)
    else:
        st.info('暂无通知数据，请先在"通知浏览"页面触发抓取。')

with right:
    st.subheader("待办状态分布")
    st.bar_chart(
        {
            "待处理": todo_stats.get("pending", 0),
            "已完成": todo_stats.get("done", 0),
            "已跳过": todo_stats.get("skipped", 0),
        }
    )

# 快捷入口
st.divider()
st.subheader("🚀 快捷入口")
page_links = st.columns(3)
with page_links[0]:
    st.page_link("pages/1_📋_通知浏览.py", label="📋 通知浏览", use_container_width=True)
with page_links[1]:
    st.page_link("pages/2_✅_待办清单.py", label="✅ 待办清单", use_container_width=True)
with page_links[2]:
    st.page_link("pages/3_💬_智能问答.py", label="💬 智能问答", use_container_width=True)

# 最近通知
st.divider()
st.subheader("🆕 最近通知")
recent_notices = get_notices(limit=10)
if not recent_notices:
    st.info('暂无通知，请点击上方"通知浏览"页面手动抓取。')
else:
    for n in recent_notices:
        with st.container():
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{n['title']}**")
            c2.caption(f"{n.get('source', '-')} · {n.get('status', '-')}")
            st.caption(f"抓取时间：{n.get('crawled_at', '-')}")
        st.divider()

st.caption(f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
