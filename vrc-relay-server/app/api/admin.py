import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_discord_notifier, get_mediamtx_client, require_admin
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus
from app.schemas.stream import LiveStreamOut
from app.schemas.user import UserOut
from app.services import admin_actions, stream_key_service
from app.services.discord_service import DiscordNotifier
from app.services.mediamtx_client import MediaMTXClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/users", response_model=list[UserOut])
async def list_users(
    status_filter: UserStatus | None = None, db: AsyncSession = Depends(get_db)
) -> list[UserOut]:
    stmt = select(User)
    if status_filter is not None:
        stmt = stmt.where(User.status == status_filter)
    result = await db.execute(stmt.order_by(User.applied_at.desc()))
    return list(result.scalars())


@router.post("/users/{user_id}/approve", response_model=UserOut)
async def approve_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    discord: DiscordNotifier = Depends(get_discord_notifier),
) -> UserOut:
    user = await _get_user_or_404(db, user_id)
    if user.status != UserStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "承認待ちのユーザーではありません")

    return await admin_actions.approve_user(db, user, discord)


@router.post("/users/{user_id}/ban", response_model=UserOut)
async def ban_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_client),
    current_admin: User = Depends(get_current_user),
) -> UserOut:
    user = await _get_user_or_404(db, user_id)
    if user.id == current_admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "自分自身をBANすることはできません")

    return await admin_actions.ban_user(db, user, mediamtx)


@router.get("/streams", response_model=list[LiveStreamOut])
async def list_streams(
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_client),
) -> list[LiveStreamOut]:
    result = await db.execute(
        select(User).where(User.role == UserRole.user).where(User.status == UserStatus.approved)
    )
    users = list(result.scalars())

    paths = {p["name"]: p for p in await mediamtx.list_paths()}

    streams: list[LiveStreamOut] = []
    for user in users:
        key = await stream_key_service.get_by_user_id(db, user.id)
        if key is None:
            continue
        path_info = paths.get(key.path_name)
        streams.append(
            LiveStreamOut(
                username=user.username,
                path_name=key.path_name,
                is_publishing=bool(path_info and path_info.get("ready")),
                bytes_received=path_info.get("bytesReceived") if path_info else None,
                ready_time=path_info.get("readyTime") if path_info else None,
            )
        )
    return streams


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ユーザーが見つかりません")
    return user
