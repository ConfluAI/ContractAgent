"""
对话线程缓存 — Redis L1 + MySQL L2（仅缓存消息，不缓存法律条文）。

读：Redis → 未命中 → MySQL → 回填 Redis
写：MySQL → Redis（write-through）
"""

import json
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from server.redis_client import get_redis
from server.services import conversation_service as mysql_svc

logger = logging.getLogger(__name__)

# ── Redis Key ───────────────────────────────────────────────────────────
# thread:{thread_id}:messages  → list: [{role, content}, ...]

_MESSAGES_TTL = 1800    # 30 分钟
_MAX_MESSAGES = 20      # 最近 20 条


def _messages_key(thread_id: str) -> str:
    return f"thread:{thread_id}:messages"


# ── 读 ──────────────────────────────────────────────────────────────────

async def get_cached_messages(
    thread_id: str, db: AsyncSession,
) -> list[dict]:
    """加载对话历史。先查 Redis，未命中查 MySQL。"""
    redis = await get_redis()

    if redis:
        try:
            raw_list = await redis.lrange(_messages_key(thread_id), 0, -1)
            if raw_list:
                logger.debug("消息缓存命中 Redis: %s (%d 条)", thread_id, len(raw_list))
                return [json.loads(m) for m in raw_list]
        except Exception as e:
            logger.warning("Redis 读取消息失败: %s", e)

    # MySQL fallback
    messages = await mysql_svc.get_messages(db, thread_id)
    result = [{"role": m.role, "content": m.content} for m in messages]

    # 回填 Redis
    if redis and result:
        try:
            pipe = redis.pipeline()
            key = _messages_key(thread_id)
            pipe.delete(key)
            for msg in result[-_MAX_MESSAGES:]:
                pipe.rpush(key, json.dumps(msg, ensure_ascii=False))
            pipe.expire(key, _MESSAGES_TTL)
            await pipe.execute()
        except Exception as e:
            logger.warning("Redis 回填消息失败: %s", e)

    return result


# ── 写 ──────────────────────────────────────────────────────────────────

async def append_cached_message(
    thread_id: str, role: str, content: str,
) -> None:
    """写穿：追加消息到 Redis。MySQL 由调用方负责。"""
    redis = await get_redis()
    if redis is None:
        return
    try:
        msg = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        key = _messages_key(thread_id)
        pipe = redis.pipeline()
        pipe.rpush(key, msg)
        pipe.ltrim(key, -_MAX_MESSAGES, -1)
        pipe.expire(key, _MESSAGES_TTL)
        await pipe.execute()
    except Exception as e:
        logger.warning("Redis 追加消息失败: %s", e)


async def invalidate_thread(thread_id: str) -> None:
    """删除线程的 Redis 消息缓存。"""
    redis = await get_redis()
    if redis is None:
        return
    try:
        await redis.delete(_messages_key(thread_id))
    except Exception as e:
        logger.warning("Redis 失效缓存失败: %s", e)
