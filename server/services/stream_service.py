"""
SSE 流式服务 — 统一使用图的 astream(stream_mode=["custom", "updates"])。

流程:
  1. 如果有 thread_id → 加载对话历史（注入 initial_state 供 LLM 上下文）
  2. 调用 _review_graph.astream / _qa_graph.astream
     - "updates" 事件 → 检测 merge_retrieval 完成 → 发送 retrieval_done
     - "custom" 事件 → writer 推送的 token → 逐 token SSE
  3. 图完成后持久化消息到对话线程
"""

import asyncio
import json
import logging
import re
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from graph.workflow import (
    get_review_graph, get_qa_graph,
    build_review_state, build_qa_state, _make_initial_state,
)
from server.services.history_service import create_history
from server.services import conversation_service as conv_svc
from server.services import thread_cache

logger = logging.getLogger(__name__)


def _extract_conclusion(text: str) -> str:
    """从审查报告中提取'直接结论'部分，减少注入 LLM 上下文的 token。"""
    m = re.search(r"一、直接结论\s*\n?(.*?)(?=二、|\Z)", text, re.DOTALL)
    if m:
        return m.group(1).strip()[:300]
    return text[:200].strip()


def _trim_history(messages: list[dict]) -> list[dict]:
    """压缩对话历史：用户消息保留原文，助手消息只保留直接结论。"""
    trimmed = []
    for msg in messages:
        if msg["role"] == "assistant":
            trimmed.append({"role": "assistant", "content": _extract_conclusion(msg["content"])})
        else:
            trimmed.append(msg)
    return trimmed


async def _load_history(
    thread_id: str, db: AsyncSession, user_id: int
) -> tuple:
    """加载线程的对话历史。"""
    thread = await conv_svc.get_thread(db, thread_id, user_id)
    if thread is None:
        return [], None, []
    messages = await thread_cache.get_cached_messages(thread_id, db)
    raw = [{"role": m["role"], "content": m["content"]} for m in messages]
    history = _trim_history(raw)
    return history, thread, json.loads(thread.branches or "[]")


# ── 流式重试配置（与 graph/workflow.py 的 _ainvoke_with_retry 对等）──────

_STREAM_MAX_RETRIES = 3
_STREAM_RETRY_BASE_DELAY = 2.0


async def _stream_graph(
    graph, state: dict, config: dict,
) -> AsyncGenerator[dict, None]:
    """通用的图流式包装器——带重试的 astream → SSE 事件转换。

    与 _ainvoke_with_retry 对等：可恢复异常（Timeout / RateLimit / ConnectionError
    等 openai.APIError 子类）触发重试，复用同一 thread_id → LangGraph checkpoint
    自动跳过已完成节点，不重复检索。

    Yields:
      {"event": "retrieval_done", "data": {...}}
      {"event": "token", "data": {"token": "..."}}
      {"event": "retry", "data": {"attempt": N, "max_retries": M}}   ← 重试信号
      {"event": "done", "data": {...}}
    """
    retrieval_done = False
    final_state = None

    for attempt in range(1, _STREAM_MAX_RETRIES + 1):
        try:
            async for mode, data in graph.astream(
                state, config, stream_mode=["custom", "updates"]
            ):
                if mode == "updates":
                    final_state = data
                    if not retrieval_done and "merge_retrieval" in data:
                        retrieval_done = True
                        merge_data = data["merge_retrieval"]
                        yield {
                            "event": "retrieval_done",
                            "data": {
                                "contract_type": state.get("contract_type", ""),
                                "branches": state.get("branches", []),
                                "warnings": merge_data.get("warnings", []),
                            },
                        }
                elif mode == "custom":
                    yield {"event": "token", "data": data}

            # ── async for 正常耗尽 → 图执行成功 ──
            break

        except Exception as e:
            if attempt == _STREAM_MAX_RETRIES:
                logger.error(
                    f"图流式 {_STREAM_MAX_RETRIES} 次全部失败 "
                    f"(thread={config['configurable']['thread_id']}): {e}"
                )
                yield {
                    "event": "done",
                    "data": {
                        "id": None,
                        "thread_id": config["configurable"]["thread_id"],
                        "full_output": "",
                        "error": str(e),
                    },
                }
                return

            delay = min(_STREAM_RETRY_BASE_DELAY ** attempt, 10)
            logger.warning(
                f"图流式失败 (attempt={attempt}/{_STREAM_MAX_RETRIES}, "
                f"thread={config['configurable']['thread_id']}): {e}, "
                f"{delay:.0f}s 后重试..."
            )
            await asyncio.sleep(delay)
            yield {
                "event": "retry",
                "data": {
                    "attempt": attempt + 1,
                    "max_retries": _STREAM_MAX_RETRIES,
                },
            }

    # ── 图正常结束 ──
    # PostgresSaver 保留 checkpoint（7 天 TTL 由定时清理任务处理，见 CHECKPOINT_RETENTION_DAYS）
    thread_id = config["configurable"]["thread_id"]

    error_msg = ""
    if isinstance(final_state, dict):
        for node_name, node_data in final_state.items():
            if node_data.get("error"):
                error_msg = node_data["error"]
                break

    yield {
        "event": "done",
        "data": {
            "id": None,
            "thread_id": thread_id,
            "full_output": "",
            "error": error_msg,
            "_final_state": final_state,
        },
    }


