from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440
    password_setup_token_expire_minutes: int = 2880

    admin_username: str = "admin"
    admin_password: str = "change_me"

    mediamtx_api_base_url: str = "http://mediamtx:9997"
    mediamtx_webhook_shared_secret: str = ""

    public_rtsps_host: str = "localhost"
    public_rtsps_port: int = 8322
    public_rtmp_host: str = "localhost"
    public_rtmp_port: int = 1935

    discord_bot_token: str = ""

    public_web_base_url: str = "http://localhost:8000"

    def playback_url(self, path_name: str) -> str:
        return f"rtsps://{self.public_rtsps_host}:{self.public_rtsps_port}/{path_name}"

    def push_url(self, path_name: str, stream_key: str) -> str:
        return f"rtmp://{self.public_rtmp_host}:{self.public_rtmp_port}/{path_name}?key={stream_key}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
