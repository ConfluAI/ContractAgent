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
    """Reducer：合并分支结果。空字典 {} 视为清空信号，用于 merge 后释放内存。"""
    if not right:
        return {}
    return {**left, **right}


class WorkflowState(TypedDict):
    input: str
    contract_type: str
    branches: list[str]
    branch_results: Annotated[dict[str, list[dict]], _merge_branch_results]
    retrieval_result: dict
    review_output: str
    error: str
    warnings: list[str]
    # file_path, rerank, conversation_history → configurable（不变输入，不存 checkpoint）
