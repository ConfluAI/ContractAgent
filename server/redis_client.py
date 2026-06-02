"""
Redis 客户端单例 — 异步连接，自动重连。
"""

import logging
from typing import Optional

import redis.asyncio as aioredis

from server.config import settings

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """获取 Redis 异步客户端（单例）。"""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        # 验证连接
        try:
            await _redis.ping()
            logger.info("Redis 连接成功: %s", settings.REDIS_URL)
        except Exception as e:
            logger.warning("Redis 不可用 (%s)，回退到仅 MySQL", e)
            _redis = None
    return _redis


async def close_redis() -> None:
    """关闭 Redis 连接。"""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
