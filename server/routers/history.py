from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.schemas.history import HistoryItem, HistoryListResponse
from server.services.history_service import list_by_user, delete_by_id
from server.auth.dependencies import get_current_user
from server.models.user import User

router = APIRouter(prefix="/api/history", tags=["查询历史"])


@router.get("", response_model=HistoryListResponse)
async def get_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = await list_by_user(db, current_user.id)
    return HistoryListResponse(items=items, total=len(items))


@router.delete("/{history_id}")
async def remove_history(
    history_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ok = await delete_by_id(db, history_id, current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"message": "删除成功"}
