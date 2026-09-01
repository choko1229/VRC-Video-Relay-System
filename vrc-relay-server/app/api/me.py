from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_mediamtx_client
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.stream import MyStatusOut, StreamKeyRotateOut
from app.services import stream_key_service
from app.services.mediamtx_client import MediaMTXClient

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("/status", response_model=MyStatusOut)
async def get_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_client),
) -> MyStatusOut:
    key = await stream_key_service.get_by_user_id(db, user.id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "配信設定が見つかりません")

    path_info = await mediamtx.get_path(key.path_name)
    is_publishing = bool(path_info and path_info.get("ready"))

    return MyStatusOut(
        path_name=key.path_name,
        playback_url=settings.playback_url(key.path_name),
        push_url=settings.push_url(key.path_name, key.stream_key),
        is_active=key.is_active,
        is_publishing=is_publishing,
        rotated_at=key.rotated_at,
    )


@router.post("/stream-key/rotate", response_model=StreamKeyRotateOut)
async def rotate_stream_key(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StreamKeyRotateOut:
    key = await stream_key_service.get_by_user_id(db, user.id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "配信設定が見つかりません")

    key = await stream_key_service.rotate(db, key)
    await db.commit()

    return StreamKeyRotateOut(
        path_name=key.path_name,
        push_url=settings.push_url(key.path_name, key.stream_key),
        rotated_at=key.rotated_at,
    )
