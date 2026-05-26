"""
集中式模型路由 — 合同审查全链路，通过硅基流动统一调用。

检索链路: Embedding + BM25 → RRF → Reranker → LLM 审查
"""

import os
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ── 模型映射 ──────────────────────────────────────────────────────────

MODELS = {
    # 词嵌入：BGE 中文专用，完全免费
    "embedding": "BAAI/bge-large-zh-v1.5",
    # 合同审查主模型
    "review_llm": "deepseek-ai/DeepSeek-V3",
}

# ── 客户端（单例）─────────────────────────────────────────────────────

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ["SILICONFLOW_API_KEY"],
            base_url=os.environ.get(
                "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
            ),
        )
    return _client


def model_name(task: str) -> str:
    return MODELS[task]
