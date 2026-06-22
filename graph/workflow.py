"""
LangGraph workflows — contract review + question answering.

两个图，各自支持 ainvoke（阻塞）和 astream(stream_mode="custom")（流式）。

图结构从 BRANCH_SPEC 自动生成。新增分支只需在 BRANCH_SPEC + dispatcher 加配置。

Error routing（三类错误，三种处理）:
  非致命 — retriever 检索空结果 → 节点内 catch，降级返回 [] + warning，图继续
  可恢复 — LLM 超时/限流/连接中断 → 不 catch，向上抛，LangGraph checkpoint 保存后可重试
  真致命 — 模型配置错/API Key 无效 → 节点内 catch BadRequestError/AuthenticationError → END

Review graph:
    START → parser → dispatcher ─┬─ {branch}_retriever* ─┬─ merge → reviewer → END
                    ↓ (error)     └─ ... ────────────────┘    ↓ (error)
                   END                                        END

QA graph:
    START → dispatcher ─┬─ {branch}_retriever* ─┬─ merge → qa_responder → END
               ↓ (error)└─ ... ────────────────┘    ↓ (error)
              END                                    END

用法:
  阻塞: result = await run_contract_review(user_input="...", file_path="...")
  流式: async for mode, data in _review_graph.astream(state, stream_mode="custom"):
            yield data["token"]
"""

from __future__ import annotations

import asyncio
import threading
import uuid
import logging

import openai
from openai import (
    BadRequestError, AuthenticationError,
    APITimeoutError, RateLimitError, APIConnectionError, InternalServerError,
)
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, RetryPolicy
from langchain_core.runnables import RunnableConfig

from graph.state import WorkflowState
from graph.parser import parser_node
from graph.dispatcher import dispatcher_node
from graph.reviewer import reviewer_node
from graph.map_reviewer import map_reviewer_node
from graph.reduce_reviewer import reduce_reviewer_node
from graph.qa_responder import qa_responder_node
from retrieval.retriever import ContractRetriever, BRANCH_SPEC
from config.models import PROMPT_VERSION

# ── Checkpointer（惰性初始化，由 server startup 触发）─────────────────

_checkpointer: "AsyncPostgresSaver | MemorySaver" = MemorySaver()  # 默认内存，init 后切换
_checkpointer_ctx = None  # PostgresSaver 的 context manager
_review_graph = None
_qa_graph = None

# ── 重试配置 ────────────────────────────────────────────────────────────

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0

# ── RetryPolicy 配置（节点级重试，由 LangGraph 框架执行）─────────────────

# 可恢复的 OpenAI 异常 — 网络闪断 / 限流 / 服务端 5xx → 重试
_RETRY_ON_LLM = (
    APITimeoutError, RateLimitError, APIConnectionError, InternalServerError,
)
# dispatcher 额外重试 ValueError — LLM 返回非 JSON 时换一次输出可能成功
_RETRY_ON_DISPATCHER = (*_RETRY_ON_LLM, ValueError)

logger = logging.getLogger(__name__)


async def _ainvoke_with_retry(
    graph, initial_state: dict, thread_id: str | None,
    max_retries: int = _MAX_RETRIES,
    configurable: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    """带 checkpoint 重试的异步图调用。

    只有节点内部不 catch 的可恢复异常（Timeout / RateLimit 等）才会
    从 graph.ainvoke() 向上抛，触发此处的重试。

    configurable 可携带不变配置（file_path, rerank 等），
    注入 config["configurable"] 供节点通过 get_config() 读取。
    """
    if thread_id is None:
        thread_id = str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": thread_id, **(configurable or {})},
    }
    # 注入 LangSmith 元数据（prompt 版本、图类型）
    if metadata:
        config["metadata"] = metadata

    for attempt in range(1, max_retries + 1):
        try:
            return await graph.ainvoke(initial_state, config)
        except Exception:
            if attempt == max_retries:
                logger.error(
                    f"图调用 {max_retries} 次全部失败 (thread={thread_id})"
                )
                raise
            delay = min(_RETRY_BASE_DELAY ** attempt, 10)
            logger.warning(
                f"图调用失败 (attempt={attempt}/{max_retries}, thread={thread_id}), "
                f"{delay:.0f}s 后重试..."
            )
            await asyncio.sleep(delay)

    raise RuntimeError("unreachable")


