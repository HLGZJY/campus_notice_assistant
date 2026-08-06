"""LLM 客户端配置：从 ConfigStore 读取任务级模型配置。

M6 改造：
  - 旧版：从 .env 直接读取 OPENCODE_API_KEY / OPENCODE_BASE_URL / LLM_MODEL
  - 新版：统一从 config/store.py 读取，每个任务（extraction/qa/todo）可独立配置模型
  - 保留 LLMConfig / get_llm_config() 作为薄兼容层，默认映射到 extraction 任务

使用方式：
    from utils.llm import get_model_for_task
    api_key, base_url, model = get_model_for_task("extraction")
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from config.store import ConfigStore

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """兼容旧版的 LLM 配置。内部映射到 ConfigStore 的 extraction 任务。"""

    api_key: str
    base_url: str
    model: str

    def validate(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "未配置 API Key。请在项目根目录 .env 中设置对应供应商的环境变量，"
                "并在 config/app.yaml 中正确配置 providers.*.api_key_env。"
            )


def get_model_for_task(task: str) -> tuple[str, str, str]:
    """获取指定任务的 LLM 连接参数。

    Args:
        task: "extraction" | "qa" | "todo" | "embedding"

    Returns:
        (api_key, base_url, model_name)
    """
    store = ConfigStore.get_instance()
    provider, model_name = store.get_model(task)
    api_key = store.get_api_key(provider.name)
    return api_key, provider.base_url, model_name


def get_llm_config() -> LLMConfig:
    """兼容旧版：默认返回 extraction 任务的配置。"""
    api_key, base_url, model = get_model_for_task("extraction")
    return LLMConfig(api_key=api_key, base_url=base_url, model=model)


def get_api_key_for_env(env_var: str) -> Optional[str]:
    """读取指定环境变量名的 API key（兼容 .env 未加载时的兜底）。"""
    value = os.environ.get(env_var, "").strip()
    return value if value else None
