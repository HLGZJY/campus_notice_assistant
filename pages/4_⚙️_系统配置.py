"""系统配置页面：M6 模型、数据源、供应商、数据管理入口。

设计原则：
  - 所有配置均通过 services.config_service 读写，不直接操作 YAML
  - API key 不在 UI 展示，仅显示是否已配置（✓/✗）
  - 保存前二次确认，避免误操作
  - 配置保存后调用 st.rerun()，由 Streamlit 重新加载配置
"""
from __future__ import annotations

import streamlit as st

from services.admin_service import (
    batch_delete_by_source,
    batch_delete_by_status,
    get_index_stats,
    rebuild_index,
)
from services.config_service import (
    check_embedding_changed,
    force_reload_config,
    get_config_disk_info,
    get_config_for_ui,
    get_provider_names,
    get_sources_for_ui,
    test_model_connection,
    test_source_url,
    update_models,
    update_providers,
    update_sources,
)

st.set_page_config(page_title="系统配置", page_icon="⚙️", layout="wide")

st.title("⚙️ 系统配置")

# 顶部文件信息
_disk_info = get_config_disk_info()
if _disk_info["exists"]:
    st.caption(f"配置文件: `{_disk_info['path']}` | 最后修改: {_disk_info.get('last_modified', '-')}")
else:
    st.caption(f"配置文件: `{_disk_info['path']}` | 尚未创建")

# 初始化 session state
for key in [
    "editing_model_task",
    "editing_source_index",
    "editing_provider_name",
    "pending_model_changes",
    "pending_provider_changes",
    "pending_source_changes",
    "show_model_confirm",
    "show_provider_confirm",
    "show_source_confirm",
    "show_index_rebuild_confirm",
    "show_batch_delete_source_confirm",
    "show_batch_delete_status_confirm",
]:
    if key not in st.session_state:
        st.session_state[key] = None


# ---------- 通用组件 ----------

def _reset_state(keys: list[str]) -> None:
    for k in keys:
        st.session_state[k] = None


def _diff_dict(old: dict, new: dict) -> dict:
    """返回两个 dict 的差异字段。"""
    diff = {}
    for k in set(old.keys()) | set(new.keys()):
        if old.get(k) != new.get(k):
            diff[k] = (old.get(k), new.get(k))
    return diff


def _model_diff_summary(old: dict, new: dict) -> str:
    lines = []
    for task in ("extraction", "qa", "todo", "embedding"):
        if old.get(task) != new.get(task):
            old_str = f"{old[task]['provider']}/{old[task]['model']}"
            new_str = f"{new[task]['provider']}/{new[task]['model']}"
            lines.append(f"- {task}: {old_str} → {new_str}")
    return "\n".join(lines)


# ---------- Tab 1: 模型配置 ----------

def render_model_config():
    st.subheader("🤖 模型配置")
    config = get_config_for_ui()
    models = config["models"]
    providers = config["providers"]
    provider_names = list(providers.keys())

    task_labels = {
        "extraction": "结构化提取",
        "qa": "智能问答",
        "todo": "待办生成",
        "embedding": "Embedding",
    }

    # 展示当前配置
    for task, label in task_labels.items():
        cols = st.columns([1.5, 2, 3, 1, 1])
        cols[0].markdown(f"**{label}**")
        cols[1].write(models[task]["provider"])
        cols[2].write(models[task]["model"])

        if cols[3].button("编辑", key=f"btn_edit_model_{task}", use_container_width=True):
            st.session_state.editing_model_task = task

        if cols[4].button("测试", key=f"btn_test_model_{task}", use_container_width=True):
            with st.spinner(f"测试 {task} 模型..."):
                result = test_model_connection(models[task]["provider"], models[task]["model"])
            if result["ok"]:
                st.success(f"连接成功，延迟 {result['latency_ms']}ms")
            else:
                st.error(f"连接失败: {result['error']}")

    # 编辑表单
    if st.session_state.editing_model_task:
        task = st.session_state.editing_model_task
        st.divider()
        st.markdown(f"**编辑 {task_labels.get(task, task)} 模型配置**")
        with st.form("form_edit_model"):
            provider = st.selectbox(
                "供应商",
                provider_names,
                index=provider_names.index(models[task]["provider"]) if models[task]["provider"] in provider_names else 0,
            )
            model = st.text_input("模型名", value=models[task]["model"])

            col1, col2 = st.columns(2)
            with col1:
                submitted = st.form_submit_button("保存", use_container_width=True)
            with col2:
                cancelled = st.form_submit_button("取消", use_container_width=True)

            if submitted:
                new_models = dict(models)
                new_models[task] = {"provider": provider, "model": model}
                st.session_state.pending_model_changes = new_models
                st.session_state.show_model_confirm = True
                st.session_state.editing_model_task = None
                st.rerun()
            if cancelled:
                st.session_state.editing_model_task = None
                st.rerun()

    # 二次确认对话框
    if st.session_state.show_model_confirm:
        pending = st.session_state.pending_model_changes
        old = models
        st.divider()
        st.warning("请确认以下配置变更：")
        st.markdown("```\n" + _model_diff_summary(old, pending) + "\n```")

        if pending.get("embedding") != old.get("embedding"):
            emb_old = old['embedding']['model']
            emb_new = pending['embedding']['model']
            if emb_new != emb_old:
                st.error(
                    "⚠️ Embedding 模型已变更。保存后建议立即在「数据管理」Tab 中重建索引，"
                    "否则旧 Chroma 索引与新模型可能不兼容。"
                )

        c1, c2 = st.columns(2)
        if c1.button("✅ 确认保存", key="btn_confirm_model_save", use_container_width=True):
            with st.spinner("保存中..."):
                result = update_models(pending)
            if result["ok"]:
                st.success("模型配置已保存并生效")
                _reset_state(["pending_model_changes", "show_model_confirm", "editing_model_task"])
                st.rerun()
            else:
                st.error(f"保存失败: {result['error']}")
        if c2.button("❌ 取消", key="btn_cancel_model_save", use_container_width=True):
            _reset_state(["pending_model_changes", "show_model_confirm", "editing_model_task"])
            st.rerun()


