"""
会话线程 REST API。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.auth.dependencies import get_current_user
from server.models.user import User
from server.services import conversation_service as svc
from server.services import thread_cache
from graph.workflow import get_review_graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads", tags=["会话线程"])


@router.get("")
async def list_threads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户的所有会话线程。"""
    threads = await svc.list_user_threads(db, current_user.id)
    return [
        {
            "id": t.id,
            "title": t.title,
            "contract_type": t.contract_type,
            "file_name": t.file_name,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in threads
    ]


@router.get("/{thread_id}")
async def get_thread(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取线程详情。"""
    thread = await svc.get_thread(db, thread_id, current_user.id)
    if thread is None:
        raise HTTPException(status_code=404, detail="线程不存在")
    return {
        "id": thread.id,
        "title": thread.title,
        "contract_type": thread.contract_type,
        "file_name": thread.file_name,
        "input_text": thread.input_text,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
        "updated_at": thread.updated_at.isoformat() if thread.updated_at else None,
    }


@router.get("/{thread_id}/messages")
async def get_messages(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取线程的所有对话消息。"""
    thread = await svc.get_thread(db, thread_id, current_user.id)
    if thread is None:
        raise HTTPException(status_code=404, detail="线程不存在")
    messages = await svc.get_messages(db, thread_id)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


@router.delete("/{thread_id}")
async def remove_thread(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除线程、消息、Redis 缓存 以及 PG checkpoint。"""
    ok = await svc.delete_thread(db, thread_id, current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="线程不存在")

    # 清理 Redis 消息缓存
    await thread_cache.invalidate_thread(thread_id)

    # 清理 PG checkpoint
    graph = get_review_graph()
    if graph is not None:
        try:
            await graph.checkpointer.adelete_thread(thread_id)
        except Exception:
            logger.warning("清理 checkpoint 失败: %s", thread_id, exc_info=True)

    return {"ok": True}
