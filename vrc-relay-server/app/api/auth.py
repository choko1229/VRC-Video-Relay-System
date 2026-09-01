import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.connection_log import ConnectionEventType, ConnectionLog
from app.models.user import User, UserStatus
from app.schemas.auth import (
    ApplyRequest,
    ApplyResponse,
    LoginRequest,
    LoginResponse,
    SetPasswordRequest,
)
from app.services import auth_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/apply", response_model=ApplyResponse)
async def apply(payload: ApplyRequest, db: AsyncSession = Depends(get_db)) -> ApplyResponse:
    result = await db.execute(select(User).where(User.username == payload.username))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "このユーザー名は既に使用されています")

    user = User(
        username=payload.username,
        discord_id=payload.discord_id,
        status=UserStatus.pending,
        applied_at=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    logger.info("新規申請を受け付けました: username=%s", payload.username)
    return ApplyResponse(message="申請を受け付けました。管理者の承認をお待ちください。")


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        await _log_auth_fail(db, None, f"login failed: unknown user {payload.username}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ユーザー名またはパスワードが違います")

    if not auth_service.verify_password(payload.password, user.password_hash):
        await _log_auth_fail(db, user.id, "login failed: bad password")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ユーザー名またはパスワードが違います")

    if user.status == UserStatus.banned:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "このアカウントはBANされています")
    if user.status == UserStatus.pending:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "アカウントはまだ承認されていません")

    token = auth_service.create_access_token(user, settings)
    return LoginResponse(access_token=token)


@router.post("/set-password", response_model=ApplyResponse)
async def set_password(
    payload: SetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ApplyResponse:
    try:
        user_id = auth_service.verify_password_setup_token(payload.token, settings)
    except auth_service.InvalidTokenError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "リンクが無効か有効期限切れです"
        ) from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ユーザーが見つかりません")
    if user.status != UserStatus.approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "アカウントが承認されていません")

    user.password_hash = auth_service.hash_password(payload.password)
    await db.commit()
    return ApplyResponse(message="パスワードを設定しました。Windowsアプリからログインできます。")


async def _log_auth_fail(db: AsyncSession, user_id: int | None, detail: str) -> None:
    db.add(
        ConnectionLog(
            user_id=user_id,
            event_type=ConnectionEventType.auth_fail,
            detail=detail,
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()
