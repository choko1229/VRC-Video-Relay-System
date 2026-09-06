from datetime import datetime

from pydantic import BaseModel


class MyStatusOut(BaseModel):
    path_name: str
    playback_url: str
    # RTSPS(暗号化)が映らない環境向けの非暗号フォールバックURL(rtspt、ポート番号無しの
    # ことが多い)。デフォルトでは使わせず、「映らないときは？」的な案内でのみ見せる想定。
    playback_url_fallback: str
    # Windowsクライアントアプリがffmpeg中継先として使用する実URL(ストリームキー入り)。
    # JWT認証済みの本人にのみ返す。UI上には表示せず、内部設定にのみ使う想定。
    push_url: str
    is_active: bool
    is_publishing: bool
    rotated_at: datetime | None


class StreamKeyRotateOut(BaseModel):
    path_name: str
    push_url: str
    rotated_at: datetime


class LiveStreamOut(BaseModel):
    username: str
    path_name: str
    is_publishing: bool
    bytes_received: int | None = None
    ready_time: str | None = None
