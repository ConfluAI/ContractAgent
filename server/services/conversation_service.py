"""
会话线程服务 — 线程 CRUD + 消息管理。
"""

import logging
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.conversation_thread import ConversationThread
from server.models.conversation_message import ConversationMessage

logger = logging.getLogger(__name__)


async def create_thread(
    db: AsyncSession,
    user_id: int,
    input_text: str = "",
    contract_type: str = "",
    branches: str = "[]",
    retrieval_result: str = "{}",
    title: str | None = None,
    file_name: str | None = None,
) -> ConversationThread:
    """创建新的会话线程，存储检索结果以便追问时复用。"""
    thread = ConversationThread(
        user_id=user_id,
        title=title or (input_text[:80] if input_text else "新对话"),
        contract_type=contract_type,
        branches=branches,
        retrieval_result=retrieval_result,
        file_name=file_name,
        input_text=input_text,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread


async def get_thread(
    db: AsyncSession, thread_id: str, user_id: int
) -> ConversationThread | None:
    """获取线程，验证所有权。"""
    result = await db.execute(
        select(ConversationThread).where(
            ConversationThread.id == thread_id,
            ConversationThread.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_user_threads(
    db: AsyncSession, user_id: int
) -> list[ConversationThread]:
    """列出用户的所有线程，按更新时间降序。"""
    result = await db.execute(
        select(ConversationThread)
        .where(ConversationThread.user_id == user_id)
        .order_by(desc(ConversationThread.updated_at))
    )
    return list(result.scalars().all())


async def delete_thread(
    db: AsyncSession, thread_id: str, user_id: int
) -> bool:
    """删除线程及其所有消息（级联）。"""
    thread = await get_thread(db, thread_id, user_id)
    if thread is None:
        return False
    await db.delete(thread)
    await db.commit()
    return True


async def add_message(
    db: AsyncSession, thread_id: str, role: str, content: str
) -> ConversationMessage:
    """向线程添加一条消息。"""
    msg = ConversationMessage(thread_id=thread_id, role=role, content=content)
    db.add(msg)
    # 同时更新线程的 updated_at
    thread = await db.get(ConversationThread, thread_id)
    if thread:
        from datetime import datetime
        thread.updated_at = datetime.now()
    await db.commit()
    await db.refresh(msg)
    return msg


async def get_messages(
    db: AsyncSession, thread_id: str
) -> list[ConversationMessage]:
    """获取线程的所有消息，按时间升序。"""
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.thread_id == thread_id)
        .order_by(ConversationMessage.created_at)
    )
    return list(result.scalars().all())
