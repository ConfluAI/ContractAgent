"""
集中式模型路由 — 合同审查全链路，通过硅基流动统一调用。

检索链路: Embedding + BM25 → RRF → Reranker → LLM 审查
"""

import os
from typing import Optional
from dotenv import load_dotenv
import httpx
from openai import OpenAI, AsyncOpenAI
from langsmith import wrappers

load_dotenv()

# ── Prompt 版本（改提示词时递增，LangSmith 中按版本对比耗时/Token）───────

PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "v1")

# ── 模型映射 ──────────────────────────────────────────────────────────

MODELS = {
    # 词嵌入：BGE 中文专用，完全免费
    "embedding": "BAAI/bge-large-zh-v1.5",
    # 审查 / QA 生成模型
    "review_llm": "deepseek-ai/DeepSeek-V3",
    # 专用重排序模型（免费），替代 LLM Rerank，延迟 ~100ms
    "rerank": "BAAI/bge-reranker-v2-m3",
}

# ── 客户端（单例，wrap_openai 使 LangSmith 自动采集 LLM Token/耗时）──

_client: Optional[OpenAI] = None
_async_client: Optional[AsyncOpenAI] = None


def get_client() -> OpenAI:
    """同步 OpenAI 客户端 — 阻塞端点使用。"""
    global _client
    if _client is None:
        _client = wrappers.wrap_openai(
            OpenAI(
                api_key=os.environ["SILICONFLOW_API_KEY"],
                base_url=os.environ.get(
                    "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
                ),
            )
        )
    return _client


def get_async_client() -> AsyncOpenAI:
    """异步 OpenAI 客户端 — SSE 流式端点使用。"""
    global _async_client
    if _async_client is None:
        _async_client = wrappers.wrap_openai(
            AsyncOpenAI(
                api_key=os.environ["SILICONFLOW_API_KEY"],
                base_url=os.environ.get(
                    "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
                ),
            )
        )
    return _async_client


def model_name(task: str) -> str:
    return MODELS[task]


_rerank_client: Optional[httpx.Client] = None


def _get_rerank_client() -> httpx.Client:
    """持久化 httpx Client，复用连接池避免每次 TCP+TLS 握手。"""
    global _rerank_client
    if _rerank_client is None:
        _rerank_client = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=10),
        )
    return _rerank_client


def rerank(query: str, documents: list[str], top_n: int | None = None) -> list[dict]:
    """BGE-Reranker 重排序（硅基流动，免费）。

    所有候选文档一次性送进 cross-encoder，按 relevance_score 降序返回。
    复用持久化 httpx.Client 连接池，避免每次 TCP+TLS 握手。

    Args:
        query: 用户问题
        documents: 候选文档文本列表
        top_n: 返回前 N 条（None = 全部返回）

    Returns:
        [{"index": 0, "relevance_score": 0.95}, ...]
    """
    api_key = os.environ["SILICONFLOW_API_KEY"]
    base_url = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")

    body: dict = {
        "model": MODELS["rerank"],
        "query": query,
        "documents": documents,
    }
    if top_n is not None:
        body["top_n"] = top_n

    resp = _get_rerank_client().post(
        f"{base_url}/rerank",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
    )
    resp.raise_for_status()
    return resp.json()["results"]


def warmup_all() -> None:
    """预热所有硅基流动连接池 — 服务启动时调用，消除首次请求的 TCP+TLS 握手延迟。"""
    import logging
    logger = logging.getLogger(__name__)

    # 1. 预热 rerank 连接池（独立 httpx.Client）
    try:
        rerank("warmup", ["预热连接池"], top_n=1)
        logger.info("Rerank 连接池预热完成")
    except Exception as e:
        logger.warning("Rerank 预热失败（不影响正常使用）: %s", e)

    # 2. 预热 Embedding/LLM 连接池（共用 OpenAI 客户端）
    try:
        client = get_client()
        client.embeddings.create(
            model=MODELS["embedding"], input="预热"
        )
        logger.info("Embedding/LLM 连接池预热完成")
    except Exception as e:
        logger.warning("Embedding/LLM 预热失败（不影响正常使用）: %s", e)
