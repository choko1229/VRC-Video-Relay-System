import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserStatus
from app.services import stream_key_service
from app.services.discord_service import DiscordNotifier
from app.services.mediamtx_client import MediaMTXClient

logger = logging.getLogger(__name__)


async def approve_user(db: AsyncSession, user: User, discord: DiscordNotifier) -> User:
    """承認待ちユーザーを承認し、ストリームキー発行とDiscord DM送信を行う。

    admin API・管理パネルWebUIの双方から呼ばれる共通処理。
    """
    user.status = UserStatus.approved
    user.approved_at = datetime.now(UTC)
    await stream_key_service.create_for_user(db, user)
    await db.commit()
    await db.refresh(user)

    # 一般ユーザーはDiscord OAuthが必須のためdiscord_idは常に設定されている
    message = "ご利用申請が承認されました！Windowsアプリから「Discordでログイン」してください。"
    await discord.send_dm(user.discord_id, message)

    return user


async def ban_user(db: AsyncSession, user: User, mediamtx: MediaMTXClient) -> User:
    """ユーザーをBAN(またはpendingユーザーを却下)し、配信中であれば強制切断する。"""
    user.status = UserStatus.banned
    key = await stream_key_service.get_by_user_id(db, user.id)
    if key is not None:
        await stream_key_service.deactivate(db, key)
    await db.commit()
    await db.refresh(user)

    if key is not None:
        try:
            await mediamtx.kick_publisher_by_path(key.path_name)
        except Exception:
            logger.exception("BAN時の強制切断に失敗しました path=%s", key.path_name)

    return user
