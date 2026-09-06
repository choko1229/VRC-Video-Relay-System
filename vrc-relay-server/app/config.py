import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # .envに常に必要なのはAPP_PORTのみ。それ以外は初回起動時のセットアップ画面
    # (/setup)で入力され、.envへ書き込まれる。未設定の間はis_configuredがFalseになり、
    # アプリはセットアップ画面のみを提供する。
    database_url: str | None = None

    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440
    password_setup_token_expire_minutes: int = 2880

    admin_username: str | None = None
    admin_password: str | None = None

    mediamtx_api_base_url: str | None = None

    public_rtsps_host: str | None = None
    public_rtsps_port: int = 8322
    public_rtmp_host: str | None = None
    public_rtmp_port: int = 1935
    # RTSPS(暗号化)が見られない環境向けの非暗号フォールバック。RTSPの標準ポート(554)を
    # 使えばURLからポート番号を省略できる(トパーズチャット等と同じ方式)が、通信内容は
    # 暗号化されない。ホストはRTSPSと同じ配信サーバーを使う想定なのでpublic_rtsps_hostを流用する。
    public_rtsp_plain_port: int = 554

    discord_bot_token: str = ""

    # 一般ユーザーのログイン・利用申請はDiscord OAuthを必須とする(パスワード認証は
    # 初回セットアップで作成する管理者アカウントのみが例外的に使う)。
    discord_oauth_client_id: str | None = None
    discord_oauth_client_secret: str | None = None

    public_web_base_url: str | None = None

    cloudflare_tunnel_token: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(
            self.database_url
            and self.jwt_secret_key
            and self.admin_username
            and self.admin_password
            and self.discord_oauth_client_id
            and self.discord_oauth_client_secret
        )

    @property
    def discord_oauth_redirect_uri(self) -> str:
        return f"{self.public_web_base_url}/oauth/discord/callback"

    def playback_url(self, path_name: str) -> str:
        return f"rtsps://{self.public_rtsps_host}:{self.public_rtsps_port}/{path_name}"

    def playback_url_fallback(self, path_name: str) -> str:
        """RTSPSが再生できない環境向けの非暗号フォールバックURL。rtspt(RTSP over TCP)を
        使うと、標準ポート(554)なら省略でき、そうでなければ明示する。"""
        if self.public_rtsp_plain_port == 554:
            return f"rtspt://{self.public_rtsps_host}/{path_name}"
        return f"rtspt://{self.public_rtsps_host}:{self.public_rtsp_plain_port}/{path_name}"

    def push_url(self, path_name: str, stream_key: str) -> str:
        return f"rtmp://{self.public_rtmp_host}:{self.public_rtmp_port}/{path_name}?key={stream_key}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def generate_secret() -> str:
    return secrets.token_urlsafe(48)
