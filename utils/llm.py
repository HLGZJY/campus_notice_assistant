"""LLM 客户端：opencode-go（OpenAI 兼容接口）。

配置来自 .env：
    OPENCODE_API_KEY / OPENCODE_BASE_URL / LLM_MODEL
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL = "kimi-k2.7-code"


class LLMConfig:
    """LLM 配置。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("OPENCODE_API_KEY", "").strip()
        self.base_url = (base_url or os.environ.get("OPENCODE_BASE_URL", DEFAULT_BASE_URL)).strip()
        self.model = (model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)).strip()

    def validate(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "未配置 OPENCODE_API_KEY，请在项目根目录的 .env 文件中填写 "
                "（参考 .env.example）"
            )


def get_llm_config() -> LLMConfig:
    """加载并校验 LLM 配置。"""
    config = LLMConfig()
    config.validate()
    return config
