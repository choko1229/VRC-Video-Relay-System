import logging
from datetime import UTC, datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.connection_log import ConnectionEventType, ConnectionLog
from app.models.stream_key import StreamKey
from app.models.user import User, UserStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/mediamtx", tags=["mediamtx"])

# 認証が必要なアクション。read/playback等はMediaMTX側のauthHTTPExcludeで既に除外している
# 想定だが、設定漏れに備えてここでも許可アクションのみ検証する防御的実装にしている。
_AUTH_REQUIRED_ACTIONS = {"publish"}


@router.post("/auth")
async def mediamtx_auth(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    payload = await request.json()
    action = payload.get("action")
    path_name = payload.get("path", "")
    query = payload.get("query", "")

    if action not in _AUTH_REQUIRED_ACTIONS:
        return Response(status_code=status.HTTP_200_OK)

    key_value = parse_qs(query).get("key", [None])[0]
    if not key_value:
        await _log_auth_fail(db, None, f"missing key: path={path_name}")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    result = await db.execute(select(StreamKey).where(StreamKey.path_name == path_name))
    stream_key = result.scalar_one_or_none()

    if stream_key is None or not stream_key.is_active or stream_key.stream_key != key_value:
        await _log_auth_fail(
            db, stream_key.user_id if stream_key else None, f"invalid key: path={path_name}"
        )
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    user_result = await db.execute(select(User).where(User.id == stream_key.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or user.status != UserStatus.approved:
        await _log_auth_fail(db, stream_key.user_id, f"user not approved: path={path_name}")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    db.add(
        ConnectionLog(
            user_id=user.id,
            event_type=ConnectionEventType.publish_start,
            detail=f"path={path_name}",
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()

    return Response(status_code=status.HTTP_200_OK)


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
