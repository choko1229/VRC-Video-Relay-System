import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stream_key import StreamKey
from app.models.user import User


def _generate_key() -> str:
    return secrets.token_urlsafe(32)


def path_name_for(username: str) -> str:
    return f"live_{username}"


async def create_for_user(db: AsyncSession, user: User) -> StreamKey:
    stream_key = StreamKey(
        user_id=user.id,
        stream_key=_generate_key(),
        path_name=path_name_for(user.username),
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db.add(stream_key)
    await db.flush()
    return stream_key


async def rotate(db: AsyncSession, stream_key: StreamKey) -> StreamKey:
    stream_key.stream_key = _generate_key()
    stream_key.rotated_at = datetime.now(UTC)
    stream_key.is_active = True
    await db.flush()
    return stream_key


async def deactivate(db: AsyncSession, stream_key: StreamKey) -> None:
    stream_key.is_active = False
    await db.flush()


async def get_by_path_name(db: AsyncSession, path_name: str) -> StreamKey | None:
    result = await db.execute(select(StreamKey).where(StreamKey.path_name == path_name))
    return result.scalar_one_or_none()


async def get_by_user_id(db: AsyncSession, user_id: int) -> StreamKey | None:
    result = await db.execute(select(StreamKey).where(StreamKey.user_id == user_id))
    return result.scalar_one_or_none()
