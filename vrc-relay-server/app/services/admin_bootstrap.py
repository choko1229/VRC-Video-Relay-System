import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.user import User, UserRole, UserStatus
from app.services import auth_service

logger = logging.getLogger(__name__)


async def ensure_admin_user(db: AsyncSession, settings: Settings) -> None:
    """起動時、settings.admin_usernameのadminユーザーが存在しなければ作成する。"""
    result = await db.execute(select(User).where(User.username == settings.admin_username))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return

    now = datetime.now(UTC)
    admin = User(
        username=settings.admin_username,
        password_hash=auth_service.hash_password(settings.admin_password),
        status=UserStatus.approved,
        role=UserRole.admin,
        applied_at=now,
        approved_at=now,
    )
    db.add(admin)
    await db.commit()
    logger.info("初期管理者アカウントを作成しました: %s", settings.admin_username)
