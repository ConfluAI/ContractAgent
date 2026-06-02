"""
Checkpoint 定期清理 — 删除超过保留期的 PostgreSQL checkpoint。
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from server.config import settings
from server.database import AsyncSessionLocal
from server.models.conversation_thread import ConversationThread
from graph.workflow import get_review_graph

logger = logging.getLogger(__name__)

_CLEANUP_INTERVAL_HOURS = 6  # 每 6 小时执行一次


async def _run_cleanup() -> int:
    """删除超过 CHECKPOINT_RETENTION_DAYS 天的 PG checkpoint。

    遍历 MySQL conversation_threads，找出 updated_at 超过保留期的线程，
    然后调用 PostgresSaver.adelete_thread() 清理对应的 checkpoint。

    Returns:
        清理的线程数。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.CHECKPOINT_RETENTION_DAYS
    )

    # 1. 从 MySQL 查出过期的 thread_id
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ConversationThread.id).where(
                ConversationThread.updated_at < cutoff
            )
        )
        old_threads = [row[0] for row in result.fetchall()]

    if not old_threads:
        return 0

    # 2. 在 PG 中删除对应 checkpoint
    deleted = 0
    graph = get_review_graph()
    if graph is None:
        logger.warning("图未编译，跳过 checkpoint 清理")
        return 0

    checkpointer = graph.checkpointer
    for thread_id in old_threads:
        try:
            await checkpointer.adelete_thread(thread_id)
            deleted += 1
        except Exception:
            pass  # checkpoint 可能本就不存在

    return deleted


async def cleanup_loop() -> None:
    """后台循环：定期清理过期 checkpoint。首次启动后等待 5 分钟再执行。"""
    await asyncio.sleep(300)  # 等服务完全就绪

    while True:
        try:
            count = await _run_cleanup()
            if count > 0:
                logger.info(
                    "checkpoint 清理完成，删除 %d 个过期线程（保留期 %d 天）",
                    count, settings.CHECKPOINT_RETENTION_DAYS,
                )
        except Exception:
            logger.exception("checkpoint 清理异常")

        await asyncio.sleep(_CLEANUP_INTERVAL_HOURS * 3600)
