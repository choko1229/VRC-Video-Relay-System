import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    banned = "banned"


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # パスワードは初回セットアップで作成する管理者アカウントのみが使う(break-glass用)。
    # 一般ユーザーはDiscord OAuthが必須のため常にNULL。
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 一般ユーザーは申請時のDiscord OAuthで必ず設定される(adminのみNULL許容)。
    discord_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus), default=UserStatus.pending, nullable=False
    )
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.user, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    stream_key = relationship(
        "StreamKey", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
