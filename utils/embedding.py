"""Embedding 客户端（M4）。

复用 RAG 项目的 fallback 逻辑：
  1. 先尝试 opencode-go 的 embedding API
  2. 不可用（已实测不支持）则自动切换到本地 sentence-transformers 的 all-MiniLM-L6-v2

为避免首次下载模型时访问 HuggingFace 被墙，默认设置 HF_ENDPOINT=https://hf-mirror.com。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# 确保能读取项目根目录的 .env
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# 国内镜像，避免首次下载模型时连接失败
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
LOCAL_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class _LazyEmbedding:
    """延迟初始化 embedding 对象：首次调用时才真正创建，并复用实例。"""

    def __init__(self):
        self._embedding = None

    def get(self):
        if self._embedding is None:
            self._embedding = create_embeddings()
        return self._embedding


def _probe_opencode_embedding(base_url: str, api_key: str, model: str) -> bool:
    """直接探测 opencode-go embedding 接口是否可用，避免 OpenAIEmbeddings 打印 404 日志。"""
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


def create_embeddings():
    """优先尝试 opencode-go embedding，失败则 fallback 到本地轻量模型。"""
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_openai import OpenAIEmbeddings

    api_key = os.environ.get("OPENCODE_API_KEY", "").strip()
    base_url = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1").strip()
    model = os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL

    if _probe_opencode_embedding(base_url, api_key, model):
        try:
            embeddings = OpenAIEmbeddings(
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            logger.info(f"使用 opencode-go embedding 模型: {model}")
            return embeddings
        except Exception as e:
            logger.warning(
                f"opencode-go embedding 探测成功但初始化失败 ({type(e).__name__}: {e})，"
                f"切换为本地模型 {LOCAL_EMBEDDING_MODEL}。"
            )
    else:
        logger.warning(
            f"opencode-go embedding 接口不可用，自动切换为本地模型 {LOCAL_EMBEDDING_MODEL}。"
        )

    return HuggingFaceEmbeddings(
        model_name=LOCAL_EMBEDDING_MODEL,
        model_kwargs={"local_files_only": True},
    )


_EMBEDDING_CACHE: Optional[object] = None


def get_embeddings():
    """获取（缓存的）embedding 实例。"""
    global _EMBEDDING_CACHE
    if _EMBEDDING_CACHE is None:
        _EMBEDDING_CACHE = create_embeddings()
    return _EMBEDDING_CACHE
