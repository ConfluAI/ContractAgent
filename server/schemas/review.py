from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    text: str = Field(..., min_length=1)


class ReviewResponse(BaseModel):
    id: int
    contract_type: str
    branches: list[str]
    review_output: str
    error: str
