"""
LangGraph workflows — contract review + question answering.

Review graph:
    START → parser → dispatcher ─┬─ civil_retriever ─┬─ merge → reviewer → END
                                  └─ labor_retriever ─┘
                                  (并行, civil 永远执行, labor 按需)

QA graph:
    START → dispatcher ─┬─ civil_retriever ─┬─ merge → qa_responder → END
                         └─ labor_retriever ─┘
                         (并行, QA 模式跳过 LLM Rerank)
"""

from __future__ import annotations

import threading

from langgraph.graph import StateGraph, END

from graph.state import WorkflowState
from graph.parser import parser_node
from graph.dispatcher import dispatcher_node
from graph.reviewer import reviewer_node
from graph.qa_responder import qa_responder_node
from retrieval.retriever import ContractRetriever


_retriever: ContractRetriever | None = None
_retriever_lock = threading.Lock()


def _get_retriever() -> ContractRetriever:
    global _retriever
    if _retriever is None:
        with _retriever_lock:
            if _retriever is None:
                _retriever = ContractRetriever()
    return _retriever


# ── Branch retriever nodes (fan-out from dispatcher, run in parallel) ──

def _civil_retriever_node(state: WorkflowState) -> dict:
    """民事分支 — 永远执行，民法是母法兜底。"""
    r = _get_retriever()
    rerank = state.get("rerank", True)
    result = r.search_branch("civil", state["input"], rerank=rerank)
    return {"civil_result": result}


def _labor_retriever_node(state: WorkflowState) -> dict:
    """劳动分支 — 仅当 dispatcher 指定了 labor 时执行。"""
    if "labor" not in state["branches"]:
        return {"labor_result": []}
    r = _get_retriever()
    rerank = state.get("rerank", True)
    result = r.search_branch("labor", state["input"], rerank=rerank)
    return {"labor_result": result}


def _merge_retrieval_node(state: WorkflowState) -> dict:
    """汇聚并行分支结果 → assembled_text。"""
    civil = state.get("civil_result", [])
    labor = state.get("labor_result", [])
    branches = state["branches"]

    # 按 priority 组装
    from retrieval.retriever import BRANCH_SPEC

    parts = []
    processed = {}

    for name in branches:
        items = civil if name == "civil" else labor
        spec = BRANCH_SPEC[name]
        parts.append("=" * 60)
        parts.append(f"【第{spec['priority']}优先级：{spec['label']}】")
        parts.append(f"（{spec['description']}）")
        parts.append("=" * 60)
        for r in items:
            if r.get("block_text"):
                parts.append(r["block_text"])
            parts.append(
                f">> 总分={r.get('total','?')} "
                f"| {r.get('verdict','')}"
            )
        parts.append("")
        processed[name] = items

    return {
        "retrieval_result": {
            **processed,
            "activated_branches": branches,
            "assembled_text": "\n".join(parts).strip(),
        },
    }


# ── Shared node set ─────────────────────────────────────────────────────

def _build_retrieval_layer(builder: StateGraph) -> None:
    """Add parallel retrieval nodes to a graph builder (shared by both graphs)."""
    builder.add_node("civil_retriever", _civil_retriever_node)
    builder.add_node("labor_retriever", _labor_retriever_node)
    builder.add_node("merge_retrieval", _merge_retrieval_node)

    # dispatcher → fan-out to both branches (LangGraph runs them in parallel)
    builder.add_edge("dispatcher", "civil_retriever")
    builder.add_edge("dispatcher", "labor_retriever")

    # both → merge
    builder.add_edge("civil_retriever", "merge_retrieval")
    builder.add_edge("labor_retriever", "merge_retrieval")


# ── Contract Review Graph ────────────────────────────────────────────────────

_review_graph_builder = StateGraph(WorkflowState)

_review_graph_builder.add_node("parser", parser_node)
_review_graph_builder.add_node("dispatcher", dispatcher_node)
_build_retrieval_layer(_review_graph_builder)
_review_graph_builder.add_node("reviewer", reviewer_node)

_review_graph_builder.add_edge("parser", "dispatcher")
_review_graph_builder.add_edge("merge_retrieval", "reviewer")
_review_graph_builder.add_edge("reviewer", END)
_review_graph_builder.set_entry_point("parser")

_review_graph = _review_graph_builder.compile()


def run_contract_review(user_input: str = "", file_path: str = "") -> dict:
    initial_state: WorkflowState = {
        "input": user_input,
        "file_path": file_path,
        "contract_type": "",
        "branches": [],
        "civil_result": [],
        "labor_result": [],
        "retrieval_result": {},
        "review_output": "",
        "error": "",
        "rerank": True,
    }
    result = _review_graph.invoke(initial_state)
    return result


# ── Question Answering Graph ─────────────────────────────────────────────────

_qa_graph_builder = StateGraph(WorkflowState)

_qa_graph_builder.add_node("dispatcher", dispatcher_node)
_build_retrieval_layer(_qa_graph_builder)
_qa_graph_builder.add_node("qa_responder", qa_responder_node)

_qa_graph_builder.add_edge("merge_retrieval", "qa_responder")
_qa_graph_builder.add_edge("qa_responder", END)
_qa_graph_builder.set_entry_point("dispatcher")

_qa_graph = _qa_graph_builder.compile()


def run_qa(question: str) -> dict:
    initial_state: WorkflowState = {
        "input": question,
        "file_path": "",
        "contract_type": "",
        "branches": [],
        "civil_result": [],
        "labor_result": [],
        "retrieval_result": {},
        "review_output": "",
        "error": "",
        "rerank": True,
    }
    result = _qa_graph.invoke(initial_state)
    return result


# ── CLI entry ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import io
    import argparse
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    ap = argparse.ArgumentParser(description="合同审查智能体")
    ap.add_argument("query", nargs="*", help="合同内容或法律问题")
    ap.add_argument("--file", "-f", help="合同文件路径 (.docx/.pdf)")
    ap.add_argument("--qa", action="store_true", help="法律咨询模式（而非合同审查）")
    cli_args = ap.parse_args()

    query = " ".join(cli_args.query) if cli_args.query else ""
    file_path = cli_args.file or ""

    if not query and not file_path:
        query = input("请输入合同内容或法律问题：\n> ")

    print("\n" + "=" * 60)
    if cli_args.qa:
        print("  合同条款咨询 — ContractAgent")
    else:
        print("  合同审查智能体 — ContractAgent")
    print("=" * 60 + "\n")
    if file_path:
        print(f"解析文件: {file_path}")
    print("正在分析...\n")

    if cli_args.qa:
        result = run_qa(question=query)
    else:
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
