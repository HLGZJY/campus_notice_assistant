"""智能问答页面：M4 RAG 问答的 UI 入口。"""
from __future__ import annotations

import streamlit as st

from services.qa_service import ask, get_index_stats

st.set_page_config(page_title="智能问答", page_icon="💬", layout="wide")

st.title("💬 智能问答")

stats = get_index_stats()

if stats.get("error"):
    st.error(f"向量索引加载失败：{stats['error']}")
    st.info("请尝试使用项目目录下的 .venv 启动：.\\.venv\\Scripts\\python.exe -m streamlit run app.py")
else:
    st.caption(f"当前索引：{stats.get('chunks', 0)} 个文本块")
    if stats.get("chunks", 0) == 0:
        st.warning('向量索引为空，请先前往"通知浏览"页面抓取并提取通知。提取成功后会自动加入索引。')

# 初始化对话历史
if "qa_history" not in st.session_state:
    st.session_state.qa_history = []

st.subheader("提问")
question = st.text_input(
    "请输入你的问题",
    placeholder="例如：最近有哪些数学建模比赛？报名截止时间是什么时候？",
    label_visibility="collapsed",
)
ask_clicked = st.button("发送", type="primary", use_container_width=False)

if ask_clicked and question.strip():
    with st.spinner("正在检索并生成回答..."):
        try:
            result = ask(question.strip())
            st.session_state.qa_history.append(
                {
                    "question": question.strip(),
                    "answer": result.answer,
                    "sources": result.sources,
                    "retrieved_chunks": result.retrieved_chunks,
                }
            )
        except Exception as e:
            st.error(f"问答失败: {type(e).__name__}: {e}")
    st.rerun()

# 展示历史对话
st.divider()
st.subheader("对话记录")

if not st.session_state.qa_history:
    st.info("还没有提问，请在上方输入框开始提问。")

for idx, item in enumerate(reversed(st.session_state.qa_history)):
    with st.chat_message("user"):
        st.markdown(item["question"])
    with st.chat_message("assistant"):
        st.markdown(item["answer"])
        st.caption(f"检索到 {item.get('retrieved_chunks', 0)} 个文本块")
        if item.get("sources"):
            with st.expander("查看来源"):
                for s in item["sources"]:
                    st.markdown(
                        f"- **{s.title}** "
                        f"(类型：{s.notice_type or '-'}，"
                        f"截止：{s.deadline or '-'}，"
                        f"ID：{s.notice_id})"
                    )
                    if s.url:
                        st.caption(s.url)
        else:
            st.caption("未检索到相关来源")

st.divider()
with st.expander("索引管理"):
    st.markdown(f"- 索引持久化目录：`{stats.get('persist_dir', '-')}`")
    st.markdown(f"- 当前文档块数：{stats.get('chunks', 0)}")
    st.info("索引会在通知提取成功后自动增量更新。如需全量重建，请使用 CLI 工具 index.py。")
