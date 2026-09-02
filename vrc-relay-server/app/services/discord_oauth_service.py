"""Discord OAuth2(Authorization Code Grant)ラッパー。

一般ユーザーの利用申請・ログインはDiscord OAuthを必須とする。デスクトップクライアント
(Windowsアプリ)はredirect_uriを事前登録できないため、Discordへは常に本サーバー固定の
redirect_uri(settings.discord_oauth_redirect_uri)で認可させ、コールバック後にstateへ
埋め込んでおいたクライアント側のローカルURL(http://127.0.0.1:<port>/oauth/callback)へ
サーバーがさらにリダイレクトする(いわゆるOAuthリレー方式)。
"""

from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
USER_URL = "https://discord.com/api/users/@me"


class DiscordOAuthError(Exception):
    pass


def build_authorize_url(state: str, settings: Settings) -> str:
    params = {
        "client_id": settings.discord_oauth_client_id,
        "redirect_uri": settings.discord_oauth_redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "prompt": "consent",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str, settings: Settings) -> str:
    """authorization codeをaccess_tokenに交換する。失敗時はDiscordOAuthErrorを送出する。"""
    data = {
        "client_id": settings.discord_oauth_client_id,
        "client_secret": settings.discord_oauth_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.discord_oauth_redirect_uri,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(TOKEN_URL, data=data)
    if resp.status_code != 200:
        raise DiscordOAuthError(f"token exchange failed: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


async def fetch_discord_user(access_token: str) -> dict[str, Any]:
    """{"id": ..., "username": ..., "global_name": ...} 等を返す。"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(USER_URL, headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code != 200:
        raise DiscordOAuthError(f"fetching discord user failed: {resp.status_code} {resp.text}")
    return resp.json()
