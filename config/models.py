"""
集中式模型路由 — 合同审查全链路，通过硅基流动统一调用。

所有 API 调用（Embedding / LLM / Rerank）共用同一个 httpx Client，单连接池。
"""

from __future__ import annotations
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
    # 专用重排序模型（免费），替代 LLM Rerank，延迟 ~150ms
    "rerank": "BAAI/bge-reranker-v2-m3",
}

# ── 共享 httpx Client（Embedding + LLM + Rerank 共用一个连接池）────────

_http_client: Optional[httpx.Client] = None


def _get_http_client() -> httpx.Client:
    """持久化 httpx Client 单例 — 所有硅基流动 API 共用连接池。"""
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=10),
        )
    return _http_client


# ── 客户端（单例，wrap_openai 使 LangSmith 自动采集 LLM Token/耗时）──

_client: Optional[OpenAI] = None
_async_client: Optional[AsyncOpenAI] = None


def get_client() -> OpenAI:
    """同步 OpenAI 客户端 — 阻塞端点 / 检索使用。"""
    global _client
    if _client is None:
        _client = wrappers.wrap_openai(
            OpenAI(
                api_key=os.environ["SILICONFLOW_API_KEY"],
                base_url=os.environ.get(
                    "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
                ),
                http_client=_get_http_client(),
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


# ── Rerank API（复用共享 httpx Client 的连接池）───────────────────────


def rerank(query: str, documents: list[str], top_n: int | None = None) -> list[dict]:
    """BGE-Reranker 重排序（硅基流动，免费）。

    所有候选文档一次性送进 cross-encoder，按 relevance_score 降序返回。
    与 Embedding/LLM 共用同一个 httpx Client 连接池。

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

    resp = _get_http_client().post(
        f"{base_url}/rerank",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
    )
    resp.raise_for_status()
    return resp.json()["results"]


# ── 预热 ──────────────────────────────────────────────────────────────


def warmup_all() -> None:
    """预热所有硅基流动连接 — 服务启动时调用，消除首次请求的 TCP+TLS 握手。

    Embedding / LLM / Rerank 共用同一个 httpx Client 连接池，
    调一次 embedding 即可建好所有连接。
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        client = get_client()
        client.embeddings.create(model=MODELS["embedding"], input="预热")
        logger.info("硅基流动连接池预热完成（Embedding + LLM + Rerank）")
    except Exception as e:
        logger.warning("硅基流动预热失败（不影响正常使用）: %s", e)
