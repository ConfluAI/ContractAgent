from pydantic import BaseModel, Field

from server.schemas.auth import UserResponse


class RoleUpdateRequest(BaseModel):
    role: str = Field(..., pattern="^(admin|user)$")


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
