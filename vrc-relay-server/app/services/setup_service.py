"""初回セットアップ画面(/setup)用のヘルパー。

.envへの書き込みと、DB接続情報の組み立て・疎通確認を担当する。
DB接続文字列を利用者に手入力させると書式ミス(jdbc:プレフィックスの混入、
パスワード中の記号の扱い違い、docker-compose専用ホスト名の流用等)が起きやすいため、
ホスト/ポート/ユーザー名/パスワード/DB名を個別に受け取り、ここで正しくURLを組み立てる。
"""

from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

# 可読性のための書き込み順(このリストに無いキーも末尾に残す)
_ENV_KEY_ORDER = [
    "APP_PORT",
    "DATABASE_URL",
    "JWT_SECRET_KEY",
    "JWT_ALGORITHM",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
    "PASSWORD_SETUP_TOKEN_EXPIRE_MINUTES",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "MEDIAMTX_API_BASE_URL",
    "PUBLIC_RTSPS_HOST",
    "PUBLIC_RTSPS_PORT",
    "PUBLIC_RTMP_HOST",
    "PUBLIC_RTMP_PORT",
    "DISCORD_OAUTH_CLIENT_ID",
    "DISCORD_OAUTH_CLIENT_SECRET",
    "DISCORD_BOT_TOKEN",
    "PUBLIC_WEB_BASE_URL",
    "CLOUDFLARE_TUNNEL_TOKEN",
]


class DatabaseConnectionError(Exception):
    pass


def build_database_url(host: str, port: int, username: str, password: str, database: str) -> str:
    return f"mysql+aiomysql://{quote_plus(username)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"


async def test_database_connection(database_url: str) -> None:
    """接続確認のみ行う使い捨てエンジンで疎通確認する。失敗時は例外を送出する。"""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise DatabaseConnectionError(str(exc)) from exc
    finally:
        await engine.dispose()


def read_existing_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def write_env(values: dict[str, str]) -> None:
    """既存の.env(主にAPP_PORT)を保持しつつ、渡された値で上書き・追記して保存する。"""
    merged = read_existing_env()
    merged.update(values)

    lines: list[str] = []
    for key in _ENV_KEY_ORDER:
        if key in merged:
            lines.append(f"{key}={merged.pop(key)}")
    for key, value in merged.items():
        lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
