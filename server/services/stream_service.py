"""
SSE 流式服务 — 使用 asyncio.Queue 在节点间传递 token。

流程:
  1. 如果有 thread_id → 加载对话历史
  2. 创建 asyncio.Queue，注册到 graph 节点的模块级 _stream_queues[thread_id]
  3. 后台运行图，节点将 token 推入队列
  4. 主循环从队列读取 → 逐 token SSE
  5. 图完成后从 checkpoint 获取 review_output，持久化消息
"""

from __future__ import annotations
import asyncio
import json
import logging
import re
import time
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from graph.workflow import (
    get_review_graph, get_qa_graph,
    build_review_state, build_qa_state,
)
from server.services.history_service import create_history
from server.services import conversation_service as conv_svc
from server.services import thread_cache
from graph.reviewer import _stream_queues as _review_queues
from graph.qa_responder import _stream_queues as _qa_queues

logger = logging.getLogger(__name__)


def _extract_conclusion(text: str) -> str:
    m = re.search(r"一、直接结论\s*\n?(.*?)(?=二、|\Z)", text, re.DOTALL)
    if m:
        return m.group(1).strip()[:300]
    return text[:200].strip()


def _trim_history(messages: list[dict]) -> list[dict]:
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
    thread = await conv_svc.get_thread(db, thread_id, user_id)
    if thread is None:
        return [], None, []
    messages = await thread_cache.get_cached_messages(thread_id, db)
    raw = [{"role": m["role"], "content": m["content"]} for m in messages]
    history = _trim_history(raw)
    return history, thread, json.loads(thread.branches or "[]")


_STREAM_MAX_RETRIES = 3
_STREAM_RETRY_BASE_DELAY = 2.0