# ---------- Tab 2: 数据源管理 ----------

def render_source_management():
    st.subheader("📡 数据源管理")
    school = get_sources_for_ui()
    st.caption(f"当前学校: {school['name']} ({school['code']})")

    sources = school["sources"]

    # 展示列表
    for idx, src in enumerate(sources):
        cols = st.columns([4, 2, 1, 1, 1, 1])
        cols[0].write(src["name"])
        cols[1].write(src["list_url"])
        cols[2].write(f"页数: {src['max_pages']}")

        if cols[3].button("测试", key=f"btn_test_source_{idx}", use_container_width=True):
            with st.spinner("测试连接..."):
                result = test_source_url(src["list_url"])
            if result["ok"]:
                st.success(f"可达，HTTP {result['status_code']}，发现 {result['link_count']} 条链接，延迟 {result['latency_ms']}ms")
            else:
                st.error(f"失败: {result['error']}")

        if cols[4].button("编辑", key=f"btn_edit_source_{idx}", use_container_width=True):
            st.session_state.editing_source_index = idx

        if cols[5].button("删除", key=f"btn_delete_source_{idx}", use_container_width=True):
            new_sources = [s for i, s in enumerate(sources) if i != idx]
            st.session_state.pending_source_changes = new_sources
            st.session_state.show_source_confirm = True
            st.rerun()

    # 新增按钮
    if st.button("➕ 添加数据源", key="btn_add_source"):
        st.session_state.editing_source_index = "new"

    # 编辑/新增表单
    if st.session_state.editing_source_index is not None:
        idx = st.session_state.editing_source_index
        is_new = idx == "new"
        current = {"name": "", "type": "web", "list_url": "", "url_pattern": "", "max_pages": 5} if is_new else sources[idx]

        st.divider()
        st.markdown("**编辑数据源" if not is_new else "**新增数据源**")
        with st.form("form_edit_source"):
            name = st.text_input("来源名称", value=current["name"])
            list_url = st.text_input("列表页 URL", value=current["list_url"])
            url_pattern = st.text_input("URL 正则（可选，留空则自动发现）", value=current.get("url_pattern") or "")
            max_pages = st.number_input("最大翻页数", min_value=1, max_value=100, value=current["max_pages"])

            c1, c2 = st.columns(2)
            with c1:
                submitted = st.form_submit_button("保存", use_container_width=True)
            with c2:
                cancelled = st.form_submit_button("取消", use_container_width=True)

            if submitted:
                new_item = {
                    "name": name,
                    "type": "web",
                    "list_url": list_url,
                    "url_pattern": url_pattern.strip() or None,
                    "max_pages": int(max_pages),
                }
                new_sources = list(sources)
                if is_new:
                    new_sources.append(new_item)
                else:
                    new_sources[idx] = new_item
                st.session_state.pending_source_changes = new_sources
                st.session_state.show_source_confirm = True
                st.session_state.editing_source_index = None
                st.rerun()
            if cancelled:
                st.session_state.editing_source_index = None
                st.rerun()

    # 保存确认
    if st.session_state.show_source_confirm:
        pending = st.session_state.pending_source_changes
        st.divider()
        st.warning(f"确认保存数据源配置？当前 {len(sources)} 条，保存后 {len(pending)} 条。")
        c1, c2 = st.columns(2)
        if c1.button("✅ 确认保存", key="btn_confirm_source_save", use_container_width=True):
            with st.spinner("保存中..."):
                result = update_sources(pending)
            if result["ok"]:
                st.success("数据源配置已保存")
                _reset_state(["pending_source_changes", "show_source_confirm", "editing_source_index"])
                st.rerun()
            else:
                st.error(f"保存失败: {result['error']}")
        if c2.button("❌ 取消", key="btn_cancel_source_save", use_container_width=True):
            _reset_state(["pending_source_changes", "show_source_confirm", "editing_source_index"])
            st.rerun()


