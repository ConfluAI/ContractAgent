"""
LangGraph workflow state — defines the shape of data flowing through the graph.

branch_results 使用 Annotated + 自定义 reducer，
确保 fan-out 并行节点不会互相覆盖。
"""

from __future__ import annotations

from typing import Annotated, TypedDict


def _merge_branch_results(
    left: dict[str, list[dict]], right: dict[str, list[dict]]
) -> dict[str, list[dict]]:
    """Reducer：合并两个分支结果字典，用于 Annotated 类型。"""
    return {**left, **right}


class WorkflowState(TypedDict):
    input: str
    file_path: str
    contract_type: str
    branches: list[str]
    branch_results: Annotated[dict[str, list[dict]], _merge_branch_results]
    retrieval_result: dict
    review_output: str
    error: str
    warnings: list[str]
    rerank: bool
