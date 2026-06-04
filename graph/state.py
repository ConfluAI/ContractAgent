"""
LangGraph workflow state — defines the shape of data flowing through the graph.

branch_results 使用 Annotated + 自定义 reducer，确保 fan-out 并行节点不会互相覆盖。
warnings 使用 operator.add 累加，任意节点追加 warning 自动合并，无覆盖风险。
"""

from __future__ import annotations

import operator
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
    # ⚠ error 无自定义 reducer。致命错误由 Command(goto=END) 直接终止图，
    # 正常路径中不存在多节点写 error 的场景，约定"先错即停"。
    error: str
    # operator.add：任意节点返回 {"warnings": [...]} 自动追加，无需手动拼接。
    warnings: Annotated[list[str], operator.add]
    # file_path, rerank, conversation_history → configurable（不变输入，不存 checkpoint）
