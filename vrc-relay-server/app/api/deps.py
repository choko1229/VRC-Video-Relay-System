from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus
from app.services import auth_service
from app.services.discord_service import DiscordNotifier
from app.services.mediamtx_client import MediaMTXClient

_bearer_scheme = HTTPBearer(auto_error=False)


def get_mediamtx_client(settings: Settings = Depends(get_settings)) -> MediaMTXClient:
    return MediaMTXClient(settings)


def get_discord_notifier(request: Request) -> DiscordNotifier:
    return request.app.state.discord_notifier


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "認証トークンがありません")

    try:
        payload = auth_service.decode_token(credentials.credentials, settings)
    except auth_service.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "無効なトークンです") from exc

    if payload.get("purpose") != auth_service.TOKEN_PURPOSE_ACCESS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "無効なトークンです")

    user_id = int(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ユーザーが見つかりません")
    if user.status != UserStatus.approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "アカウントが有効ではありません")

    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "管理者権限が必要です")
    return user
