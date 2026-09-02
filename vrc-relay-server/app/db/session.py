from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def _ensure_initialized() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_maker
    if _session_maker is not None:
        return _session_maker

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URLが未設定です(セットアップが完了していません)")

    _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    _session_maker = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_maker


def reset() -> None:
    """セットアップ画面がDB接続情報を書き換えた直後に呼び出し、次回アクセス時に
    新しい接続情報でエンジンを再生成させる(プロセス再起動なしで反映するため)。"""
    global _engine, _session_maker
    _engine = None
    _session_maker = None


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    return _ensure_initialized()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    session_maker = _ensure_initialized()
    async with session_maker() as session:
        yield session