# ── Retriever 单例 ──────────────────────────────────────────────────────

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

    错误处理：
      - BadRequestError / AuthenticationError → 降级返回空（重试无意义）
      - Timeout / RateLimit / ConnectionError / 5xx → 向上抛，checkpoint 恢复
      - Chroma / 桥接等本地异常 → 降级返回空（重试修不好）
    """
    def _node(state: WorkflowState, config: RunnableConfig) -> dict:
        if branch_name not in state["branches"]:
            logger.warning("分支 [%s] 不在 branches=%s 中，跳过", branch_name, state["branches"])
            return {"branch_results": {branch_name: []}}
        try:
            r = _get_retriever()
            rerank = config.get("configurable", {}).get("rerank", True)
            logger.info("分支 [%s] 开始检索, query=%.80s, rerank=%s", branch_name, state["input"], rerank)
            result = r.search_branch(branch_name, state["input"], rerank=rerank)
            logger.info("分支 [%s] 检索完成, 返回 %d 条", branch_name, len(result))
            return {"branch_results": {branch_name: result}}
        except (BadRequestError, AuthenticationError) as e:
            logger.warning("分支 [%s] 模型配置异常，降级返回空: %s", branch_name, e)
            return {"branch_results": {branch_name: []}}
        except openai.APIError:
            raise
        except Exception as e:
            logger.warning("分支 [%s] 检索异常，降级返回空: %s", branch_name, e)
            return {"branch_results": {branch_name: []}}
    return _node


def _merge_retrieval_node(state: WorkflowState) -> dict:
    """汇聚所有分支结果 → assembled_text + 非致命警告。"""
    from retrieval.retriever import assemble_branch_results

    try:
        results = dict(state.get("branch_results", {}))
        branches = state.get("branches", [])

        logger.info("merge 节点: 收到 branch_results keys=%s, branches=%s",
                     list(results.keys()), branches)

        warnings: list[str] = []
        for bn in branches:
            items = results.get(bn, [])
            if not items:
                label = BRANCH_SPEC.get(bn, {}).get("label", bn)
                warnings.append(f"⚠ {label}检索未返回结果")

        rv: dict = {
            "retrieval_result": assemble_branch_results(results, branches),
            "branch_results": {},   # 清空原始检索结果，下游不需要，仅 checkpoint 有用
        }
        logger.info("merge 节点返回: assembled_text=%d字, civil=%d条, labor=%d条",
                     len(rv["retrieval_result"].get("assembled_text", "")),
                     len(rv["retrieval_result"].get("civil", [])),
                     len(rv["retrieval_result"].get("labor", [])))
        if warnings:
            rv["warnings"] = warnings
        return rv
    except Exception as e:
        return Command(goto=END, update={"error": f"[检索汇聚] {e}"})


# ── Error routing ────────────────────────────────────────────────────────

def _route_from_dispatcher(state: WorkflowState) -> str | list[str]:
    # fatal error 由 Command(goto=END) 处理，不会走到此路由函数
    return [f"{b}_retriever" for b in state["branches"]]


def _route_from_merge(state: WorkflowState) -> str:
    # 正常路径：fatal error 由 Command(goto=END) 处理。
    # 此检查为防御性：若未来有人直接 return {"error": ...} 而未用 Command，仍能终止。
    if state.get("error"):
        return END
    # 有条款切分结果 → 走逐条审查 + 汇总报告
    if state.get("clauses"):
        return "map_review"
    # 无条款（文本输入模式）→ 走旧单次审查
    return "single_review"


# ── Shared retrieval layer ───────────────────────────────────────────────

def _build_retrieval_layer(builder: StateGraph) -> None:
    """从 BRANCH_SPEC 自动生成 retriever 节点 + 边。新增分支零改动。"""
    builder.add_node("merge_retrieval", _merge_retrieval_node)

    route_map: dict[str, str] = {END: END}
    for branch_name in BRANCH_SPEC:
        node_name = f"{branch_name}_retriever"
        builder.add_node(
            node_name, _make_retriever_node(branch_name),
            retry_policy=RetryPolicy(retry_on=_RETRY_ON_LLM, max_attempts=3),
        )
        builder.add_edge(node_name, "merge_retrieval")
        route_map[node_name] = node_name

    builder.add_conditional_edges("dispatcher", _route_from_dispatcher, route_map)


# ── Contract Review Graph ────────────────────────────────────────────────

_review_graph_builder = StateGraph(WorkflowState)

_review_graph_builder.add_node("parser", parser_node)
_review_graph_builder.add_node(
    "dispatcher", dispatcher_node,
    retry_policy=RetryPolicy(retry_on=_RETRY_ON_DISPATCHER, max_attempts=3),
)
_build_retrieval_layer(_review_graph_builder)
_review_graph_builder.add_node(
    "map_reviewer", map_reviewer_node,
    retry_policy=RetryPolicy(retry_on=_RETRY_ON_LLM, max_attempts=3),
)
_review_graph_builder.add_node(
    "reduce_reviewer", reduce_reviewer_node,
    retry_policy=RetryPolicy(retry_on=_RETRY_ON_LLM, max_attempts=3),
)
_review_graph_builder.add_node("reviewer", reviewer_node)

_review_graph_builder.add_edge("parser", "dispatcher")
_review_graph_builder.add_conditional_edges("merge_retrieval", _route_from_merge, {
    "map_review": "map_reviewer",
    "single_review": "reviewer",
    END: END,
})
_review_graph_builder.add_edge("map_reviewer", "reduce_reviewer")
_review_graph_builder.add_edge("reduce_reviewer", END)
_review_graph_builder.add_edge("reviewer", END)
_review_graph_builder.set_entry_point("parser")


# ── Question Answering Graph ─────────────────────────────────────────────

_qa_graph_builder = StateGraph(WorkflowState)

_qa_graph_builder.add_node(
    "dispatcher", dispatcher_node,
    retry_policy=RetryPolicy(retry_on=_RETRY_ON_DISPATCHER, max_attempts=3),
)
_build_retrieval_layer(_qa_graph_builder)
_qa_graph_builder.add_node("qa_responder", qa_responder_node)

_qa_graph_builder.add_conditional_edges("merge_retrieval", _route_from_merge, {
    "continue": "qa_responder",
    END: END,
})
_qa_graph_builder.add_edge("qa_responder", END)
_qa_graph_builder.set_entry_point("dispatcher")


# ── Lazy compilation ─────────────────────────────────────────────────────

def _compile_graphs() -> None:
    """用当前 checkpointer 编译两个图（init_checkpointer 时调用）。"""
    global _review_graph, _qa_graph
    _review_graph = _review_graph_builder.compile(checkpointer=_checkpointer)
    _qa_graph = _qa_graph_builder.compile(checkpointer=_checkpointer)


async def init_checkpointer(postgres_url: str) -> None:
    """初始化 PostgresSaver 并重新编译图。服务器启动时调用。"""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    global _checkpointer, _checkpointer_ctx
    _checkpointer_ctx = AsyncPostgresSaver.from_conn_string(postgres_url)
    _checkpointer = await _checkpointer_ctx.__aenter__()
    await _checkpointer.setup()
    _compile_graphs()
    logger.info("PostgresSaver 初始化完成，图已重新编译")


async def close_checkpointer() -> None:
    """关闭 PostgresSaver 连接。服务器关闭时调用。"""
    global _checkpointer_ctx, _checkpointer
    if _checkpointer_ctx:
        await _checkpointer_ctx.__aexit__(None, None, None)
        _checkpointer_ctx = None
    _checkpointer = MemorySaver()
    logger.info("PostgresSaver 已关闭")


def get_review_graph():
    """获取审查图（惰性编译保障）。"""
    if _review_graph is None:
        _compile_graphs()
    return _review_graph


def get_qa_graph():
    """获取 QA 图（惰性编译保障）。"""
    if _qa_graph is None:
        _compile_graphs()
    return _qa_graph


# ── State helpers ────────────────────────────────────────────────────────

def _make_initial_state(user_input: str = "") -> WorkflowState:
    return {
        "input": user_input,
        "file_path": "",
        "contract_name": "",
        "clauses": [],
        "clause_reviews": [],
        "contract_type": "",
        "branches": [],
        "branch_results": {},
        "retrieval_result": {},
        "review_output": "",
        "error": "",
        "warnings": [],
    }


# ── 公共入口 ────────────────────────────────────────────────────────────

async def run_contract_review(
    user_input: str = "", file_path: str = "",
    thread_id: str | None = None, max_retries: int = _MAX_RETRIES,
) -> dict:
    """运行合同审查工作流（阻塞）。"""
    initial_state = _make_initial_state(user_input)
    return await _ainvoke_with_retry(
        get_review_graph(), initial_state, thread_id, max_retries,
        configurable={"file_path": file_path, "rerank": True},
        metadata={"prompt_version": PROMPT_VERSION, "graph": "review"},
    )


async def run_qa(
    question: str = "", thread_id: str | None = None,
    max_retries: int = _MAX_RETRIES,
) -> dict:
    """运行 QA 工作流（阻塞）。"""
    initial_state = _make_initial_state(question)
    return await _ainvoke_with_retry(
        get_qa_graph(), initial_state, thread_id, max_retries,
        configurable={"rerank": True},
        metadata={"prompt_version": PROMPT_VERSION, "graph": "qa"},
    )


def build_review_state(
    user_input: str = "", file_path: str = "", thread_id: str | None = None,
) -> tuple:
    """构建审查初始状态和 config，供流式端点使用。"""
    state = _make_initial_state(user_input)
    if thread_id is None:
        thread_id = str(uuid.uuid4())
    config = {
        "configurable": {
            "thread_id": thread_id,
            "file_path": file_path,
            "rerank": True,
        },
        "metadata": {"prompt_version": PROMPT_VERSION, "graph": "review"},
    }
    return state, config, thread_id


def build_qa_state(
    question: str = "", thread_id: str | None = None,
) -> tuple:
    """构建 QA 初始状态和 config，供流式端点使用。"""
    state = _make_initial_state(question)
    if thread_id is None:
        thread_id = str(uuid.uuid4())
    config = {
        "configurable": {
            "thread_id": thread_id,
            "rerank": True,
        },
        "metadata": {"prompt_version": PROMPT_VERSION, "graph": "qa"},
    }
    return state, config, thread_id


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

    async def main():
        if cli_args.qa:
            result = await run_qa(question=query)
        else:
            result = await run_contract_review(user_input=query, file_path=file_path)

        if result.get("error"):
            print(f"[错误] {result['error']}")
        else:
            print(f"合同类型: {result['contract_type']}")
            print(f"检索分支: {', '.join(result['branches'])}")
            print()
            print("-" * 60)
            print(result["review_output"])
            print("-" * 60)

    asyncio.run(main())
