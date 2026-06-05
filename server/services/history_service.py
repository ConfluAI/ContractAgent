from __future__ import annotations
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.query_history import QueryHistory


async def create_history(
    db: AsyncSession,
    user_id: int,
    query_input: str,
    contract_type: str = "",
    review_output: str = "",
) -> QueryHistory:
    history = QueryHistory(
        user_id=user_id,
        query_input=query_input,
        contract_type=contract_type,
        review_output=review_output,
    )
    db.add(history)
    await db.commit()
    await db.refresh(history)
    return history


async def list_by_user(db: AsyncSession, user_id: int) -> list[QueryHistory]:
    result = await db.execute(
        select(QueryHistory).where(QueryHistory.user_id == user_id).order_by(QueryHistory.id.desc())
    )
    return list(result.scalars().all())


async def delete_by_id(db: AsyncSession, history_id: int, user_id: int | None = None) -> bool:
    history = await db.get(QueryHistory, history_id)
    if history is None:
        return False
    if user_id is not None and history.user_id != user_id:
        return False
    await db.delete(history)
    await db.commit()
    return True