async def _stream_graph(
    graph, state: dict, config: dict,
) -> AsyncGenerator[dict, None]:
    """图流式包装器——带重试的 astream + asyncio.Queue token 传递。

    Yields SSE events: retrieval_done, token, retry, done
    """
    thread_id = config["configurable"]["thread_id"]

    for attempt in range(1, _STREAM_MAX_RETRIES + 1):
        token_queue: asyncio.Queue = asyncio.Queue()
        _review_queues[thread_id] = token_queue
        _qa_queues[thread_id] = token_queue
        graph_error = None
        astream_ended = asyncio.Event()

        async def _run_graph():
            nonlocal graph_error
            try:
                async for mode, data in graph.astream(
                    state, config, stream_mode=["updates"]
                ):
                    if mode == "updates" and "merge_retrieval" in data:
                        merge_data = data["merge_retrieval"]
                        await token_queue.put({
                            "_retrieval_done": True,
                            "warnings": merge_data.get("warnings", []),
                        })
                    if mode == "updates" and "dispatcher" in data:
                        d_data = data["dispatcher"]
                        await token_queue.put({
                            "_dispatcher": True,
                            "contract_type": d_data.get("contract_type", ""),
                            "branches": d_data.get("branches", []),
                        })
                    if mode == "updates" and "reviewer" in data:
                        r_data = data["reviewer"]
                        await token_queue.put({
                            "_review_done": True,
                            "review_output": r_data.get("review_output", ""),
                        })
                    if mode == "updates" and "qa_responder" in data:
                        q_data = data["qa_responder"]
                        await token_queue.put({
                            "_review_done": True,
                            "review_output": q_data.get("review_output", ""),
                        })
                astream_ended.set()
            except Exception as e:
                graph_error = str(e)
                astream_ended.set()

        graph_task = asyncio.create_task(_run_graph())
        dispatcher_info = {}
        review_output = ""
        final_error = ""

        try:
            _last_data_time = time.monotonic()
            while not astream_ended.is_set() or not token_queue.empty():
                try:
                    item = await asyncio.wait_for(token_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if time.monotonic() - _last_data_time > 15:
                        yield {"_heartbeat": True}
                        _last_data_time = time.monotonic()
                    continue
                _last_data_time = time.monotonic()
                if "_dispatcher" in item:
                    dispatcher_info["contract_type"] = item.get("contract_type", "")
                    dispatcher_info["branches"] = item.get("branches", [])
                elif "_retrieval_done" in item:
                    yield {
                        "event": "retrieval_done",
                        "data": {
                            "contract_type": dispatcher_info.get("contract_type", ""),
                            "branches": dispatcher_info.get("branches", []),
                            "warnings": item.get("warnings", []),
                        },
                    }
                elif "_review_done" in item:
                    review_output = item.get("review_output", "")
                    if item.get("error"):
                        final_error = item["error"]
                elif "token" in item:
                    yield {"event": "token", "data": item}

            await graph_task
            _review_queues.pop(thread_id, None)
            _qa_queues.pop(thread_id, None)

            if graph_error and attempt < _STREAM_MAX_RETRIES:
                delay = min(_STREAM_RETRY_BASE_DELAY ** attempt, 10)
                logger.warning(
                    f"图流式失败 (attempt={attempt}/{_STREAM_MAX_RETRIES}, "
                    f"thread={thread_id}): {graph_error}, {delay:.0f}s 后重试..."
                )
                await asyncio.sleep(delay)
                yield {
                    "event": "retry",
                    "data": {"attempt": attempt + 1, "max_retries": _STREAM_MAX_RETRIES},
                }
                continue

            if graph_error or final_error:
                yield {
                    "event": "done",
                    "data": {
                        "id": None, "thread_id": thread_id,
                        "full_output": "", "error": graph_error or final_error,
                    },
                }
                return

            yield {
                "event": "done",
                "data": {
                    "id": None, "thread_id": thread_id,
                    "full_output": "",
                    "error": "",
                    "warnings": [],
                    "review_output": review_output,
                },
            }
            return

        except Exception as e:
            _review_queues.pop(thread_id, None)
            _qa_queues.pop(thread_id, None)
            if attempt == _STREAM_MAX_RETRIES:
                logger.error(f"图流式 {_STREAM_MAX_RETRIES} 次全部失败 (thread={thread_id}): {e}")
                yield {
                    "event": "done",
                    "data": {
                        "id": None, "thread_id": thread_id,
                        "full_output": "", "error": str(e),
                    },
                }
                return
            delay = min(_STREAM_RETRY_BASE_DELAY ** attempt, 10)
            logger.warning(
                f"图流式失败 (attempt={attempt}/{_STREAM_MAX_RETRIES}, "
                f"thread={thread_id}): {e}, {delay:.0f}s 后重试..."
            )
            await asyncio.sleep(delay)
            yield {
                "event": "retry",
                "data": {"attempt": attempt + 1, "max_retries": _STREAM_MAX_RETRIES},
            }


async def stream_review(
    user_input: str = "",
    file_path: str = "",
    user_id: int | None = None,
    db: AsyncSession | None = None,
    thread_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    """合同审查 SSE 事件生成器。"""

    conversation_history, thread, _ = await _load_history(
        thread_id, db, user_id
    ) if thread_id and db and user_id else ([], None, [])

    state, config, actual_thread_id = build_review_state(user_input, file_path, thread_id)
    config.setdefault("metadata", {})["thread_id"] = actual_thread_id
    if conversation_history:
        config["configurable"]["conversation_history"] = conversation_history

    full_text = ""
    retrieval_info = {}

    async for event in _stream_graph(get_review_graph(), state, config):
        if event["event"] == "retrieval_done":
            retrieval_info.update(event["data"])
            yield event
        elif event["event"] == "retry":
            full_text = ""
            yield event
        elif event["event"] == "token":
            full_text += event["data"].get("token", "")
            yield event
        elif event["event"] == "done":
            error_msg = event["data"].get("error", "")
            if error_msg:
                yield event
                return

            snapshot = await get_review_graph().aget_state(config)
            sv = snapshot.values if snapshot else {}
            contract_type = sv.get("contract_type", retrieval_info.get("contract_type", ""))
            branches = sv.get("branches", retrieval_info.get("branches", []))
            if not full_text:
                full_text = sv.get("review_output", "")

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
    config.setdefault("metadata", {})["thread_id"] = actual_thread_id
    if conversation_history:
        config["configurable"]["conversation_history"] = conversation_history

    full_text = ""
    retrieval_info = {}

    async for event in _stream_graph(get_qa_graph(), state, config):
        if event["event"] == "retrieval_done":
            retrieval_info.update(event["data"])
            yield event
        elif event["event"] == "retry":
            full_text = ""
            yield event
        elif event["event"] == "token":
            full_text += event["data"].get("token", "")
            yield event
        elif event["event"] == "done":
            error_msg = event["data"].get("error", "")
            if error_msg:
                yield event
                return

            snapshot = await get_qa_graph().aget_state(config)
            sv = snapshot.values if snapshot else {}
            contract_type = sv.get("contract_type", retrieval_info.get("contract_type", ""))
            branches = sv.get("branches", retrieval_info.get("branches", []))
            if not full_text:
                full_text = sv.get("review_output", "")

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
