"""
LangGraph workflow — contract review pipeline.

Graph topology:
    START → parser → dispatcher → retriever → reviewer → END

The parser converts docx/pdf files to plain text (pass-through if no file).
The dispatcher classifies the contract type and sets branches.
The retriever executes multi-branch parallel retrieval (existing RAG).
The reviewer produces a structured legal review against the retrieved basis.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from graph.state import WorkflowState
from graph.parser import parser_node
from graph.dispatcher import dispatcher_node
from graph.reviewer import reviewer_node
from retrieval.retriever import ContractRetriever


_retriever: ContractRetriever | None = None


def _get_retriever() -> ContractRetriever:
    global _retriever
    if _retriever is None:
        _retriever = ContractRetriever()
    return _retriever


def _retriever_node(state: WorkflowState) -> dict:
    result = _get_retriever().search(
        query=state["input"],
        branches=state["branches"],
    )
    return {"retrieval_result": result}


def _build_graph() -> StateGraph:
    builder = StateGraph(WorkflowState)

    builder.add_node("parser", parser_node)
    builder.add_node("dispatcher", dispatcher_node)
    builder.add_node("retriever", _retriever_node)
    builder.add_node("reviewer", reviewer_node)

    builder.set_entry_point("parser")
    builder.add_edge("parser", "dispatcher")
    builder.add_edge("dispatcher", "retriever")
    builder.add_edge("retriever", "reviewer")
    builder.add_edge("reviewer", END)

    return builder


_graph = _build_graph().compile()


def run_contract_review(user_input: str = "", file_path: str = "") -> dict:
    """Run the full contract review pipeline.

    Args:
        user_input: Contract text or review questions. If empty, provide file_path instead.
        file_path: Path to a .docx or .pdf contract file. Parsed into input automatically.

    Returns:
        dict with contract_type, branches, retrieval_result, and review_output
    """
    initial_state: WorkflowState = {
        "input": user_input,
        "file_path": file_path,
        "contract_type": "",
        "branches": [],
        "retrieval_result": {},
        "review_output": "",
        "error": "",
    }
    result = _graph.invoke(initial_state)
    return result


# ── CLI entry ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import argparse

    ap = argparse.ArgumentParser(description="合同审查智能体")
    ap.add_argument("query", nargs="*", help="合同内容或法律问题")
    ap.add_argument("--file", "-f", help="合同文件路径 (.docx/.pdf)")
    cli_args = ap.parse_args()

    query = " ".join(cli_args.query) if cli_args.query else ""
    file_path = cli_args.file or ""

    if not query and not file_path:
        query = input("请输入合同内容或法律问题：\n> ")

    print("\n" + "=" * 60)
    print("  合同审查智能体 — ContractAgent")
    print("=" * 60 + "\n")
    if file_path:
        print(f"解析文件: {file_path}")
    print("正在分析...\n")

    result = run_contract_review(user_input=query, file_path=file_path)

    if result.get("error"):
        print(f"[错误] {result['error']}")
    else:
        print(f"合同类型: {result['contract_type']}")
        print(f"检索分支: {', '.join(result['branches'])}")
        print()
        print("-" * 60)
        print(result["review_output"])
        print("-" * 60)
