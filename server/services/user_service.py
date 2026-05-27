from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.user import User
from server.auth.password import hash_password


async def create_user(db: AsyncSession, username: str, password: str, role: str = "user") -> User:
    user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.id))
    return list(result.scalars().all())


async def delete_user(db: AsyncSession, user_id: int) -> bool:
    user = await db.get(User, user_id)
    if user is None:
        return False
    await db.delete(user)
    await db.commit()
    return True


async def update_role(db: AsyncSession, user_id: int, role: str) -> User | None:
    user = await db.get(User, user_id)
    if user is None:
        return None
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user
