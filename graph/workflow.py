"""
LangGraph workflows — contract review + question answering.

图结构从 BRANCH_SPEC 自动生成。新增分支只需在 BRANCH_SPEC + dispatcher 加配置，
无需修改此文件。

Error routing:
  - dispatcher / merge 出错 → 条件边跳 END（致命）
  - retriever 出错 → 降级返回空列表，不中断图（非致命）

Review graph:
    START → parser → dispatcher ─┬─ {branch}_retriever* ─┬─ merge → reviewer → END
                    ↓ (error)     └─ ... ────────────────┘    ↓ (error)
                   END                                        END

QA graph:
    START → dispatcher ─┬─ {branch}_retriever* ─┬─ merge → qa_responder → END
               ↓ (error)└─ ... ────────────────┘    ↓ (error)
              END                                    END
"""

from __future__ import annotations

import threading

from langgraph.graph import StateGraph, END

from graph.state import WorkflowState
from graph.parser import parser_node
from graph.dispatcher import dispatcher_node
from graph.reviewer import reviewer_node
from graph.qa_responder import qa_responder_node
from retrieval.retriever import ContractRetriever, BRANCH_SPEC


_retriever: ContractRetriever | None = None
_retriever_lock = threading.Lock()


def _get_retriever() -> ContractRetriever:
    global _retriever
    if _retriever is None:
        with _retriever_lock:
            if _retriever is None:
                _retriever = ContractRetriever()
    return _retriever


# ── Retriever node factory (generated from BRANCH_SPEC) ──────────────────

def _make_retriever_node(branch_name: str):
    """工厂函数：为指定分支生成检索节点。
    节点名 = "{branch_name}_retriever"，由 _build_retrieval_layer 注册。
    """
    def _node(state: WorkflowState) -> dict:
        if branch_name not in state["branches"]:
            return {"branch_results": {branch_name: []}}
        try:
            r = _get_retriever()
            rerank = state.get("rerank", True)
            result = r.search_branch(branch_name, state["input"], rerank=rerank)
            return {"branch_results": {branch_name: result}}
        except Exception:
            return {"branch_results": {branch_name: []}}
    return _node


def _merge_retrieval_node(state: WorkflowState) -> dict:
    """汇聚所有分支结果 → assembled_text + 非致命警告。"""
    from retrieval.retriever import assemble_branch_results

    try:
        results = dict(state.get("branch_results", {}))
        branches = state.get("branches", [])

        # 非致命警告：某分支应激活但无结果
        warnings: list[str] = []
        for bn in branches:
            items = results.get(bn, [])
            if not items:
                label = BRANCH_SPEC.get(bn, {}).get("label", bn)
                warnings.append(f"⚠ {label}检索未返回结果")

        rv = {"retrieval_result": assemble_branch_results(results, branches)}
        if warnings:
            rv["warnings"] = warnings
        return rv
    except Exception as e:
        return {"error": f"[检索汇聚] {e}"}


# ── Error routing ────────────────────────────────────────────────────────

def _route_from_dispatcher(state: WorkflowState) -> str | list[str]:
    """致命错误 → END；正常 → fan-out 到所有激活分支的检索节点。"""
    if state.get("error"):
        return END
    return [f"{b}_retriever" for b in state["branches"]]


def _route_from_merge(state: WorkflowState) -> str:
    """致命错误 → END。"""
    if state.get("error"):
        return END
    return "continue"


# ── Shared retrieval layer (node names from BRANCH_SPEC) ─────────────────

def _build_retrieval_layer(builder: StateGraph) -> None:
    """从 BRANCH_SPEC 自动生成 retriever 节点 + 边。新增分支零改动。"""
    builder.add_node("merge_retrieval", _merge_retrieval_node)

    route_map: dict[str, str] = {END: END}
    for branch_name in BRANCH_SPEC:
        node_name = f"{branch_name}_retriever"
        builder.add_node(node_name, _make_retriever_node(branch_name))
        builder.add_edge(node_name, "merge_retrieval")
        route_map[node_name] = node_name

    # dispatcher → fan-out（动态路由到激活分支）/ END
    builder.add_conditional_edges("dispatcher", _route_from_dispatcher, route_map)


# ── Contract Review Graph ────────────────────────────────────────────────

_review_graph_builder = StateGraph(WorkflowState)

_review_graph_builder.add_node("parser", parser_node)
_review_graph_builder.add_node("dispatcher", dispatcher_node)
_build_retrieval_layer(_review_graph_builder)
_review_graph_builder.add_node("reviewer", reviewer_node)

_review_graph_builder.add_edge("parser", "dispatcher")
_review_graph_builder.add_conditional_edges("merge_retrieval", _route_from_merge, {
    "continue": "reviewer",
    END: END,
})
_review_graph_builder.add_edge("reviewer", END)
_review_graph_builder.set_entry_point("parser")

_review_graph = _review_graph_builder.compile()


def _make_initial_state(user_input: str = "", file_path: str = "") -> WorkflowState:
    return {
        "input": user_input,
        "file_path": file_path,
        "contract_type": "",
        "branches": [],
        "branch_results": {},
        "retrieval_result": {},
        "review_output": "",
        "error": "",
        "warnings": [],
        "rerank": True,
    }


def _make_error_return(err_msg: str, **extra) -> dict:
    return {
        "contract_type": "",
        "branches": [],
        "branch_results": {},
        "retrieval_result": {},
        "review_output": "",
        "error": err_msg,
        "warnings": [],
        "rerank": True,
        **extra,
    }


def run_contract_review(user_input: str = "", file_path: str = "") -> dict:
    initial_state = _make_initial_state(user_input, file_path)
    try:
        result = _review_graph.invoke(initial_state)
    except Exception as e:
        return _make_error_return(
            f"审查工作流异常: {e}",
            input=user_input, file_path=file_path,
        )
    return result


# ── Question Answering Graph ─────────────────────────────────────────────

_qa_graph_builder = StateGraph(WorkflowState)

_qa_graph_builder.add_node("dispatcher", dispatcher_node)
_build_retrieval_layer(_qa_graph_builder)
_qa_graph_builder.add_node("qa_responder", qa_responder_node)

_qa_graph_builder.add_conditional_edges("merge_retrieval", _route_from_merge, {
    "continue": "qa_responder",
    END: END,
})
_qa_graph_builder.add_edge("qa_responder", END)
_qa_graph_builder.set_entry_point("dispatcher")

_qa_graph = _qa_graph_builder.compile()


def run_qa(question: str) -> dict:
    initial_state = _make_initial_state(question, "")
    try:
        result = _qa_graph.invoke(initial_state)
    except Exception as e:
        return _make_error_return(
            f"咨询工作流异常: {e}",
            input=question, file_path="",
        )
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
