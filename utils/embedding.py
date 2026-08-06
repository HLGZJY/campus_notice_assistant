"""Embedding 客户端（M4 + M6 改造）。

M6 改造点：
  - 从 ConfigStore 读取 embedding 模型配置（provider + model）
  - 增加 version 感知：配置/模型变更后自动重建 embedding 实例
  - provider 不局限于 opencode-go，任何 OpenAI-compatible 端点均可配置
  - 未配置 base_url 或 provider 名为 local 时，fallback 到本地 sentence-transformers

复用 RAG 项目的 fallback 逻辑：
  1. 先尝试 OpenAI-compatible embedding API
  2. 不可用则自动切换到本地 sentence-transformers 的 all-MiniLM-L6-v2

为避免首次下载模型时访问 HuggingFace 被墙，默认设置 HF_ENDPOINT=https://hf-mirror.com。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from config.store import ConfigStore

# 国内镜像，避免首次下载模型时连接失败
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# 模块级缓存状态（被 ConfigStore.version 驱动失效）
_EMBEDDING_CACHE: Optional[object] = None
_CONFIG_VERSION_AT_LOAD: int = -1
_LAST_EMBEDDING_MODEL: Optional[str] = None
_LAST_EMBEDDING_PROVIDER: Optional[str] = None


def _probe_embedding_endpoint(base_url: str, api_key: str, model: str) -> bool:
    """直接探测 OpenAI-compatible embedding 接口是否可用，避免 OpenAIEmbeddings 打印 404 日志。"""
    import requests

    url = f"{base_url}/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        resp = requests.post(
            url,
            headers=headers,
            json={"input": "test", "model": model},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def create_embeddings(provider_name: Optional[str] = None, model_name: Optional[str] = None):
    """创建 embedding 实例。

    Args:
        provider_name: 供应商名；None 则从 ConfigStore 读取
        model_name: 模型名；None 则从 ConfigStore 读取
    """
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_openai import OpenAIEmbeddings

    store = ConfigStore.get_instance()
    if provider_name is None or model_name is None:
        provider, model_name = store.get_model("embedding")
        provider_name = provider.name
    else:
        provider = store.get_provider(provider_name)

    api_key = store.get_api_key(provider_name)

    # 1. 未配置 base_url 或明确本地 provider → 直接用本地模型
    if not provider.base_url:
        local_model = model_name if model_name else DEFAULT_LOCAL_EMBEDDING_MODEL
        # 兼容简写：all-MiniLM-L6-v2 → sentence-transformers/all-MiniLM-L6-v2
        if local_model and "/" not in local_model:
            local_model = f"sentence-transformers/{local_model}"
        logger.info(f"使用本地 embedding 模型: {local_model}")
        return HuggingFaceEmbeddings(
            model_name=local_model,
            model_kwargs={"local_files_only": True},
        )

    # 2. 尝试 OpenAI-compatible embedding API
    if api_key and _probe_embedding_endpoint(provider.base_url, api_key, model_name):
        try:
            embeddings = OpenAIEmbeddings(
                api_key=api_key,
                base_url=provider.base_url,
                model=model_name,
            )
            logger.info(f"使用 OpenAI-compatible embedding 模型: {model_name} @ {provider.base_url}")
            return embeddings
        except Exception as e:
            logger.warning(
                f"embedding 探测成功但初始化失败 ({type(e).__name__}: {e})，"
                f"切换为本地模型 {DEFAULT_LOCAL_EMBEDDING_MODEL}。"
            )
    else:
        reason = "API key 未配置" if not api_key else "embedding 接口探测失败"
        logger.warning(
            f"{reason}，自动 fallback 到本地模型 {DEFAULT_LOCAL_EMBEDDING_MODEL}。"
        )

    return HuggingFaceEmbeddings(
        model_name=DEFAULT_LOCAL_EMBEDDING_MODEL,
        model_kwargs={"local_files_only": True},
    )


def get_embeddings():
    """获取（缓存的）embedding 实例。

    通过比较 ConfigStore.version 与上次加载时的 version，
    自动识别配置变更并重建 embedding。
    """
    global _EMBEDDING_CACHE, _CONFIG_VERSION_AT_LOAD, _LAST_EMBEDDING_MODEL, _LAST_EMBEDDING_PROVIDER

    store = ConfigStore.get_instance()
    provider, model_name = store.get_model("embedding")
    current_version = store.version

    if (
        _EMBEDDING_CACHE is not None
        and _CONFIG_VERSION_AT_LOAD == current_version
        and _LAST_EMBEDDING_MODEL == model_name
        and _LAST_EMBEDDING_PROVIDER == provider.name
    ):
        return _EMBEDDING_CACHE

    _EMBEDDING_CACHE = create_embeddings(provider.name, model_name)
    _CONFIG_VERSION_AT_LOAD = current_version
    _LAST_EMBEDDING_MODEL = model_name
    _LAST_EMBEDDING_PROVIDER = provider.name
    return _EMBEDDING_CACHE


def invalidate_embedding_cache() -> None:
    """手动清空 embedding 缓存，下次调用 get_embeddings() 会重新创建实例。"""
    global _EMBEDDING_CACHE, _CONFIG_VERSION_AT_LOAD, _LAST_EMBEDDING_MODEL, _LAST_EMBEDDING_PROVIDER
    _EMBEDDING_CACHE = None
    _CONFIG_VERSION_AT_LOAD = -1
    _LAST_EMBEDDING_MODEL = None
    _LAST_EMBEDDING_PROVIDER = None
    logger.info("embedding 缓存已清空")


def get_embedding_model_info() -> dict:
    """返回当前 embedding 模型信息，供 UI 检测是否需要重建索引。"""
    store = ConfigStore.get_instance()
    provider, model_name = store.get_model("embedding")
    return {
        "provider": provider.name,
        "model": model_name,
        "base_url": provider.base_url,
        "api_key_status": store.get_api_key_status(provider.name),
    }