# ---------- Tab 3: 供应商管理 ----------

def render_provider_management():
    st.subheader("🔑 供应商管理")
    st.info("API Key 不在界面中保存，只保留引用环境变量名。如需修改密钥，请编辑项目根目录 `.env` 文件。")

    config = get_config_for_ui()
    providers = config["providers"]

    # 展示
    for name, p in providers.items():
        cols = st.columns([2, 4, 2, 1, 1, 1])
        cols[0].write(name)
        cols[1].write(p["base_url"] or "（本地）")
        key_status = "✅ 已配置" if p["api_key_status"] else "❌ 未配置"
        cols[2].write(f"{p['api_key_env']} {key_status}")

        if cols[3].button("测试", key=f"btn_test_provider_{name}", use_container_width=True):
            st.info("请在「模型配置」Tab 中测试具体模型，结果更准确。")

        if cols[4].button("编辑", key=f"btn_edit_provider_{name}", use_container_width=True):
            st.session_state.editing_provider_name = name

        if cols[5].button("删除", key=f"btn_delete_provider_{name}", use_container_width=True):
            if name == "local":
                st.error("local 供应商为内置项，不能删除")
            else:
                new_providers = {k: v for k, v in providers.items() if k != name}
                st.session_state.pending_provider_changes = new_providers
                st.session_state.show_provider_confirm = True
                st.rerun()

    # 新增按钮
    if st.button("➕ 添加供应商", key="btn_add_provider"):
        st.session_state.editing_provider_name = "__new__"

    # 编辑/新增表单
    if st.session_state.editing_provider_name:
        name = st.session_state.editing_provider_name
        is_new = name == "__new__"
        current = providers.get(name, {"name": "", "base_url": "", "api_key_env": ""})

        st.divider()
        st.markdown("**编辑供应商**" if not is_new else "**新增供应商**")
        with st.form("form_edit_provider"):
            provider_name = st.text_input("供应商名称", value=name if not is_new else "", disabled=not is_new)
            base_url = st.text_input("base_url（OpenAI-compatible 端点）", value=current["base_url"])
            api_key_env = st.text_input("API Key 环境变量名", value=current["api_key_env"])

            c1, c2 = st.columns(2)
            with c1:
                submitted = st.form_submit_button("保存", use_container_width=True)
            with c2:
                cancelled = st.form_submit_button("取消", use_container_width=True)

            if submitted:
                new_providers = dict(providers)
                new_providers[provider_name] = {
                    "name": provider_name,
                    "base_url": base_url.strip(),
                    "api_key_env": api_key_env.strip(),
                }
                st.session_state.pending_provider_changes = new_providers
                st.session_state.show_provider_confirm = True
                st.session_state.editing_provider_name = None
                st.rerun()
            if cancelled:
                st.session_state.editing_provider_name = None
                st.rerun()

    # 保存确认
    if st.session_state.show_provider_confirm:
        pending = st.session_state.pending_provider_changes
        st.divider()
        st.warning(f"确认保存供应商配置？当前 {len(providers)} 个，保存后 {len(pending)} 个。")
        c1, c2 = st.columns(2)
        if c1.button("✅ 确认保存", key="btn_confirm_provider_save", use_container_width=True):
            with st.spinner("保存中..."):
                result = update_providers(pending)
            if result["ok"]:
                st.success("供应商配置已保存")
                _reset_state(["pending_provider_changes", "show_provider_confirm", "editing_provider_name"])
                st.rerun()
            else:
                st.error(f"保存失败: {result['error']}")
        if c2.button("❌ 取消", key="btn_cancel_provider_save", use_container_width=True):
            _reset_state(["pending_provider_changes", "show_provider_confirm", "editing_provider_name"])
            st.rerun()


# ---------- Tab 4: 数据管理 ----------

