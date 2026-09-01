import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ConnectionEventType(str, enum.Enum):
    publish_start = "publish_start"
    publish_end = "publish_end"
    auth_fail = "auth_fail"
    error = "error"


class ConnectionLog(Base):
    __tablename__ = "connection_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 認証失敗時はユーザーが特定できない場合もあるためnullable
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[ConnectionEventType] = mapped_column(
        Enum(ConnectionEventType), nullable=False
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
