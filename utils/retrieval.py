"""
SiliconFlow Embeddings — OpenAI 兼容接口，调用 BAAI/bge-large-zh-v1.5（免费）。
"""

from typing import List
from langchain_core.embeddings import Embeddings
from config.models import get_client, model_name


class SiliconFlowEmbeddings(Embeddings):
    """通过硅基流动 OpenAI 兼容接口调用 BGE 中文嵌入模型。"""

    _BATCH_SIZE = 32  # API 每批最多 32 条
    _MAX_CHARS = 500  # BGE 限制 512 tokens，中文约 1 char/token

    def __init__(self) -> None:
        self._client = get_client()
        self._model = model_name("embedding")

    def _truncate(self, text: str) -> str:
        if len(text) <= self._MAX_CHARS:
            return text
        return text[: self._MAX_CHARS]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        truncated = [self._truncate(t) for t in texts]
        all_embeddings: List[List[float]] = []
        for i in range(0, len(truncated), self._BATCH_SIZE):
            batch = truncated[i : i + self._BATCH_SIZE]
            resp = self._client.embeddings.create(model=self._model, input=batch)
            sorted_data = sorted(resp.data, key=lambda d: d.index)
            all_embeddings.extend(d.embedding for d in sorted_data)
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        resp = self._client.embeddings.create(
            model=self._model, input=self._truncate(text)
        )
        return resp.data[0].embedding
