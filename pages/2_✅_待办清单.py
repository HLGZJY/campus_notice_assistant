"""待办清单页面：M3 待办的 UI 入口。"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from services.notice_service import get_notices
from services.todo_service import generate_todos, get_todos, mark_todo

st.set_page_config(page_title="待办清单", page_icon="✅", layout="wide")

st.title("✅ 待办清单")

# 筛选
status_filter = st.radio(
    "状态筛选",
    options=["all", "pending", "done", "skipped"],
    format_func=lambda x: {
        "all": "全部",
        "pending": "待处理",
        "done": "已完成",
        "skipped": "已跳过",
    }.get(x, x),
    horizontal=True,
)

todos = get_todos(status=status_filter if status_filter != "all" else None)

# 统计
pending_count = len([t for t in todos if t["status"] == "pending"])
overdue_count = 0
for t in todos:
    if t["status"] == "pending" and t.get("due_at"):
        try:
            due = datetime.fromisoformat(t["due_at"])
            if due < datetime.now():
                overdue_count += 1
        except ValueError:
            pass

st.caption(f"共 {len(todos)} 条待办，待处理 {pending_count} 条，过期 {overdue_count} 条")

# 新增待办
st.divider()
st.subheader("为通知生成待办")
action_notices = get_notices(status="extracted", is_action=True, limit=100)
notice_options = {f"{n['title']} (#{n['id']})": n for n in action_notices}
selected = st.selectbox("选择通知", options=[""] + list(notice_options.keys()), format_func=lambda x: x if x else "请选择一条通知")
if selected and st.button("生成待办", type="primary"):
    notice_id = notice_options[selected]["id"]
    with st.spinner("生成中..."):
        result = generate_todos(notice_id)
    if result["success"]:
        st.success("待办生成成功")
    else:
        st.error(f"生成失败: {result.get('error')}")
    st.rerun()

st.divider()

if not todos:
    st.info('暂无待办事项。请到"通知浏览"页面选择行动型通知生成待办。')
    st.stop()

# 待办列表
for t in todos:
    is_overdue = False
    due_text = t.get("due_at") or "无截止时间"
    if t.get("due_at"):
        try:
            due = datetime.fromisoformat(t["due_at"])
            is_overdue = t["status"] == "pending" and due < datetime.now()
            due_text = due.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass

    priority_color = "red" if t.get("priority") == "high" else "gray"
    border_color = "border-left: 4px solid red;" if is_overdue else "border-left: 4px solid #ddd;"

    with st.container(border=True):
        st.markdown(
            f"<div style='{border_color} padding-left: 12px;'>"
            f"<span style='color:{priority_color}; font-weight:bold;'>[{t.get('priority', 'normal').upper()}]</span> "
            f"<b>{t['action']}</b></div>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"截止：{due_text} · "
            f"来源：《{t.get('notice_title', '未知通知')}》 · "
            f"类型：{t.get('notice_type', '-')} · "
            f"状态：{t['status']}"
        )
        if is_overdue:
            st.error("⚠️ 已过期")

        if t["status"] == "pending":
            btn_cols = st.columns([1, 1, 4])
            with btn_cols[0]:
                if st.button("完成", key=f"done_{t['id']}", use_container_width=True):
                    mark_todo(t["id"], "done")
                    st.rerun()
            with btn_cols[1]:
                if st.button("跳过", key=f"skip_{t['id']}", use_container_width=True):
                    mark_todo(t["id"], "skipped")
                    st.rerun()
        elif t["status"] in {"done", "skipped"}:
            if st.button("恢复为待处理", key=f"pending_{t['id']}", use_container_width=True):
                mark_todo(t["id"], "pending")
                st.rerun()