def render_data_management():
    st.subheader("🗃️ 数据管理")

    # 索引管理
    with st.expander("向量索引管理", expanded=True):
        stats = get_index_stats()
        if stats.get("error"):
            st.error(f"向量索引状态异常: {stats['error']}")
        else:
            st.write(f"当前索引 chunk 数: **{stats.get('chunks', 0)}**")
            st.write(f"持久化目录: `{stats.get('persist_dir', '-')}`")

        if st.button("🔄 全量重建索引", key="btn_rebuild_index"):
            st.session_state.show_index_rebuild_confirm = True

        if st.session_state.show_index_rebuild_confirm:
            st.warning("重建索引会删除旧 Chroma collection，重新切分所有已提取通知。是否继续？")
            c1, c2 = st.columns(2)
            if c1.button("✅ 确认重建", key="btn_confirm_rebuild_index", use_container_width=True):
                with st.spinner("重建索引中..."):
                    result = rebuild_index()
                if result.get("error"):
                    st.error(f"重建失败: {result['error']}")
                else:
                    st.success(f"重建完成：{result['notices']} 条通知，{result['chunks']} 个 chunk")
                st.session_state.show_index_rebuild_confirm = False
                st.rerun()
            if c2.button("❌ 取消", key="btn_cancel_rebuild_index", use_container_width=True):
                st.session_state.show_index_rebuild_confirm = False
                st.rerun()

    st.divider()

    # 批量删除
    with st.expander("批量删除通知"):
        # 按来源
        from services.notice_service import get_sources
        sources = get_sources()
        if sources:
            selected_source = st.selectbox("选择来源", sources, key="batch_delete_source")
            if st.button("删除该来源全部通知", key="btn_batch_delete_source"):
                st.session_state.show_batch_delete_source_confirm = True

            if st.session_state.show_batch_delete_source_confirm:
                st.warning(f"确认删除来源「{selected_source}」的全部通知？关联待办和索引 chunk 也会被清理。")
                c1, c2 = st.columns(2)
                if c1.button("✅ 确认删除", key="btn_confirm_delete_source", use_container_width=True):
                    with st.spinner("删除中..."):
                        result = batch_delete_by_source(selected_source)
                    if result["ok"]:
                        st.success(f"已删除 {result['deleted_notices']} 条通知")
                    else:
                        st.error(f"删除失败: {result['error']}")
                    st.session_state.show_batch_delete_source_confirm = False
                    st.rerun()
                if c2.button("❌ 取消", key="btn_cancel_delete_source", use_container_width=True):
                    st.session_state.show_batch_delete_source_confirm = False
                    st.rerun()
        else:
            st.info("暂无来源数据")

        # 按状态
        st.divider()
        selected_status = st.selectbox(
            "选择状态",
            ["raw", "extracted", "partial", "failed"],
            key="batch_delete_status",
        )
        if st.button("删除该状态全部通知", key="btn_batch_delete_status"):
            st.session_state.show_batch_delete_status_confirm = True

        if st.session_state.show_batch_delete_status_confirm:
            st.warning(f"确认删除所有状态为「{selected_status}」的通知？")
            c1, c2 = st.columns(2)
            if c1.button("✅ 确认删除", key="btn_confirm_delete_status", use_container_width=True):
                with st.spinner("删除中..."):
                    result = batch_delete_by_status(selected_status)
                if result["ok"]:
                    st.success(f"已删除 {result['deleted_notices']} 条通知")
                else:
                    st.error(f"删除失败: {result['error']}")
                st.session_state.show_batch_delete_status_confirm = False
                st.rerun()
            if c2.button("❌ 取消", key="btn_cancel_delete_status", use_container_width=True):
                st.session_state.show_batch_delete_status_confirm = False
                st.rerun()


# ---------- Tab 5: 配置重载（放在末尾） ----------

def render_reload():
    st.subheader("🔄 重新加载配置")
    st.info("如果你手动编辑了 config/app.yaml 或 config/schools/*.yaml，可点击下面按钮从磁盘重新加载。")
    if st.button("从磁盘重新加载配置", key="btn_force_reload"):
        with st.spinner("加载中..."):
            result = force_reload_config()
        if result["ok"]:
            st.success("配置已重新加载")
            st.rerun()
        else:
            st.error(f"加载失败: {result['error']}")


# ---------- 主界面 ----------

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🤖 模型配置", "📡 数据源管理", "🔑 供应商管理", "🗃️ 数据管理", "🔄 重载配置"]
)

with tab1:
    render_model_config()
with tab2:
    render_source_management()
with tab3:
    render_provider_management()
with tab4:
    render_data_management()
with tab5:
    render_reload()
