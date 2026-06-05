from __future__ import annotations
from datetime import datetime

from pydantic import BaseModel


class HistoryItem(BaseModel):
    id: int
    query_input: str
    contract_type: str | None
    review_output: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class HistoryListResponse(BaseModel):
    items: list[HistoryItem]
    total: int
