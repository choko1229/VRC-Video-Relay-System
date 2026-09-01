import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class MediaMTXClient:
    """公開サーバーMediaMTXのHTTP API(paths/list, rtmpconns kick等)のラッパー。

    注意: 個別パスの動的add/delete(v3のconfig API)は配信中に他ユーザーを切断する
    既知の不具合報告があるため使用しない。ここではpaths一覧取得とセッションkickのみ扱う。
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.mediamtx_api_base_url.rstrip("/")

    async def list_paths(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=5.0) as client:
            resp = await client.get("/v3/paths/list")
            resp.raise_for_status()
            return resp.json().get("items", [])

    async def get_path(self, path_name: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=5.0) as client:
            resp = await client.get(f"/v3/paths/get/{path_name}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def list_rtmp_conns(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=5.0) as client:
            resp = await client.get("/v3/rtmpconns/list")
            resp.raise_for_status()
            return resp.json().get("items", [])

    async def kick_rtmp_conn(self, conn_id: str) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=5.0) as client:
            resp = await client.post(f"/v3/rtmpconns/kick/{conn_id}")
            resp.raise_for_status()

    async def kick_publisher_by_path(self, path_name: str) -> bool:
        """指定パスをpublish中のRTMPコネクションを切断する。見つからなければFalse。"""
        conns = await self.list_rtmp_conns()
        for conn in conns:
            if conn.get("path") == path_name and conn.get("state") == "publish":
                await self.kick_rtmp_conn(conn["id"])
                return True
        return False
