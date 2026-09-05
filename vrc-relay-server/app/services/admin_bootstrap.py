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


class AdminUsernameTakenError(Exception):
    pass


async def update_admin_credentials(
    db: AsyncSession, old_username: str, new_username: str, new_password: str
) -> None:
    """管理画面の接続設定変更で、break-glassアカウントのユーザー名/パスワードを更新する。

    ensure_admin_userは「存在しなければ作る」だけなので、ユーザー名を変更した場合に
    そのまま使うと元のアカウントが残ったまま新しいアカウントが増えてしまう(過去に実際に
    起きた「管理者アカウントが複数できてしまう」不具合と同じ原因)。ここでは既存の行を
    直接更新する。
    """
    if new_username != old_username:
        result = await db.execute(select(User).where(User.username == new_username))
        if result.scalar_one_or_none() is not None:
            raise AdminUsernameTakenError(f"ユーザー名「{new_username}」は既に使用されています")

    result = await db.execute(select(User).where(User.username == old_username))
    admin = result.scalar_one_or_none()

    now = datetime.now(UTC)
    if admin is None:
        # break-glass行が見つからない(手動で削除された等)場合は新規作成にフォールバックする
        admin = User(
            username=new_username,
            status=UserStatus.approved,
            role=UserRole.admin,
            applied_at=now,
            approved_at=now,
        )
        db.add(admin)
    else:
        admin.username = new_username

    admin.password_hash = auth_service.hash_password(new_password)
    await db.commit()
    logger.info("break-glass管理者アカウントの認証情報を更新しました: %s", new_username)
