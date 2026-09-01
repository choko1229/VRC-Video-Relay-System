import logging

import httpx

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"


class DiscordNotifier:
    """承認通知等をDiscord DMで送るためのラッパー。

    BotがDMを送るだけならGateway接続(常時WebSocket)は不要で、
    「DMチャンネル作成→メッセージ送信」のREST API 2回で完結する
    (前提: Botが対象ユーザーと同じサーバーに参加していること)。
    DISCORD_BOT_TOKEN未設定の場合はno-opとして振る舞う(ログ出力のみ)。
    """

    def __init__(self, token: str) -> None:
        self._token = token
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    async def start(self) -> None:
        if not self.enabled:
            logger.warning("DISCORD_BOT_TOKEN未設定のため、Discord通知は無効化されています")
            return
        self._client = httpx.AsyncClient(
            base_url=DISCORD_API_BASE,
            headers={"Authorization": f"Bot {self._token}"},
            timeout=10.0,
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def send_dm(self, discord_id: str, message: str) -> bool:
        if not self.enabled or self._client is None:
            logger.info("[discord dm skipped] to=%s message=%s", discord_id, message)
            return False

        try:
            channel_resp = await self._client.post(
                "/users/@me/channels", json={"recipient_id": discord_id}
            )
            channel_resp.raise_for_status()
            channel_id = channel_resp.json()["id"]

            msg_resp = await self._client.post(
                f"/channels/{channel_id}/messages", json={"content": message}
            )
            msg_resp.raise_for_status()
            return True
        except Exception:
            logger.exception("Discord DM送信に失敗しました discord_id=%s", discord_id)
            return False
