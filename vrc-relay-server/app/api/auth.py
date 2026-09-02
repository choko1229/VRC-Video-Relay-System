import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.connection_log import ConnectionEventType, ConnectionLog
from app.models.user import User, UserStatus
from app.schemas.auth import LoginRequest, LoginResponse
from app.services import auth_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    """パスワードログイン。初回セットアップで作成する管理者アカウントのみが使う
    break-glass用の入口(一般ユーザーはDiscord OAuthが必須、/oauth/discord/loginを参照)。"""
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
