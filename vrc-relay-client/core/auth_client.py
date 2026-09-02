import base64
import json
import logging
from datetime import UTC, datetime

import httpx

from db.models import AuthToken, SessionLocal

logger = logging.getLogger(__name__)

try:
    import win32crypt

    _DPAPI_AVAILABLE = True
except ImportError:
    _DPAPI_AVAILABLE = False
    logger.warning(
        "pywin32(win32crypt)が利用できません。DPAPI暗号化の代わりにBase64エンコードのみで"
        "保存します(Windows以外での開発時のみを想定。本番Windows環境では発生しないはず)。"
    )


def _encrypt(raw: str) -> bytes:
    if _DPAPI_AVAILABLE:
        return win32crypt.CryptProtectData(raw.encode("utf-8"), "vrc-relay-client", None, None, None, 0)
    return base64.b64encode(raw.encode("utf-8"))


def _decrypt(blob: bytes) -> str:
    if _DPAPI_AVAILABLE:
        _desc, data = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return data.decode("utf-8")
    return base64.b64decode(blob).decode("utf-8")


def save_token(username: str, token: str) -> None:
    encrypted = _encrypt(token)
    with SessionLocal() as session:
        session.query(AuthToken).delete()
        session.add(
            AuthToken(username=username, encrypted_token=encrypted, issued_at=datetime.now(UTC))
        )
        session.commit()


def load_token() -> tuple[str, str] | None:
    """(username, token) を返す。未ログインならNone。"""
    with SessionLocal() as session:
        row = session.query(AuthToken).first()
        if row is None:
            return None
        try:
            return row.username, _decrypt(row.encrypted_token)
        except Exception:
            logger.exception("認証トークンの復号に失敗しました。再ログインが必要です。")
            return None


def clear_token() -> None:
    with SessionLocal() as session:
        session.query(AuthToken).delete()
        session.commit()


def _decode_jwt_payload(token: str) -> dict:
    """署名検証はしない、payloadを読み出すだけの軽量デコード。
    このJWTはDiscord OAuthコールバックでサーバーからHTTPS経由で直接渡されたものであり、
    ここではローカル表示用のusernameを取り出す目的のみに使う(認可判断には使わない)。"""
    payload_b64 = token.split(".")[1]
    padding = "=" * (-len(payload_b64) % 4)
    decoded = base64.urlsafe_b64decode(payload_b64 + padding)
    return json.loads(decoded)


def save_token_from_jwt(token: str) -> str:
    """Discord OAuthログイン完了後、ローカルコールバックで受け取ったJWTを保存する。"""
    try:
        payload = _decode_jwt_payload(token)
        username = payload.get("username", "unknown")
    except Exception:
        logger.exception("受け取ったトークンの解析に失敗しました")
        username = "unknown"

    save_token(username, token)
    return username


async def get_my_status(base_url: str, token: str) -> dict:
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        resp = await client.get("/api/me/status", headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        return resp.json()


async def rotate_stream_key(base_url: str, token: str) -> dict:
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        resp = await client.post(
            "/api/me/stream-key/rotate", headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        return resp.json()
