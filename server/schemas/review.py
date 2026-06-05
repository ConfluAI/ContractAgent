from __future__ import annotations
from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    text: str = Field(..., min_length=1)


class ReviewResponse(BaseModel):
    id: int
    contract_type: str
    branches: list[str]
    review_output: str
    error: str
    warnings: list[str] = []


class StreamReviewRequest(BaseModel):
    text: str = Field(..., min_length=1)
    thread_id: str | None = Field(None, description="多轮对话线程 ID，传入则复用缓存的法律依据")
