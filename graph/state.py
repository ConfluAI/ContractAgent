"""
LangGraph workflow state — defines the shape of data flowing through the graph.
"""

from __future__ import annotations

from typing import TypedDict


class WorkflowState(TypedDict):
    input: str
    file_path: str
    contract_type: str
    branches: list[str]
    civil_result: list[dict]
    labor_result: list[dict]
    retrieval_result: dict
    review_output: str
    error: str
    rerank: bool             
