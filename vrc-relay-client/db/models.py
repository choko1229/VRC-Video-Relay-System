from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, LargeBinary, String, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DB_PATH = Path(__file__).resolve().parent.parent / "vrc_relay_client.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class AppConfig(Base):
    """key-value設定(公開サーバーURL等)。WebUIから変更可能。"""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class AuthToken(Base):
    """公開サーバーから発行されたJWT。Windows DPAPIで暗号化して保存する(平文保存禁止)。"""

    __tablename__ = "auth_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class RelaySettings(Base):
    """Tier2関連設定(ビットレート調整のしきい値等)。key-value。"""

    __tablename__ = "relay_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class LocalLog(Base):
    """接続ログ・エラーログ(短期保持1〜2週間)。"""

    __tablename__ = "local_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def add_log(level: str, message: str) -> None:
    with SessionLocal() as session:
        session.add(LocalLog(level=level, message=message, created_at=datetime.now(UTC)))
        session.commit()


def get_config(key: str, default: str | None = None) -> str | None:
    with SessionLocal() as session:
        row = session.get(AppConfig, key)
        return row.value if row is not None else default


def set_config(key: str, value: str) -> None:
    with SessionLocal() as session:
        row = session.get(AppConfig, key)
        if row is None:
            session.add(AppConfig(key=key, value=value))
        else:
            row.value = value
        session.commit()


def get_relay_setting(key: str, default: str | None = None) -> str | None:
    with SessionLocal() as session:
        row = session.get(RelaySettings, key)
        return row.value if row is not None else default


def set_relay_setting(key: str, value: str) -> None:
    with SessionLocal() as session:
        row = session.get(RelaySettings, key)
        if row is None:
            session.add(RelaySettings(key=key, value=value))
        else:
            row.value = value
        session.commit()


def purge_old_logs(retention_days: int = 14) -> None:
    from datetime import timedelta

    from sqlalchemy import delete

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    with SessionLocal() as session:
        session.execute(delete(LocalLog).where(LocalLog.created_at < cutoff))
        session.commit()
