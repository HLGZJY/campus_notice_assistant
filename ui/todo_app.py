"""M3 小界面：待办生成 Demo（Streamlit）。

MVP 形态：用户查看通知 → 点"生成待办"才生成 → 过期待办灰显。
M5 会把这页吸收合并进完整应用。

运行：streamlit run ui/todo_app.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from core.todo import generate_todos_for_notice
from storage.db import get_connection, get_todos, set_todo_status

st.set_page_config(page_title="待办 Demo (M3)", layout="wide")
st.title("待办生成 Demo（M3）")
st.caption("MVP 形态：用户查看通知，点“生成待办”才生成；过期待办灰显。")

ACTION_TYPES = (
    "competition", "lecture", "registration",
    "scholarship", "administrative", "recruitment",
)
today = datetime.now().date()
conn = get_connection()

# ---------- 1. 通知列表 + 生成按钮 ----------
st.header("通知列表（行动型）")
notices = conn.execute(
    f"""SELECT id, title, notice_type, deadline, status FROM notices
        WHERE status IN ('extracted','partial')
          AND notice_type IN ({','.join('?' * len(ACTION_TYPES))})
        ORDER BY deadline IS NULL, deadline ASC, id ASC""",
    list(ACTION_TYPES),
).fetchall()

if not notices:
    st.info("还没有已提取的行动型通知，先跑 `python extract.py`。")
else:
    for n in notices:
        c1, c2 = st.columns([7, 2])
        c1.markdown(f"**#{n['id']}** {n['title']}")
        c1.caption(
            f"类型: {n['notice_type']}  · 截止: {n['deadline'] or '-'}  · "
            f"通知状态: {n['status']}"
        )
        if c2.button("生成待办", key=f"gen_{n['id']}"):
            with st.spinner("生成中..."):
                outcome = generate_todos_for_notice(n["id"])
            if outcome.status == "generated":
                st.success(f"已生成 {len(outcome.items)} 条待办")
                for it in outcome.items:
                    st.write(f"- {it.action}")
            else:
                st.info(outcome.error)
            st.rerun()

# ---------- 2. 待办清单 ----------
st.header("待办清单（按截止升序）")
todos = get_todos(conn)

if not todos:
    st.info("暂无待办，去上面点“生成待办”。")
else:
    for t in todos:
        expired = (
            t["due_at"] and t["due_at"][:10] < today.isoformat()
            and t["status"] == "pending"
        )
        if expired:
            color = "gray"
        elif t["priority"] == "high":
            color = "red"
        else:
            color = "black"
        due = (t["due_at"] or "-")[:19]
        c1, c2, c3 = st.columns([7, 1, 1])
        c1.markdown(
            f"<span style='color:{color}'>{t['action']}</span>  "
            f"<span style='color:{color}'>（截止 {due}，{t['status']}"
            f"{' · 已过期' if expired else ''}）</span>",
            unsafe_allow_html=True,
        )
        if t["status"] == "pending":
            if c2.button("完成", key=f"done_{t['id']}"):
                set_todo_status(conn, t["id"], "done")
                st.rerun()
            if c3.button("跳过", key=f"skip_{t['id']}"):
                set_todo_status(conn, t["id"], "skipped")
                st.rerun()
        else:
            c2.write(t["status"])
            c3.write("")

conn.close()