async def stream_review(
    user_input: str = "",
    file_path: str = "",
    user_id: int | None = None,
    db: AsyncSession | None = None,
    thread_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    """合同审查 SSE 事件生成器。"""

    # 加载对话历史
    conversation_history, thread, _ = await _load_history(
        thread_id, db, user_id
    ) if thread_id and db and user_id else ([], None, [])

    state, config, actual_thread_id = build_review_state(user_input, file_path, thread_id)

    # 对话历史注入 configurable（不进 checkpoint），reviewer 通过 get_config() 读取
    if conversation_history:
        config["configurable"]["conversation_history"] = conversation_history

    # 流式执行图
    full_text = ""
    retrieval_info = {}
    async for event in _stream_graph(get_review_graph(), state, config):
        if event["event"] == "retrieval_done":
            retrieval_info = event["data"]
            yield event
        elif event["event"] == "retry":
            full_text = ""  # 清空旧 token，LLM 重试会重新产出
            yield event
        elif event["event"] == "token":
            full_text += event["data"].get("token", "")
            yield event
        elif event["event"] == "done":
            error_msg = event["data"].get("error", "")
            if error_msg:
                yield event
                return

            # ── 持久化 ──
            contract_type = retrieval_info.get("contract_type", "")
            branches = retrieval_info.get("branches", [])
            history_id = None

            if db is not None and user_id is not None:
                try:
                    h = await create_history(
                        db, user_id=user_id,
                        query_input=user_input or f"[文件上传] {file_path}",
                        contract_type=contract_type, review_output=full_text,
                    )
                    history_id = h.id
                except Exception as e:
                    logger.error(f"保存历史记录失败: {e}")

                try:
                    if thread is None:
                        thread = await conv_svc.create_thread(
                            db, user_id=user_id, input_text=user_input,
                            contract_type=contract_type,
                            branches=json.dumps(branches, ensure_ascii=False),
                            file_name=file_path if file_path else None,
                        )
                        actual_thread_id = thread.id

                    await conv_svc.add_message(db, actual_thread_id, "user", user_input)
                    await conv_svc.add_message(db, actual_thread_id, "assistant", full_text)
                    await thread_cache.append_cached_message(actual_thread_id, "user", user_input)
                    await thread_cache.append_cached_message(actual_thread_id, "assistant", full_text)
                except Exception as e:
                    logger.error(f"保存对话记录失败: {e}")

            yield {
                "event": "done",
                "data": {
                    "id": history_id, "thread_id": actual_thread_id,
                    "full_output": full_text, "error": "",
                },
            }


async def stream_qa(
    user_input: str = "",
    user_id: int | None = None,
    db: AsyncSession | None = None,
    thread_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    """法律咨询 SSE 事件生成器。"""

    conversation_history, thread, _ = await _load_history(
        thread_id, db, user_id
    ) if thread_id and db and user_id else ([], None, [])

    state, config, actual_thread_id = build_qa_state(user_input, thread_id)
    if conversation_history:
        config["configurable"]["conversation_history"] = conversation_history

    full_text = ""
    retrieval_info = {}
    async for event in _stream_graph(get_qa_graph(), state, config):
        if event["event"] == "retrieval_done":
            retrieval_info = event["data"]
            yield event
        elif event["event"] == "retry":
            full_text = ""  # 清空旧 token，LLM 重试会重新产出
            yield event
        elif event["event"] == "token":
            full_text += event["data"].get("token", "")
            yield event
        elif event["event"] == "done":
            error_msg = event["data"].get("error", "")
            if error_msg:
                yield event
                return

            contract_type = retrieval_info.get("contract_type", "")
            branches = retrieval_info.get("branches", [])
            history_id = None

            if db is not None and user_id is not None:
                try:
                    h = await create_history(
                        db, user_id=user_id, query_input=user_input,
                        contract_type=contract_type, review_output=full_text,
                    )
                    history_id = h.id
                except Exception as e:
                    logger.error(f"保存历史记录失败: {e}")

                try:
                    if thread is None:
                        thread = await conv_svc.create_thread(
                            db, user_id=user_id, input_text=user_input,
                            contract_type=contract_type,
                            branches=json.dumps(branches, ensure_ascii=False),
                        )
                        actual_thread_id = thread.id

                    await conv_svc.add_message(db, actual_thread_id, "user", user_input)
                    await conv_svc.add_message(db, actual_thread_id, "assistant", full_text)
                    await thread_cache.append_cached_message(actual_thread_id, "user", user_input)
                    await thread_cache.append_cached_message(actual_thread_id, "assistant", full_text)
                except Exception as e:
                    logger.error(f"保存对话记录失败: {e}")

            yield {
                "event": "done",
                "data": {
                    "id": history_id, "thread_id": actual_thread_id,
                    "full_output": full_text, "error": "",
                },
            }
