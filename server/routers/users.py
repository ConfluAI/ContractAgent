from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.schemas.user import RoleUpdateRequest, UserListResponse
from server.schemas.auth import UserResponse
from server.services.user_service import list_users, delete_user, update_role
from server.auth.dependencies import require_role
from server.models.user import User

router = APIRouter(prefix="/api/users", tags=["用户管理"])


@router.get("", response_model=UserListResponse)
async def get_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    users = await list_users(db)
    return UserListResponse(users=users, total=len(users))


@router.delete("/{user_id}")
async def remove_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    ok = await delete_user(db, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"message": "删除成功"}


@router.put("/{user_id}/role", response_model=UserResponse)
async def change_role(
    user_id: int,
    body: RoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    user = await update_role(db, user_id, body.role)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user
