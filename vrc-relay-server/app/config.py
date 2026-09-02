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

    discord_bot_token: str = ""

    public_web_base_url: str | None = None

    cloudflare_tunnel_token: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.database_url and self.jwt_secret_key and self.admin_username and self.admin_password)

    def playback_url(self, path_name: str) -> str:
        return f"rtsps://{self.public_rtsps_host}:{self.public_rtsps_port}/{path_name}"

    def push_url(self, path_name: str, stream_key: str) -> str:
        return f"rtmp://{self.public_rtmp_host}:{self.public_rtmp_port}/{path_name}?key={stream_key}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def generate_secret() -> str:
    return secrets.token_urlsafe(48)
